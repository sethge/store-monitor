#!/usr/bin/env python3
"""
多店铺巡检调度器
逐个登录店铺 → 运行巡检 → 输出报告
"""

import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).parent
STORES_FILE = BASE_DIR / "stores.json"


def load_config():
    return json.loads(STORES_FILE.read_text())


def get_ws_url(port=9222):
    result = subprocess.run(
        ["curl", "--noproxy", "localhost", "-s", f"http://localhost:{port}/json/version"],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode != 0:
        raise ConnectionError("Chrome调试端口未响应")
    return json.loads(result.stdout)["webSocketDebuggerUrl"]


async def login_store(page, store):
    """登录指定店铺，返回 (成功, 原因)"""
    print(f"  登录中... 账号: {store['account'][:3]}***")

    # 先检查是否已登录
    await page.goto("https://e.waimai.meituan.com/", wait_until="commit", timeout=15000)
    await asyncio.sleep(3)

    # 检查是否在登录页
    url = page.url
    if 'login' not in url and 'passport' not in url:
        # 可能已登录，检查页面内容
        title = await page.title()
        if '商家' in title or '外卖' in title:
            # 检查当前登录的是不是目标店铺
            for f in page.frames:
                try:
                    text = await f.evaluate("() => document.body.innerText")
                    if store.get('name', '')[:4] in text:
                        print(f"  ✅ 已登录: {store['name']}")
                        return True, "already_logged_in"
                except:
                    pass
            # 登录了但不是目标店铺，需要切换
            print(f"  当前非目标店铺，需要切换...")

    # 需要登录
    if not store.get('account') or not store.get('password'):
        return False, "no_credentials"

    # 导航到登录页
    await page.goto("https://e.waimai.meituan.com/login", wait_until="commit", timeout=15000)
    await asyncio.sleep(3)

    # 检查是否需要验证码（授权掉线）
    page_text = ""
    for f in page.frames:
        try:
            text = await f.evaluate("() => document.body.innerText")
            page_text += text
        except:
            pass

    if '验证码' in page_text and '手机' in page_text:
        await page.screenshot(path=str(BASE_DIR / "data" / "screenshots" / "need_verify.png"))
        return False, "need_sms_verify"

    # 尝试账号密码登录
    try:
        # 找账号输入框
        account_input = await page.query_selector('input[type="text"], input[name="account"], input[placeholder*="账号"], input[placeholder*="手机"]')
        password_input = await page.query_selector('input[type="password"]')

        if not account_input or not password_input:
            # 可能需要先点"密码登录"tab
            for f in page.frames:
                try:
                    await f.evaluate("""() => {
                        document.querySelectorAll('span, div, a').forEach(el => {
                            const t = el.textContent.trim();
                            if (t === '密码登录' || t === '账号密码登录') el.click();
                        });
                    }""")
                except:
                    pass
            await asyncio.sleep(2)
            account_input = await page.query_selector('input[type="text"], input[name="account"]')
            password_input = await page.query_selector('input[type="password"]')

        if account_input and password_input:
            await account_input.fill(store['account'])
            await password_input.fill(store['password'])
            await asyncio.sleep(1)

            # 点登录按钮
            login_btn = await page.query_selector('button[type="submit"], button:has-text("登录")')
            if login_btn:
                await login_btn.click()
            else:
                await page.keyboard.press("Enter")

            await asyncio.sleep(5)

            # 检查登录结果
            new_url = page.url
            if 'login' not in new_url and 'passport' not in new_url:
                print(f"  ✅ 登录成功")
                return True, "login_success"

            # 可能弹出验证码
            page_text2 = ""
            for f in page.frames:
                try:
                    page_text2 += await f.evaluate("() => document.body.innerText")
                except:
                    pass
            if '验证' in page_text2 or '滑块' in page_text2:
                await page.screenshot(path=str(BASE_DIR / "data" / "screenshots" / "need_verify.png"))
                return False, "need_captcha"

            return False, "login_failed"
        else:
            return False, "no_input_found"

    except Exception as e:
        return False, f"login_error: {e}"


async def run_store_check(page, store, config):
    """对单个店铺运行巡检，复用monitor.py的逻辑"""
    # 动态导入monitor模块
    import monitor

    # 设置store专属数据目录
    store_data_dir = BASE_DIR / "data" / store["id"]
    store_data_dir.mkdir(parents=True, exist_ok=True)
    store_screenshot_dir = store_data_dir / "screenshots"
    store_screenshot_dir.mkdir(exist_ok=True)

    # 临时替换monitor的路径
    orig_data_dir = monitor.DATA_DIR
    orig_snapshot = monitor.SNAPSHOT_FILE
    orig_screenshot = monitor.SCREENSHOT_DIR

    monitor.DATA_DIR = store_data_dir
    monitor.SNAPSHOT_FILE = store_data_dir / "last_check.json"
    monitor.SCREENSHOT_DIR = store_screenshot_dir

    try:
        snapshot = monitor.load_snapshot()

        # 1. 消息中心
        messages = await monitor.scrape_messages(page)

        # 2. 评分/评价
        scores = await monitor.scrape_scores(page)

        # 3. 活动
        activities = await monitor.scrape_activities(page)

        # 保存快照
        monitor.save_snapshot({
            "messages": messages,
            "scores": scores,
            "activities": activities,
        })

        return {
            "store": store,
            "messages": messages,
            "scores": scores,
            "activities": activities,
            "snapshot": snapshot,
            "success": True,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"store": store, "success": False, "error": str(e)}
    finally:
        # 恢复原路径
        monitor.DATA_DIR = orig_data_dir
        monitor.SNAPSHOT_FILE = orig_snapshot
        monitor.SCREENSHOT_DIR = orig_screenshot


def print_report(result, config):
    """输出单店铺巡检报告（复用monitor的输出逻辑）"""
    if not result["success"]:
        print(f"\n❌ {result['store']['name']} 巡检失败: {result.get('error', '未知')}")
        return

    import monitor
    store = result["store"]
    scores = result["scores"]
    messages = result["messages"]
    activities = result["activities"]

    # 复用 run_check 里的输出格式
    store_name = store["name"]

    settings = config.get("settings", {})
    from datetime import timedelta
    today_str = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now().replace(hour=0, minute=0, second=0) - timedelta(days=1)).strftime('%Y-%m-%d')
    three_days_ago = (datetime.now() - timedelta(days=settings.get("notify_days", 3))).strftime('%Y-%m-%d')
    cutoff_ts = datetime.now().timestamp() - settings.get("notify_days", 3) * 86400

    def short_date(d):
        m = re.match(r'\d{4}-(\d{2})-(\d{2})', str(d))
        return f"{int(m.group(1))}月{int(m.group(2))}日" if m else str(d)

    def short_dt(d):
        m = re.match(r'\d{4}[.-](\d{2})[.-](\d{2})\s+(\d{2}):\d{2}', str(d))
        return f"{int(m.group(1))}月{int(m.group(2))}日{int(m.group(3))}点" if m else short_date(d)

    def short_time(t):
        m = re.match(r'\d{4}-(\d{2})-(\d{2})', str(t))
        return f"{int(m.group(1))}月{int(m.group(2))}日" if m else str(t)

    reviews = scores.get("评价列表", [])
    bad_reviews = scores.get("中差评", [])
    yesterday_good = len([r for r in reviews if r.get('time') == yesterday and r['stars'] >= 4])
    yesterday_mid = len([r for r in reviews if r.get('time') == yesterday and r['stars'] == 3])
    yesterday_bad = len([r for r in reviews if r.get('time') == yesterday and r['stars'] <= 2])
    recent_bad = [r for r in bad_reviews if r.get('time', '') >= three_days_ago]

    print(f"\n{'='*50}")
    print(f"【{store_name}】巡检报告")
    print(f"{'='*50}")

    print(f"\n📊 评价")
    if recent_bad:
        print(f"  ⚠️ 近3日中差评（{len(recent_bad)}条）:")
        for r in recent_bad:
            print(f"    [{r['stars']}星] {short_date(r['time'])} — {r['comment']}")
            if r['foods']:
                print(f"      菜品: {', '.join(r['foods'][:3])}")
            if r.get('appeal_status'):
                print(f"      申诉: {r['appeal_status']}")
            if r['reply']:
                print(f"      已回复: {r['reply'][:80]}...")
    elif bad_reviews:
        print(f"  近3日无新增中差评，历史中差评{len(bad_reviews)}条:")
        for r in bad_reviews:
            print(f"    [{r['stars']}星] {short_date(r['time'])} — {r['comment']}")
            if r['foods']:
                print(f"      菜品: {', '.join(r['foods'][:3])}")
            if r.get('appeal_status'):
                print(f"      申诉: {r['appeal_status']}")
    else:
        print(f"  ✅ 无中差评")
    print(f"  昨日评价：好评 {yesterday_good} 条，中评 {yesterday_mid} 条，差评 {yesterday_bad} 条")

    print(f"\n🎯 活动")
    expiring = [a for a in activities.get("items", [])
                if a.get("days_left") is not None and a["days_left"] <= 7 and not a.get("auto_extend")]
    if expiring:
        for a in expiring:
            print(f"  ⚠️ {a['type']}「{a['preview']}」还剩{a['days_left']}天 到期{short_date(a['end_date'])}")
    else:
        print(f"  ✅ 无即将到期活动")
    print()
    for act in activities.get("items", []):
        status = ""
        if act.get("days_left") is not None:
            if act.get("auto_extend"):
                status = f"自动延期 到期{short_date(act['end_date'])}"
            elif act["days_left"] <= 7:
                status = f"⚠️ 剩{act['days_left']}天 到期{short_date(act['end_date'])}"
            else:
                status = f"到期{short_date(act['end_date'])}"
        op = ""
        if act.get("op_logs"):
            latest = act["op_logs"][-1]
            op = f"{latest['操作类型']}{short_dt(latest['操作时间'])}"
        print(f"  [{act['index']}] {act.get('type','')} | {act.get('preview','')} | 7日销量:{act.get('sales_7d','-')} | {status} {('| '+op) if op else ''}")

    print(f"\n📬 近3日通知")
    alert_keywords = ['到期', '失败', '超时', '变更']
    important_msgs = []
    for m in messages:
        if m.get("ctime", 0) < cutoff_ts:
            continue
        title = m.get('title', '')
        category = m.get('category', '')
        if category == '店铺动态':
            if re.search(r'【.+】', title):
                continue
            ad_keywords = ['招商', '上线', '升级', '覆盖全国', '邀请您', '即将上线']
            if any(kw in title for kw in ad_keywords):
                continue
            important_msgs.append(m)
        elif any(kw in title for kw in alert_keywords):
            important_msgs.append(m)

    if important_msgs:
        for m in important_msgs:
            print(f"  [{m.get('category', '')}] {m['title']} — {short_time(m['time'])}")
            detail = m.get('content', m.get('summary', ''))
            if detail:
                clean = re.sub(r'<[^>]+>', '', detail).strip()
                if clean and not clean.startswith('http'):
                    print(f"    {clean[:150]}")
    else:
        print("  ✅ 无重要通知")


