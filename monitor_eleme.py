#!/usr/bin/env python3
"""
饿了么（淘宝闪送）商家后台巡检
通过拦截API获取评价/评分/活动数据
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path


BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SCREENSHOT_DIR = DATA_DIR / "screenshots"


async def scrape_eleme(page):
    """对当前已登录的饿了么页面执行巡检，返回完整数据"""

    # 找饿了么页面
    ele_page = None
    for p in page.context.pages:
        if 'ele.me' in p.url and 'melody' in p.url:
            ele_page = p
            break

    if not ele_page:
        return None

    # 提取shopId
    m = re.search(r'/shop/(\d+)/', ele_page.url)
    shop_id = m.group(1) if m else ""

    captured = {}

    async def on_response(response):
        url = response.url
        try:
            if 'getRateResult' in url:
                captured['reviews'] = await response.json()
            elif 'getShopRateStatsV2' in url:
                captured['stats'] = await response.json()
            elif 'getActivitiesByDate' in url:
                captured['activities_by_date'] = await response.json()
            elif 'method=MarketingCenterService.getActivities' in url and 'ByDate' not in url and 'Entrance' not in url:
                captured['my_activities'] = await response.json()
            elif 'getSevenDaysAvgReplyRateInfo' in url:
                captured['reply_rate'] = await response.json()
            elif 'getActivityEntrance' in url:
                captured['activity_entrance'] = await response.json()
        except:
            pass

    ele_page.on("response", on_response)

    # 0. 先去首页抓"重要待办"和通知
    dashboard_url = f"https://melody.shop.ele.me/app/shop/{shop_id}/dashboard#app.shop.dashboard"
    await ele_page.goto(dashboard_url, wait_until="commit", timeout=15000)
    await asyncio.sleep(3)

    # 从首页iframe抓重要待办
    todos = []
    for f in ele_page.frames:
        try:
            text = await f.evaluate("() => document.body.innerText")
            if '重要待办' in text or '待办' in text:
                # 提取待办内容
                lines = text.split('\n')
                in_todo = False
                for line in lines:
                    line = line.strip()
                    if '重要待办' in line:
                        in_todo = True
                        continue
                    if in_todo and line and len(line) > 2 and line != '暂无待办':
                        if any(kw in line for kw in ['商家成长', '平台消息', '活动中心', '今日营业']):
                            break
                        todos.append(line)
                if '暂无待办' in text:
                    break
                break
        except:
            pass

    # 1. 导航到评价页抓评分+评价
    review_url = f"https://melody.shop.ele.me/app/shop/{shop_id}/comments#app.shop.comments"
    await ele_page.goto(review_url, wait_until="commit", timeout=15000)
    await asyncio.sleep(3)

    # 截图
    await ele_page.screenshot(path=str(SCREENSHOT_DIR / "eleme_reviews.png"))

    # 2. 导航到营销中心
    activity_url = f"https://melody.shop.ele.me/app/shop/{shop_id}/activity__index#app.shop.activity.index"
    await ele_page.goto(activity_url, wait_until="commit", timeout=15000)
    await asyncio.sleep(2)

    # 点"我的活动"触发getActivities API
    await ele_page.evaluate("""() => {
        document.querySelectorAll('span, a, div').forEach(el => {
            if (el.textContent?.trim() === '我的活动' && el.offsetParent) el.click();
        });
    }""")
    await asyncio.sleep(3)

    # 点"进行中"tab
    await ele_page.evaluate("""() => {
        document.querySelectorAll('span, div, a').forEach(el => {
            if (el.textContent?.trim() === '进行中' && el.offsetParent) el.click();
        });
    }""")
    await asyncio.sleep(3)

    await ele_page.screenshot(path=str(SCREENSHOT_DIR / "eleme_activities.png"))

    ele_page.remove_listener("response", on_response)

    # 解析数据
    result = {
        "platform": "饿了么",
        "shop_id": shop_id,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "重要待办": todos,
    }

    # --- 评分 ---
    stats_list = captured.get('stats', {}).get('result', [])
    if stats_list:
        stats = stats_list[0] if isinstance(stats_list, list) else stats_list
        result["评分"] = {
            "综合评分": stats.get('serviceRating', 0),
            "口味": stats.get('qualityRating', 0),
            "包装": stats.get('packageRating', 0),
            "配送": stats.get('riderRating', 0),
            "评价总数": stats.get('ratingCount', 0),
            "差评数": stats.get('negativeRatingCount', 0),
            "回复率": stats.get('replyRatingPercent', 0),
            "差评回复率": stats.get('replyNegativeRatingPercent', 0),
        }
        nf = stats.get('newFactor', {})
        if nf:
            result["评分"]["新版总分"] = nf.get('overallScore', '')
            result["评分"]["口味分"] = nf.get('tasteScore', '')
            result["评分"]["包装分"] = nf.get('packageScore', '')

    # --- 回复率 ---
    reply_info = captured.get('reply_rate', {})
    if reply_info:
        result["消息回复率"] = reply_info.get('avgRate', '')

    # --- 评价列表 ---
    reviews_data = captured.get('reviews', {}).get('result', {}).get('rateInfos', [])
    reviews = []
    bad_reviews = []
    for r in reviews_data:
        order_infos = r.get('orderRateInfos', [])
        if not order_infos:
            continue
        info = order_infos[0]
        star = info.get('qualityRating', 0)
        review = {
            "stars": star,
            "user": r.get('username', ''),
            "comment": info.get('ratingContent', '') or '',
            "time": (info.get('ratingAt', '') or '')[:10],
            "foods": [],
            "reply": info.get('replyContent', '') or '',
            "reply_time": (info.get('replyAt', '') or '')[:19].replace('T', ' '),
            "service_score": info.get('serviceRating', 0),
            "quality_score": info.get('qualityRating', 0),
            "pack_score": info.get('packageRating', 0),
            "appealed": r.get('appealed', False),
        }
        # 菜品
        item_names = r.get('itemNames') or []
        if item_names:
            review["foods"] = item_names
        reviews.append(review)
        if star <= 3:
            bad_reviews.append(review)

    result["评价列表"] = reviews
    result["中差评"] = bad_reviews

    # --- 活动 ---
    # 优先用 getActivities（我的活动），fallback到 getActivitiesByDate
    my_acts = captured.get('my_activities', {}).get('result', {}).get('activities', [])
    if my_acts:
        act_data = my_acts
        source = 'my'
    else:
        act_data = captured.get('activities_by_date', {}).get('result', {}).get('activities', [])
        source = 'date'

    activities = []
    for a in act_data:
        # 状态
        if source == 'my':
            status_info = a.get('status', {})
            status = status_info.get('desc', '进行中')
            rule_text = a.get('rule', {}).get('rule', '') if isinstance(a.get('rule'), dict) else a.get('rule', '')
        else:
            status_type = a.get('statusType', {})
            status = "已结束" if status_type.get('activityEnd') else "进行中" if status_type.get('activityStart') else "未开始"
            rule_text = a.get('rule', '')

        date_str = a.get('date', '')
        days_left = None
        end_date = ""
        dm = re.search(r'至\s*(\d{4}-\d{2}-\d{2})', date_str)
        if dm:
            end_date = dm.group(1)
            try:
                from datetime import date
                end = date.fromisoformat(end_date)
                days_left = (end - datetime.now().date()).days
            except:
                pass

        activities.append({
            "title": a.get('title', ''),
            "rule": rule_text,
            "date": date_str,
            "end_date": end_date,
            "days_left": days_left,
            "status": status,
        })
    result["活动"] = activities

    # 获取店铺名 — 优先从评价API取（最准确）
    store_name = ""
    if reviews_data:
        store_name = reviews_data[0].get('shopName', '')
    result["店铺名"] = store_name

    # 打印摘要
    score_info = result.get("评分", {})
    print(f"[饿了么] {store_name}")
    print(f"  综合 {score_info.get('综合评分', '?')} | 口味 {score_info.get('口味', '?')} | 包装 {score_info.get('包装', '?')}")
    print(f"  评价{score_info.get('评价总数', '?')}条 差评{score_info.get('差评数', '?')}条 回复率{score_info.get('回复率', '?')}%")
    print(f"  活动{len(activities)}个 评价已加载{len(reviews)}条 中差评{len(bad_reviews)}条")

    return result


def format_eleme_report(data):
    """格式化饿了么巡检报告"""
    if not data:
        return ""

    def short_date(d):
        m = re.match(r'\d{4}-(\d{2})-(\d{2})', str(d))
        return f"{int(m.group(1))}月{int(m.group(2))}日" if m else str(d)

    lines = []
    store_name = data.get("店铺名", "未知")
    score = data.get("评分", {})
    reviews = data.get("评价列表", [])
    bad_reviews = data.get("中差评", [])
    activities = data.get("活动", [])

    yesterday = (datetime.now().replace(hour=0, minute=0, second=0) - timedelta(days=1)).strftime('%Y-%m-%d')
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')

    yesterday_good = len([r for r in reviews if r.get('time') == yesterday and r['stars'] >= 4])
    yesterday_mid = len([r for r in reviews if r.get('time') == yesterday and r['stars'] == 3])
    yesterday_bad = len([r for r in reviews if r.get('time') == yesterday and r['stars'] <= 2])
    recent_bad = [r for r in bad_reviews if r.get('time', '') >= three_days_ago]

    lines.append(f"\n{'='*50}")
    lines.append(f"【{store_name}】巡检报告（饿了么）")
    lines.append(f"{'='*50}")

    # 评价
    expiring = [a for a in activities if a.get('days_left') is not None and a['days_left'] <= 7 and a['status'] == '进行中']

    if recent_bad:
        lines.append(f"  📊 评价：⚠️ 近3日中差评{len(recent_bad)}条")
        for r in recent_bad:
            lines.append(f"      [{r['stars']}星] {short_date(r['time'])} — {r['comment'] or '（无文字）'}")
            if r['foods']:
                lines.append(f"        菜品: {', '.join(r['foods'][:3])}")
            if r['reply']:
                lines.append(f"        已回复: {r['reply'][:80]}...")
    elif bad_reviews:
        lines.append(f"  📊 评价：近3日无新增，历史中差评{len(bad_reviews)}条")
        for r in bad_reviews:
            lines.append(f"      [{r['stars']}星] {short_date(r['time'])} — {r['comment'] or '（无文字）'}")
    else:
        lines.append(f"  📊 评价：无中差评")
    lines.append(f"    昨日：好评{yesterday_good} 中评{yesterday_mid} 差评{yesterday_bad}")

    # 活动
    if expiring:
        lines.append(f"  🎯 活动：⚠️ {len(expiring)}个即将到期")
        for a in expiring:
            lines.append(f"      {a['title']}「{a['rule']}」还剩{a['days_left']}天 到期{short_date(a['end_date'])}")
    else:
        lines.append(f"  🎯 活动：无最近7天到期活动")

    if activities:
        for i, a in enumerate(activities, 1):
            status = a.get('status', '')
            days = f"剩{a['days_left']}天" if a.get('days_left') is not None else ""
            date_info = ""
            if a.get('date'):
                dates = re.findall(r'\d{4}-(\d{2})-(\d{2})', a['date'])
                if len(dates) == 2:
                    d1 = f"{int(dates[0][0])}月{int(dates[0][1])}日"
                    d2 = f"{int(dates[1][0])}月{int(dates[1][1])}日"
                    date_info = f"{d1}~{d2}"
            lines.append(f"    [{i}] {a['title']} | {a.get('rule', '')} | {date_info} {days} | {status}")

    # 通知 — 和美团一样的逻辑
    todos = data.get("重要待办", [])
    # 过滤掉无用的（如"查看历史待办"）
    real_todos = [t for t in todos if t and '查看' not in t and len(t) > 3]
    if real_todos:
        lines.append(f"  📬 近3日通知：{len(real_todos)}条")
        for t in real_todos:
            lines.append(f"      {t}")
    else:
        lines.append(f"  📬 近3日通知：无重要通知")

    return "\n".join(lines)
