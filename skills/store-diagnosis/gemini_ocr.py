#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用Gemini视觉模型读取店铺截图，提取结构化竞对数据
两阶段策略：第一批提取店铺基础信息，所有批次提取菜品，最后合并排序
"""
import json
import os
import sys
import time


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
    {"名称": "xxx", "月销": "61", "实际价格": 35.8, "折扣力度": 0, "分类": "门店热销", "是否福利放送": false, "是否单点不送": false}
  ]
}

菜品提取规则：
- 提取截图中看到的每一个菜品，不要遗漏
- 每个菜品记录：名称、月销、实际价格、所属分类
- 标注是否属于"福利放送"分类
- 标注是否标有"单点不送"
- 满减力度 = 减免额 ÷ 门槛
- 看不到的字段写 "未获取"
只返回JSON。'''


DISH_PROMPT = '''你是外卖店铺数据提取专家。请逐张仔细查看每张截图，提取看到的每一个菜品。不要遗漏任何菜品。

对每张截图，从上到下逐个读取菜品。每个菜品包含：
- 菜品名称（完整名称）
- 月销量（写原始值如"100+"、"61"、"月售48"）
- 价格（菜单显示的数字价格，如9.8、24.3）
- 所属分类（如"门店热销"、"广式糖水"、"解馋小吃"、"福利放送"等）

返回严格JSON：
{
  "菜品": [
    {"名称": "xxx", "月销": "61", "实际价格": 35.8, "折扣力度": 0, "分类": "xxx", "是否福利放送": false}
  ]
}

注意：
- 不要跳过任何菜品，即使只能看到部分信息
- "福利放送"分类下的菜品标记 是否福利放送=true
- 看不到月销或价格写"未获取"
只返回JSON。'''


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
    """调一次Gemini"""
    from google import genai
    contents = []
    for path in image_paths:
        with open(path, 'rb') as f:
            contents.append(genai.types.Part.from_bytes(data=f.read(), mime_type='image/jpeg'))
    contents.append(prompt)
    resp = client.models.generate_content(model=model, contents=contents)
    return _parse_json(resp.text)


def read_images_with_gemini(api_key, image_paths, model='gemini-2.5-flash'):
    """两阶段读图：先提店铺信息，再逐批提菜品，最后合并过滤排序"""
    from google import genai

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})

    batch_size = 5
    batches = [image_paths[i:i+batch_size] for i in range(0, len(image_paths), batch_size)]

    # 阶段1：第一批提取店铺基础信息 + 菜品
    print(f"    阶段1: 提取店铺信息（前{min(batch_size, len(image_paths))}张）...", file=sys.stderr)
    store_result = _call_gemini(client, model, batches[0], STORE_PROMPT)

    # 阶段2：剩余批次只提菜品
    all_dishes_raw = list(store_result.get("菜品", []))

    for i, batch in enumerate(batches[1:], 2):
        print(f"    阶段2: 提取菜品 批次{i}/{len(batches)}（{len(batch)}张）...", file=sys.stderr)
        try:
            result = _call_gemini(client, model, batch, DISH_PROMPT)
            all_dishes_raw.extend(result.get("菜品", []))
        except Exception as e:
            print(f"    批次{i}失败: {e}", file=sys.stderr)
        time.sleep(2)  # 避免rate limit

    # 阶段3：合并去重过滤排序
    print(f"    阶段3: 合并{len(all_dishes_raw)}个菜品，过滤排序...", file=sys.stderr)

    # 去重（同名取最大月销）
    dishes_map = {}
    for d in all_dishes_raw:
        name = d.get("名称", "").strip()
        if not name or len(name) < 2:
            continue

        # 只过滤福利放送分类（Gemini对"单点不送"判断不准，不用它过滤）
        if d.get("是否福利放送", False):
            continue
        cat = str(d.get("分类", ""))
        if "福利" in cat:
            continue
        # 过滤明确的非菜品和分类名
        skip_words = ["蘸料", "小料", "调料", "米饭", "餐具", "纸巾", "餐盒", "筷子",
                       "第一款", "第二款", "招牌广式", "招牌系列", "精选系列"]
        if any(w in name for w in skip_words):
            continue
        # 过滤分类名误识别为菜品
        cat_names = ["系列", "分类", "专区", "合集", "广式糖水", "门店热销",
                      "解馋小吃", "粉面主食", "超值套餐", "招牌双皮奶",
                      "汤圆系列", "椰奶西米", "嫩滑豆花", "饱腹简餐",
                      "杯装饮品", "麻薯系列", "斑斓冻冻", "福利放送",
                      "店铺环境", "神枪手活动", "进店必看"]
        if any(name == cn or name.startswith(cn) for cn in cat_names):
            continue

        import re
        sales_raw = str(d.get("月销", "0"))
        # 清理月销：提取第一个数字（可能返回"月售48 15人觉得份量足"等格式）
        sales_match = re.search(r'(\d+)', sales_raw)
        sales_num = int(sales_match.group(1)) if sales_match else 0
        # 标准化月销显示
        sales_display = f"{sales_num}+" if sales_num >= 100 else str(sales_num)

        # 过滤无效菜名
        if name in ["未获取", "无", "—", "-"] or len(name) < 2:
            continue

        # 模糊去重：找是否已有相似菜名（包含关系或编辑距离很近）
        matched_key = None
        for existing_name in dishes_map:
            # 一个包含另一个，或者只差1-2个字
            if existing_name in name or name in existing_name:
                matched_key = existing_name
                break
            # 共同字符超过80%且长度差不超过2
            common = set(existing_name) & set(name)
            if (len(common) >= max(len(existing_name), len(name)) * 0.8
                and abs(len(existing_name) - len(name)) <= 2
                and len(common) >= 3):
                matched_key = existing_name
                break

        if matched_key:
            # 合并到已有的，取月销更大的
            if sales_num > dishes_map[matched_key]["_sales"]:
                dishes_map[matched_key] = {
                    "名称": name if len(name) > len(matched_key) else matched_key,
                    "月销": sales_display,
                    "实际价格": d.get("实际价格", "未获取") if d.get("实际价格", "未获取") != "未获取" else dishes_map[matched_key]["实际价格"],
                    "折扣力度": d.get("折扣力度", 0),
                    "_sales": sales_num,
                }
        elif sales_num > 0:
            dishes_map[name] = {
                "名称": name,
                "月销": sales_display,
                "实际价格": d.get("实际价格", "未获取"),
                "折扣力度": d.get("折扣力度", 0),
                "_sales": sales_num,
            }

    # 排序取Top10
    sorted_dishes = sorted(dishes_map.values(), key=lambda x: x["_sales"], reverse=True)
    top10 = [{k: v for k, v in d.items() if k != "_sales"} for d in sorted_dishes[:10]]

    # 组装最终结果
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
        "热销菜": top10,
    }

    print(f"    完成: {final['店铺名称']} | {len(top10)}个热销菜（从{len(all_dishes_raw)}个中筛选）", file=sys.stderr)
    return final


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Gemini视觉读图')
    parser.add_argument('images', nargs='+', help='图片文件路径')
    parser.add_argument('--key', default=None, help='Gemini API Key')
    args = parser.parse_args()

    api_key = args.key or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print("错误: 需要GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    valid = [p for p in args.images if os.path.exists(p)]
    if not valid:
        print("错误: 没有有效的图片文件", file=sys.stderr)
        sys.exit(1)

    result = read_images_with_gemini(api_key, valid)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
