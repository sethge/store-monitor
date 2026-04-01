#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析OCR文字 → 结构化竞对JSON
用法:
  python3 ocr_images.py *.jpg | python3 parse_ocr.py
  python3 parse_ocr.py ocr_result.json

不依赖视觉模型，纯文本解析。
"""
import json
import re
import sys


def parse_store_info(all_texts):
    """从所有帧的OCR文字中提取店铺基础信息"""
    full_text = "\n".join(all_texts)

    info = {
        "店铺名称": "未获取",
        "平台": "未获取",
        "店铺评分": "未获取",
        "营业时间": "未获取",
        "月销": "未获取",
        "实际配送费": "未获取",
        "配送方式": "未获取",
        "评价数": "未获取",
        "差评数": "未获取",
        "差评率": "未获取",
        "满减档位": "未获取",
        "满减档位数": "未获取",
        "第一档满减力度": "未获取",
        "第二档满减力度": "未获取",
        "其他活动": "未获取",
    }

    # 平台判断
    if any(k in full_text for k in ["美团", "美团快送", "美团配送", "美团全城送"]):
        info["平台"] = "美团"
    elif any(k in full_text for k in ["饿了么", "蜂鸟", "蜂鸟准时达"]):
        info["平台"] = "饿了么"

    # 评分（格式：4.5 或 评分4.5）
    m = re.search(r'(?:评分|评价)\s*(\d\.\d)', full_text)
    if not m:
        m = re.search(r'\b([45]\.\d)\b', full_text)
    if m:
        info["店铺评分"] = float(m.group(1))

    # 月销
    m = re.search(r'月售?\s*(\d+\+?)', full_text)
    if m:
        info["月销"] = m.group(1)

    # 评价数
    m = re.search(r'评价\s*(\d+)', full_text)
    if m:
        info["评价数"] = int(m.group(1))

    # 配送费
    if "免配送" in full_text or "免起送" in full_text or "0元配送" in full_text:
        info["实际配送费"] = "0元"
    else:
        m = re.search(r'配送费?\s*[¥￥]?\s*(\d+\.?\d*)', full_text)
        if m:
            info["实际配送费"] = f"{m.group(1)}元"

    # 配送方式
    for kw in ["蜂鸟准时达", "蜂鸟专送", "蜂鸟快送", "美团快送", "美团专送", "美团配送", "美团全城送", "商家自配"]:
        if kw in full_text:
            info["配送方式"] = kw
            break

    # 满减
    manjian = re.findall(r'满?\s*(\d+)\s*[减-]\s*(\d+)', full_text)
    if manjian:
        # 去重
        seen = set()
        unique = []
        for m, j in manjian:
            key = f"{m}-{j}"
            if key not in seen:
                seen.add(key)
                unique.append((int(m), int(j)))
        unique.sort(key=lambda x: x[0])
        info["满减档位"] = "，".join(f"{m}-{j}" for m, j in unique)
        info["满减档位数"] = len(unique)
        if len(unique) >= 1:
            info["第一档满减力度"] = round(unique[0][1] / unique[0][0], 3)
        if len(unique) >= 2:
            info["第二档满减力度"] = round(unique[1][1] / unique[1][0], 3)

    # 其他活动
    activities = []
    activity_patterns = [
        r'折扣商品.*?折起', r'新人立减\d+', r'新客立减\d+',
        r'收藏.*?券', r'神券', r'免配送', r'超\d+分钟免单',
        r'\d+\.\d折', r'福利放送',
        r'[Vv]\d+满\d+可用', r'黑钻会员.*?可用',
    ]
    for pat in activity_patterns:
        ms = re.findall(pat, full_text)
        activities.extend(ms)
    if activities:
        info["其他活动"] = ";".join(dict.fromkeys(activities))  # 去重保序

    # 店铺名称（通常在第一帧，找"XX店"或"XX铺"格式）
    for text in all_texts[:30]:  # 只看前面的文字
        # 匹配带括号的店名 或 带·的店名
        m = re.search(r'([\u4e00-\u9fa5·]+(?:店|铺|馆|堂|坊|阁|轩|居|家|斋)[\u4e00-\u9fa5·]*(?:\([^)]+\))?)', text)
        if m and len(m.group(1)) >= 4:
            info["店铺名称"] = m.group(1)
            break
        # 匹配 XX·XX·XX 格式
        m = re.search(r'([\u4e00-\u9fa5]+·[\u4e00-\u9fa5·]+)', text)
        if m and len(m.group(1)) >= 5:
            info["店铺名称"] = m.group(1)
            break

    return info


def parse_dishes(all_texts):
    """从OCR文字中提取菜品列表"""
    dishes = {}  # {菜名: {月销, 价格}}

    # 排除关键词（福利放送/单点不送/小料/饮料等）
    exclude_keywords = ["福利放送", "单点不送", "起购", "蘸料", "调料", "米饭", "餐具"]
    # 福利放送区域标记
    in_fuli = False

    i = 0
    while i < len(all_texts):
        text = all_texts[i]

        # 检测福利放送区域
        if "福利放送" in text:
            in_fuli = True
            i += 1
            continue
        # 检测离开福利放送区域（进入其他分类）
        if in_fuli and any(k in text for k in ["门店热销", "招牌双皮", "汤圆系列", "广式糖水",
                                                  "解馋小吃", "嫩滑豆花", "椰奶西米", "粉面主食",
                                                  "超值套餐", "麻薯系列", "斑斓冻冻", "杯装饮品",
                                                  "神枪手活动", "店铺环境", "饱腹简餐"]):
            in_fuli = False

        # 跳过福利放送区域
        if in_fuli:
            i += 1
            continue

        # 跳过杯装饮品分类
        if "杯装饮品" in text:
            # 跳到下一个分类
            i += 1
            while i < len(all_texts):
                if any(k in all_texts[i] for k in ["神枪手", "店铺环境", "超值套餐", "麻薯"]):
                    break
                i += 1
            continue

        # 检测月销
        m = re.search(r'月售?\s*(\d+\+?)', text)
        if m:
            sales_str = m.group(1)
            sales_num = int(sales_str.replace("+", ""))

            # 向前找菜名（通常在月售的前1-3行）
            dish_name = None
            for back in range(1, min(4, i + 1)):
                candidate = all_texts[i - back]
                # 菜名特征：中文为主，长度3-20，不是纯数字/时间/UI文字
                if (len(candidate) >= 2
                    and not re.match(r'^[\d.:¥￥%+\s]+$', candidate)
                    and not any(skip in candidate for skip in [
                        "月售", "评价", "点菜", "商家", "温馨", "选规格",
                        "门店", "福利", "招牌双皮", "汤圆系列", "广式糖水",
                        "解馋小吃", "椰奶西米", "粉面主食", "超值套餐",
                        "外送", "自取", "预订", "拼单", "觉得", "回头客",
                        "人已下单", "网友推荐", "味道赞", "分量足",
                        "单点不送", "起购", "免起送", "配送",
                    ])):
                    dish_name = candidate
                    break

            if dish_name:
                # 清理菜名
                dish_name = re.sub(r'^[🔥❤️♨️☀️🌟💕\s]+', '', dish_name)
                dish_name = dish_name.strip()

                if not dish_name or len(dish_name) < 2:
                    i += 1
                    continue

                # 检查排除词
                context = " ".join(all_texts[max(0, i-3):i+3])
                if any(ex in context for ex in exclude_keywords):
                    i += 1
                    continue

                # 向后找价格
                price = "未获取"
                for fwd in range(0, min(4, len(all_texts) - i)):
                    pm = re.search(r'[¥￥]\s*(\d+\.?\d*)', all_texts[i + fwd])
                    if pm:
                        price = float(pm.group(1))
                        break

                # 存储（取最大月销，避免重复）
                if dish_name not in dishes or sales_num > dishes[dish_name].get("sales_num", 0):
                    dishes[dish_name] = {
                        "名称": dish_name,
                        "月销": sales_str,
                        "sales_num": sales_num,
                        "实际价格": price,
                        "折扣力度": 0,
                    }

        i += 1

    # 按月销排序，取Top10
    sorted_dishes = sorted(dishes.values(), key=lambda x: x["sales_num"], reverse=True)

    # 移除内部排序字段
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
    """解析一个视频的OCR数据 → 结构化JSON"""
    # 收集所有文字（按帧顺序）
    all_texts = []
    for frame_name in sorted(ocr_data.keys()):
        for item in ocr_data[frame_name]:
            all_texts.append(item["text"])

    info = parse_store_info(all_texts)
    dishes = parse_dishes(all_texts)
    info["热销菜"] = dishes

    return info


def main():
    # 读取OCR JSON
    if len(sys.argv) > 1 and sys.argv[1] != '-':
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            raw = json.load(f)
    else:
        raw = json.load(sys.stdin)

    # 判断输入格式：
    # 单个视频：{"scene_001.jpg": [...], "scene_002.jpg": [...]}
    # 多个视频（从extract+ocr管道）：[{"video": "xxx", "ocr": {...}}, ...]
    if isinstance(raw, dict):
        # 单个视频的OCR结果
        result = parse_ocr_data(raw)
        print(json.dumps([result], ensure_ascii=False, indent=2))
    elif isinstance(raw, list):
        # 多个视频
        results = []
        for item in raw:
            if isinstance(item, dict) and "ocr" in item:
                result = parse_ocr_data(item["ocr"])
                results.append(result)
            else:
                result = parse_ocr_data(item)
                results.append(result)
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
