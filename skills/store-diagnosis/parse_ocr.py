#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析OCR文字 → 结构化竞对JSON
用法:
  python3 ocr_images.py *.jpg | python3 parse_ocr.py
  python3 parse_ocr.py ocr_result.json
"""
import json
import re
import sys


def parse_store_info(frames_data):
    """从第一帧提取店铺基础信息"""
    info = {
        "店铺名称": "未获取", "平台": "未获取", "店铺评分": "未获取",
        "营业时间": "未获取", "月销": "未获取", "实际配送费": "未获取",
        "配送方式": "未获取", "评价数": "未获取", "差评数": "未获取",
        "差评率": "未获取", "满减档位": "未获取", "满减档位数": "未获取",
        "第一档满减力度": "未获取", "第二档满减力度": "未获取", "其他活动": "未获取",
    }

    # 收集所有文字
    all_items = []
    for fname in sorted(frames_data.keys()):
        for item in frames_data[fname]:
            all_items.append(item)

    full_text = " ".join(t["text"] for t in all_items)

    # 平台
    if any(k in full_text for k in ["美团", "美团快送", "美团配送", "美团全城送", "美团金"]):
        info["平台"] = "美团"
    elif any(k in full_text for k in ["饿了么", "蜂鸟", "蜂鸟准时达"]):
        info["平台"] = "饿了么"

    # 店铺名称 — 找最长的含"店/铺/馆"的文字，或含中文·的
    for item in all_items[:80]:
        text = item["text"]
        # 带括号的店名：XX(XX店)
        if re.search(r'[\u4e00-\u9fa5].+\(.*[店铺馆堂]\)', text) and len(text) >= 6:
            info["店铺名称"] = text
            break
        # XX铺·XX·XX 格式
        if "·" in text and len(text) >= 5 and re.search(r'[\u4e00-\u9fa5]', text):
            # 可能被截断，取最完整的一个
            if len(text) > len(info["店铺名称"]) or info["店铺名称"] == "未获取":
                info["店铺名称"] = text.rstrip("(（")
        # XX店/铺
        m = re.search(r'([\u4e00-\u9fa5]{2,}(?:店|铺|馆)[\u4e00-\u9fa5]*(?:\([^)]+\))?)', text)
        if m and len(m.group(1)) >= 5 and info["店铺名称"] == "未获取":
            info["店铺名称"] = m.group(1)

    # 评分 — 找第一帧里的 X.X 格式数字（在评分/月售附近）
    for item in all_items[:50]:
        m = re.match(r'^([45]\.\d)$', item["text"])
        if m:
            info["店铺评分"] = float(m.group(1))
            break

    # 月销 — 找 "XXX+" 或 "月售XXX"
    for item in all_items[:50]:
        m = re.match(r'^(\d{2,})\+?$', item["text"])
        if m and int(m.group(1).replace("+","")) >= 50:
            val = item["text"]
            if not val.endswith("+"):
                val += "+"
            info["月销"] = val
            break
        m = re.search(r'月售?\s*(\d+\+?)', item["text"])
        if m and int(m.group(1).replace("+","")) >= 50:
            info["月销"] = m.group(1)
            break

    # 评价数
    for item in all_items[:80]:
        m = re.search(r'评价\s*(\d+)', item["text"])
        if m:
            info["评价数"] = int(m.group(1))
            break

    # 配送费
    if "免配送" in full_text or "免起送" in full_text:
        info["实际配送费"] = "0元"
    else:
        m = re.search(r'配送费?\s*[¥￥]?\s*(\d+\.?\d*)', full_text)
        if m:
            info["实际配送费"] = f"{m.group(1)}元"

    # 配送方式
    for kw in ["蜂鸟准时达", "蜂鸟专送", "蜂鸟快送", "美团快送", "美团专送",
                "美团配送", "美团全城送", "美团金配送", "商家自配"]:
        if kw in full_text:
            info["配送方式"] = kw
            break

    # 满减 — 只匹配合理范围（门槛10-200，减免1-50）
    manjian_items = []
    for item in all_items:
        matches = re.findall(r'(\d{2,3})\s*[减\-]\s*(\d{1,2})', item["text"])
        for m_str, j_str in matches:
            m_val, j_val = int(m_str), int(j_str)
            if 10 <= m_val <= 200 and 1 <= j_val <= 50 and j_val < m_val:
                manjian_items.append((m_val, j_val))

    if manjian_items:
        # 去重排序
        unique = sorted(set(manjian_items))
        info["满减档位"] = "，".join(f"{m}-{j}" for m, j in unique)
        info["满减档位数"] = len(unique)
        if len(unique) >= 1:
            info["第一档满减力度"] = round(unique[0][1] / unique[0][0], 3)
        if len(unique) >= 2:
            info["第二档满减力度"] = round(unique[1][1] / unique[1][0], 3)

    # 其他活动
    activities = []
    for pat in [r'折扣商品.*?折起', r'新人立减\d+', r'新客立减\d+',
                r'收藏.*?券', r'神券', r'超\d+分钟免单',
                r'\d\.\d折', r'[Vv]\d+满\d+可用', r'黑钻.*?可用']:
        ms = re.findall(pat, full_text)
        activities.extend(ms)
    if activities:
        info["其他活动"] = ";".join(dict.fromkeys(activities))

    return info


def parse_dishes(frames_data):
    """从OCR数据中提取菜品（利用坐标信息）"""
    # 收集所有帧的文字块，按帧分组
    dishes = {}  # {菜名: {月销数值, 月销文本, 价格}}
    in_fuli = False  # 福利放送区域标记

    for fname in sorted(frames_data.keys()):
        items = frames_data[fname]
        # 按y坐标排序
        items_sorted = sorted(items, key=lambda t: (t["y"], t["x"]))

        frame_in_fuli = False
        for i, item in enumerate(items_sorted):
            text = item["text"]

            # 检测福利放送区域
            if "福利放送" in text:
                frame_in_fuli = True
                continue
            # 检测离开福利放送（进入其他分类）
            if frame_in_fuli and any(k in text for k in [
                "门店热销", "招牌双皮", "汤圆系列", "广式糖水",
                "解馋小吃", "嫩滑豆花", "椰奶西米", "粉面主食",
                "超值套餐", "麻薯系列", "斑斓冻冻", "杯装饮品",
                "饱腹简餐", "顺德风味"
            ]):
                frame_in_fuli = False

            if frame_in_fuli:
                continue

            # 跳过杯装饮品/店铺环境/神枪手活动
            if any(k in text for k in ["杯装饮品", "店铺环境", "神枪手活动"]):
                break  # 这些在菜单末尾，后面不看了

            # 找月售信息
            m = re.search(r'月售?\s*(\d+)(\+?)', text)
            if not m:
                continue

            sales_num = int(m.group(1))
            sales_str = m.group(1) + m.group(2)

            if sales_num < 1:
                continue

            # 检查附近是否有"单点不送"
            context_texts = []
            for j in range(max(0, i-2), min(len(items_sorted), i+3)):
                context_texts.append(items_sorted[j]["text"])
            context = " ".join(context_texts)
            if "单点不送" in context or "起购" in context:
                continue

            # 向上找菜名（y坐标比月售小，x坐标在右侧区域x>150）
            dish_name = None
            my_y = item["y"]
            for back in range(1, min(5, i + 1)):
                candidate = items_sorted[i - back]
                c_text = candidate["text"].strip()
                c_y = candidate["y"]
                c_x = candidate["x"]

                # 菜名应该在月售上方（y差<100），右侧内容区（x>150）
                if my_y - c_y > 120:
                    break  # 太远了

                # 过滤非菜名
                if len(c_text) < 2:
                    continue
                if re.match(r'^[\d.:¥￥%+\-\s]+$', c_text):
                    continue
                # 过滤UI文字/分类名
                skip_words = [
                    "月售", "评价", "点菜", "商家", "温馨", "选规格", "选套餐",
                    "门店", "福利", "招牌双皮", "汤圆系列", "广式糖水",
                    "解馋小吃", "椰奶西米", "粉面主食", "超值套餐",
                    "外送", "自取", "预订", "拼单", "觉得", "回头客",
                    "人已下单", "网友推荐", "味道赞", "分量足", "味道逼赞",
                    "单点不送", "起购", "免起送", "配送", "门店招牌",
                    "嫩滑豆花", "饱腹简餐", "顺德风味", "迸店必看",
                    "物有所值", "点评", "不是很辣", "凉皮很香",
                    "食材新鲜", "觉得咏", "口感嫩滑", "低糖健康",
                    "人觉得", "现在预订", "后配送", "超优惠",
                    "个", "红薯", "鸡腿", "份", "杯", "条", "粒",  # 单位词
                    "招牌", "新品", "热卖", "必点",  # 标签
                ]
                if any(sw in c_text for sw in skip_words):
                    continue
                if len(c_text) <= 2 and not re.search(r'[\u4e00-\u9fa5]{2}', c_text):
                    continue
                # 过滤纯数字/标点/英文碎片
                if re.match(r'^[a-zA-Z\s\d.,:;!?]+$', c_text):
                    continue

                dish_name = c_text
                break

            if not dish_name or len(dish_name) < 2:
                continue

            # 清理菜名
            dish_name = re.sub(r'^[🔥❤️♨️☀️🌟💕\s!！]+', '', dish_name)
            dish_name = re.sub(r'\s+', '', dish_name)
            # 去掉开头的"招牌"标签（如果后面还有内容）
            dish_name = re.sub(r'^招牌\s*', '', dish_name) if len(dish_name) > 4 else dish_name
            dish_name = dish_name.strip("!！ ")

            if len(dish_name) < 2:
                continue

            # 向下找价格（¥/半/羊 + 数字）
            price = "未获取"
            for fwd in range(0, min(5, len(items_sorted) - i)):
                price_text = items_sorted[i + fwd]["text"]
                # OCR经常把¥识别成"半"或"羊"
                pm = re.search(r'[¥￥半羊]\s*(\d+\.?\d*)', price_text)
                if pm:
                    price = float(pm.group(1))
                    break
                # 也可能是纯数字价格 如 "9.8"
                if fwd > 0:  # 不匹配月售本身
                    pm = re.match(r'^(\d{1,3}\.\d{1,2})$', price_text.strip())
                    if pm and 1 < float(pm.group(1)) < 200:
                        price = float(pm.group(1))
                        break

            # 存储（同名取最大月销）
            if dish_name not in dishes or sales_num > dishes[dish_name]["sales_num"]:
                dishes[dish_name] = {
                    "名称": dish_name,
                    "月销": sales_str,
                    "sales_num": sales_num,
                    "实际价格": price,
                    "折扣力度": 0,
                }

    # 按月销排序取Top10
    sorted_dishes = sorted(dishes.values(), key=lambda x: x["sales_num"], reverse=True)
    result = []
    for d in sorted_dishes[:10]:
        result.append({
            "名称": d["名称"],
            "月销": d["月销"],
            "实际价格": d["实际价格"],
            "折扣力度": d["折扣力度"],
        })
    return result


def parse_ocr_data(ocr_data):
    """解析一个视频的OCR数据"""
    info = parse_store_info(ocr_data)
    dishes = parse_dishes(ocr_data)
    info["热销菜"] = dishes
    return info


def main():
    if len(sys.argv) > 1 and sys.argv[1] != '-':
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            raw = json.load(f)
    else:
        raw = json.load(sys.stdin)

    if isinstance(raw, dict):
        result = parse_ocr_data(raw)
        print(json.dumps([result], ensure_ascii=False, indent=2))
    elif isinstance(raw, list):
        results = []
        for item in raw:
            if isinstance(item, dict) and "ocr" in item:
                result = parse_ocr_data(item["ocr"])
            else:
                result = parse_ocr_data(item)
            results.append(result)
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