async def main():
    config = load_config()
    settings = config.get("settings", {})
    port = settings.get("chrome_port", 9222)

    enabled_stores = [s for s in config["stores"] if s.get("enabled")]
    if not enabled_stores:
        print("没有启用的店铺")
        return

    print(f"\n{'#'*50}")
    print(f"盯店巡检 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"共 {len(enabled_stores)} 家店铺")
    print(f"{'#'*50}")

    try:
        ws_url = get_ws_url(port)
    except Exception as e:
        print(f"❌ Chrome未连接: {e}")
        return

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(ws_url)
        context = browser.contexts[0]
        page = context.pages[0]

        results = []
        for i, store in enumerate(enabled_stores):
            print(f"\n{'─'*40}")
            print(f"[{i+1}/{len(enabled_stores)}] {store['name']}")
            print(f"{'─'*40}")

            # 登录
            if len(enabled_stores) > 1 or store.get('account'):
                success, reason = await login_store(page, store)
                if not success:
                    print(f"  ❌ 登录失败: {reason}")
                    if reason == "need_sms_verify":
                        print(f"  📱 需要老板手机验证码，请手动处理后重试")
                        # TODO: 推送通知给老板
                    results.append({"store": store, "success": False, "error": reason})
                    continue

            # 巡检
            result = await run_store_check(page, store, config)
            results.append(result)

            # 输出报告
            print_report(result, config)

        # 汇总
        print(f"\n{'#'*50}")
        print(f"巡检完成 - {len([r for r in results if r['success']])} 成功 / {len([r for r in results if not r['success']])} 失败")
        for r in results:
            status = "✅" if r["success"] else "❌"
            print(f"  {status} {r['store']['name']} {r.get('error', '')}")
        print(f"{'#'*50}")

    except Exception as e:
        print(f"❌ 巡检出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
