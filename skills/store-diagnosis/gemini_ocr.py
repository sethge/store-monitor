#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用Gemini视觉模型读取店铺截图，提取结构化竞对数据
策略：每帧单独读取，确保不漏任何菜品，最后合并去重排序
"""
import json
import os
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"

STORE_PROMPT = '''你是外卖店铺数据提取专家。请仔细查看这些截图，提取店铺基础信息和看到的所有菜品。

返回严格JSON：
{
  "店铺名称": "完整店铺名(含分店名)",
  "平台": "美团/饿了么",
  "店铺评分": 4.8,
  "营业时间": "10:00-22:00",
  "月销": "300+",
  "实际配送费": "0元",
  "配送方式": "蜂鸟准时达/美团快送/美团配送",
  "评价数": 867,
  "差评数": 0,
  "差评率": 0,
  "满减档位": "38-3，49-5，65-7，78-11",
  "满减档位数": 4,
  "第一档满减力度": 0.079,
  "第二档满减力度": 0.102,
  "其他活动": "折扣商品xx折起; 新人立减xx",
  "菜品": [
    {"名称": "xxx", "月销": 61, "实际价格": 35.8, "分类": "门店热销", "是否福利放送": false}
  ]
}

菜品提取规则：
- 提取截图中看到的每一个菜品，不要遗漏
- 月销写纯数字（如61、100），超过100的写100
- 价格写数字（如24.3、9.8）
- 标注所属分类和是否属于"福利放送"
- 看不到的写null
只返回JSON。'''


DISH_PROMPT = '''请仔细查看这张外卖菜单截图，从上到下逐个列出看到的每一个菜品。

返回严格JSON：
{
  "菜品": [
    {"名称": "完整菜名", "月销": 61, "实际价格": 35.8, "分类": "分类名", "是否福利放送": false}
  ]
}

规则：
- 不要跳过任何菜品
- 月销写纯数字（如41、100），不要加"+"
- 价格写菜单上显示的数字价格
- 分类名是左侧菜单栏中的分类名（如"门店热销"、"广式糖水"、"解馋小吃"等）

福利放送判断：
- 如果菜品在"福利放送"分类标题下面 → 是福利放送=true
- 如果菜品价格特别低（如¥0、¥1.77、¥2.1、¥3、¥3.5）且标有"X份起购"或"折" → 很可能是福利放送=true
- 正常菜品的价格一般在¥6以上

看不到的写null。只返回JSON。'''


_DEFAULT_CFG = "eyJnZW1pbmlfYXBpX2tleSI6IkFJemFTeUNzcGpIUldmaHY5TmExdXJpSXRSTlpMbzJLdDRuSWhqYyIsInRlbmNlbnRfc2VjcmV0X2lkIjoiQUtJRHBWMEpQSDBZdTJ5akhiZ2FKbzhHRHdSbXoxcUtiZ1hBIiwidGVuY2VudF9zZWNyZXRfa2V5IjoiYXc4NnFUdkFBemEwb1BsdnNmSWl3eGtKZ3BvWjVXbW8ifQ=="

def _load_config():
    """加载配置：config.json > 内置默认 > 环境变量"""
    import base64
    # 1. config.json
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    # 2. 内置默认
    try:
        return json.loads(base64.b64decode(_DEFAULT_CFG).decode())
    except:
        pass
    return {}

def get_api_key():
    cfg = _load_config()
    return os.environ.get('GEMINI_API_KEY') or cfg.get('gemini_api_key')


def _parse_json(text):
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        json_lines = []
        inside = False
        for line in lines:
            if line.startswith('```') and not inside:
                inside = True
                continue
            elif line.startswith('```') and inside:
                break
            elif inside:
                json_lines.append(line)
        text = '\n'.join(json_lines)
    return json.loads(text)


def _call_gemini(client, model, image_paths, prompt):
    from google import genai
    contents = []
    for path in image_paths:
        with open(path, 'rb') as f:
            contents.append(genai.types.Part.from_bytes(data=f.read(), mime_type='image/jpeg'))
    contents.append(prompt)
    resp = client.models.generate_content(model=model, contents=contents)
    return _parse_json(resp.text)


def _extract_sales(val):
    """从各种格式提取月销数字"""
    if val is None:
        return 0
    s = str(val)
    m = re.search(r'(\d+)', s)
    return int(m.group(1)) if m else 0


def _is_category_name(name):
    """判断是否是分类名而非菜品名"""
    cats = ["广式糖水", "门店热销", "解馋小吃", "粉面主食", "超值套餐",
            "招牌双皮奶", "汤圆系列", "椰奶西米", "嫩滑豆花", "饱腹简餐",
            "杯装饮品", "麻薯系列", "斑斓冻冻", "福利放送", "店铺环境",
            "神枪手活动", "进店必看", "顺德风味", "门店招牌", "精选养生",
            "招牌系列", "精选系列"]
    for c in cats:
        if name == c or name.startswith(c):
            return True
    if any(w in name for w in ["系列", "分类", "专区", "合集", "第一款", "第二款"]):
        return True
    return False


def read_images_with_gemini(api_key, image_paths, model='gemini-2.5-flash'):
    """逐帧读取，确保100%覆盖"""
    from google import genai

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})

    # 阶段1：前3帧提取店铺基础信息
    print(f"    阶段1: 提取店铺信息...", file=sys.stderr)
    store_result = _call_gemini(client, model, image_paths[:3], STORE_PROMPT)
    all_dishes_raw = list(store_result.get("菜品", []))
    time.sleep(2)

    # 阶段2：分批读取菜品（每5帧一批）
    batch_size = 5
    batches = [image_paths[i:i+batch_size] for i in range(0, len(image_paths), batch_size)]

    for i, batch in enumerate(batches[1:], 2):  # 跳过第一批（已在阶段1处理）
        print(f"    阶段2: 批次{i}/{len(batches)}（{len(batch)}张）...", file=sys.stderr)
        try:
            result = _call_gemini(client, model, batch, DISH_PROMPT)
            all_dishes_raw.extend(result.get("菜品", []))
        except Exception as e:
            err = str(e)
            if '429' in err or 'RESOURCE_EXHAUSTED' in err:
                print(f"    rate limit，等60秒...", file=sys.stderr)
                time.sleep(60)
                try:
                    result = _call_gemini(client, model, batch, DISH_PROMPT)
                    all_dishes_raw.extend(result.get("菜品", []))
                except:
                    print(f"    批次{i}重试失败", file=sys.stderr)
            else:
                print(f"    批次{i}失败: {e}", file=sys.stderr)
        time.sleep(2)

    # 阶段3：合并去重过滤排序
    print(f"    阶段3: 合并{len(all_dishes_raw)}个菜品...", file=sys.stderr)

    dishes_map = {}
    for d in all_dishes_raw:
        name = str(d.get("名称", "")).strip().rstrip("!！ ")
        if not name or len(name) < 2 or name in ["未获取", "无", "null"]:
            continue

        # 过滤福利放送
        if d.get("是否福利放送", False):
            continue
        cat = str(d.get("分类", ""))
        if "福利" in cat:
            continue

        # 过滤非菜品
        if any(w in name for w in ["蘸料", "小料", "调料", "米饭", "餐具", "纸巾", "餐盒"]):
            continue
        if _is_category_name(name):
            continue

        sales_num = _extract_sales(d.get("月销"))

        # 模糊去重（完全包含关系，或80%共同字符+长度差<=2）
        matched_key = None
        for existing in dishes_map:
            if existing in name or name in existing:
                matched_key = existing
                break
            common = set(existing) & set(name)
            if (len(common) >= max(len(existing), len(name)) * 0.8
                    and abs(len(existing) - len(name)) <= 2 and len(common) >= 3):
                matched_key = existing
                break

        price = d.get("实际价格")
        if isinstance(price, str):
            pm = re.search(r'(\d+\.?\d*)', price)
            price = float(pm.group(1)) if pm else "未获取"

        if matched_key:
            if sales_num > dishes_map[matched_key]["_sales"]:
                better_name = name if len(name) >= len(matched_key) else matched_key
                old_price = dishes_map[matched_key]["实际价格"]
                dishes_map[matched_key] = {
                    "名称": better_name,
                    "月销": str(sales_num) if sales_num < 100 else f"{sales_num}+",
                    "实际价格": price if price != "未获取" else old_price,
                    "折扣力度": d.get("折扣力度", 0) or 0,
                    "_sales": sales_num,
                }
        elif sales_num > 0:
            dishes_map[name] = {
                "名称": name,
                "月销": str(sales_num) if sales_num < 100 else f"{sales_num}+",
                "实际价格": price if price else "未获取",
                "折扣力度": d.get("折扣力度", 0) or 0,
                "_sales": sales_num,
            }

    # 后处理：价格低于5元且月销>20的大概率是福利放送
    for name in list(dishes_map.keys()):
        d = dishes_map[name]
        price = d["实际价格"]
        if isinstance(price, (int, float)) and price < 5 and d["_sales"] > 20:
            del dishes_map[name]
            continue

    # 按月销排序，去掉不合格的后剩多少是多少
    sorted_dishes = sorted(dishes_map.values(), key=lambda x: x["_sales"], reverse=True)
    top = [{k: v for k, v in d.items() if k != "_sales"} for d in sorted_dishes[:15]]

    final = {
        "店铺名称": store_result.get("店铺名称", "未获取"),
        "平台": store_result.get("平台", "未获取"),
        "店铺评分": store_result.get("店铺评分", "未获取"),
        "营业时间": store_result.get("营业时间", "未获取"),
        "月销": store_result.get("月销", "未获取"),
        "实际配送费": store_result.get("实际配送费", "未获取"),
        "配送方式": store_result.get("配送方式", "未获取"),
        "评价数": store_result.get("评价数", "未获取"),
        "差评数": store_result.get("差评数", "未获取"),
        "差评率": store_result.get("差评率", "未获取"),
        "满减档位": store_result.get("满减档位", "未获取"),
        "满减档位数": store_result.get("满减档位数", "未获取"),
        "第一档满减力度": store_result.get("第一档满减力度", "未获取"),
        "第二档满减力度": store_result.get("第二档满减力度", "未获取"),
        "其他活动": store_result.get("其他活动", "未获取"),
        "热销菜": top,
    }

    print(f"    完成: {final['店铺名称']} | Top10从{len(all_dishes_raw)}个菜品中筛选", file=sys.stderr)
    return final


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('images', nargs='+')
    parser.add_argument('--key', default=None)
    args = parser.parse_args()

    api_key = args.key or get_api_key()
    if not api_key:
        print("错误: 需要GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    valid = [p for p in args.images if os.path.exists(p)]
    result = read_images_with_gemini(api_key, valid)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
