#!/usr/bin/env python3
"""对比巡店和预警的输出差异 - 宋彬全量，headless模式"""
import asyncio, json, time, sys, os
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from run_fast import run_once, watch_open_all, watch_refresh
from plugin_helper import get_ext, close_store_pages, stop_hider
from browser import launch_headless, check_headless_login, kill_headless, _cdp_ws, PORT
import patrol_log as L

SONGBIN_BRANDS = [
    "乐山家常菜(桐梓林)", "云下（团结湖店）", "华兴煎蛋面（致民路店）",
    "尽膳（双店）", "尽膳口福（三店）", "曹家土菜馆（胜太路店,韩府路店）",
    "森园茶餐厅（大岗兴业街店）", "牛街桥头回香苑（方庄店）",
    "白下元宵铺（迈皋桥）", "芙蓉树下（望京店）",
    "落舌麻辣烫（金石路店）", "重庆碗杂面（益州大道南段店）",
    "食宜鲜炖（南开店）", "食宜鲜炖（双店）", "麦记牛奶（春熙路店）",
]

OUT = Path(__file__).parent / "data"

async def main():
    OUT.mkdir(exist_ok=True)
    L.start()
    pw = await async_playwright().start()

    # 用headless模式
    b, ctx = await launch_headless(pw)
    print(f"headless连接成功，{len(ctx.pages)}个页面")

    # 验证登录态
    ok, msg = await check_headless_login(ctx)
    if not ok:
        print(f"❌ 登录失败: {msg}")
        kill_headless()
        await pw.stop()
        return
    print(f"✅ 登录OK: {msg}")

    # === 1. 预警模式 ===
    print(f"\n{'='*50}")
    print(f"预警模式 - {len(SONGBIN_BRANDS)}个品牌")
    print(f"{'='*50}\n")
    t0 = time.time()
    watch_pages, blocked = await watch_open_all(SONGBIN_BRANDS, ctx)
    all_notices = await watch_refresh(watch_pages)
    alert_time = time.time() - t0

    # 关闭预警页面
    for _, _, pg in watch_pages:
        try: await pg.close()
        except: pass

    alert_result = {
        "mode": "alert",
        "time_seconds": round(alert_time, 1),
        "brands": len(SONGBIN_BRANDS),
        "blocked": [(dn, pn, r) for dn, pn, r in blocked],
        "notices": {}
    }
    for store, items in all_notices.items():
        alert_result["notices"][store] = []
        for item in items:
            alert_result["notices"][store].append({
                "platform": item["platform"],
                "count": len(item["notices"]),
                "titles": [n["title"] for n in item["notices"]]
            })

    (OUT / "compare_alert.json").write_text(json.dumps(alert_result, ensure_ascii=False, indent=2))
    print(f"\n预警完成: {alert_time:.0f}s, {len(all_notices)}家有通知\n")

    await asyncio.sleep(3)

    # === 2. 巡店模式 ===
    print(f"\n{'='*50}")
    print(f"巡店模式 - {len(SONGBIN_BRANDS)}个品牌")
    print(f"{'='*50}\n")
    t0 = time.time()
    all_issues = await run_once(SONGBIN_BRANDS, ctx)
    patrol_time = time.time() - t0

    patrol_result = {
        "mode": "patrol",
        "time_seconds": round(patrol_time, 1),
        "brands": len(SONGBIN_BRANDS),
        "stores": {}
    }
    for store, items in all_issues.items():
        patrol_result["stores"][store] = []
        for item in items:
            entry = {
                "platform": item["platform"],
                "type": item["type"],
                "msg": item["msg"],
            }
            if item.get("details"):
                entry["detail_count"] = len(item["details"])
                if item["type"] == "bad_review":
                    entry["reviews"] = [{"stars": d.get("stars"), "comment": d.get("comment","")[:60]} for d in item["details"] if isinstance(d, dict)]
                elif item["type"] == "notice":
                    entry["notices"] = [d.get("title","") for d in item["details"] if isinstance(d, dict)]
                elif item["type"] == "expiring":
                    entry["activities"] = [{"name": d.get("name",""), "days": d.get("days")} for d in item["details"] if isinstance(d, dict)]
            patrol_result["stores"][store].append(entry)

    (OUT / "compare_patrol.json").write_text(json.dumps(patrol_result, ensure_ascii=False, indent=2))
    print(f"\n巡店完成: {patrol_time:.0f}s, {len(all_issues)}家有问题\n")

    # === 3. 对比 ===
    print(f"\n{'='*50}")
    print(f"对比结果")
    print(f"{'='*50}\n")
    print(f"预警: {alert_time:.0f}s | 巡店: {patrol_time:.0f}s | 速度比: {patrol_time/max(alert_time,1):.1f}x")
    print()

    alert_stores = set(alert_result["notices"].keys())
    patrol_stores = set(patrol_result["stores"].keys())
    patrol_notice_stores = set()
    patrol_extra_types = {}
    for store, items in patrol_result["stores"].items():
        for item in items:
            if item["type"] == "notice":
                patrol_notice_stores.add(store)
            else:
                patrol_extra_types.setdefault(item["type"], []).append(f"{store}({item['platform']}): {item['msg']}")

    print(f"预警发现通知: {len(alert_stores)}家")
    print(f"巡店发现问题: {len(patrol_stores)}家")
    print(f"  其中通知类: {len(patrol_notice_stores)}家")
    print()

    both = alert_stores & patrol_notice_stores
    alert_only = alert_stores - patrol_notice_stores
    patrol_notice_only = patrol_notice_stores - alert_stores

    print(f"通知交集: {len(both)}家")
    for s in sorted(both): print(f"  {s}")
    print(f"仅预警有: {len(alert_only)}家")
    for s in sorted(alert_only): print(f"  {s}")
    print(f"仅巡店有: {len(patrol_notice_only)}家")
    for s in sorted(patrol_notice_only): print(f"  {s}")
    print()

    print(f"巡店独有维度（预警完全不覆盖）:")
    for t, items in patrol_extra_types.items():
        labels = {"bad_review":"差评","expiring":"活动到期","promo":"推广余额","auth":"授权失败","verify":"验证拦截","error":"错误"}
        print(f"  {labels.get(t,t)}: {len(items)}条")
        for i in items:
            print(f"    {i}")
    print()

    summary = {
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M'),
        "alert_time": round(alert_time, 1),
        "patrol_time": round(patrol_time, 1),
        "speed_ratio": round(patrol_time/max(alert_time,1), 1),
        "alert_stores_with_notices": len(alert_stores),
        "patrol_stores_with_issues": len(patrol_stores),
        "patrol_stores_with_notices": len(patrol_notice_stores),
        "notice_intersection": len(both),
        "alert_only_notices": len(alert_only),
        "patrol_only_notices": len(patrol_notice_only),
        "patrol_extra_dimensions": {t: len(v) for t, v in patrol_extra_types.items()},
    }
    (OUT / "compare_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print("结果已存: data/compare_alert.json, data/compare_patrol.json, data/compare_summary.json")

    await close_store_pages(ctx)
    await stop_hider()
    kill_headless()
    await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
