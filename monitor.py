#!/usr/bin/env python3
"""
盯店监控 - 美团商家后台自动巡检
监控三个维度：评分/评价、消息通知、活动状态
通过 page.goto() 导航各页面，避免 click_nav 的 iframe 不刷新问题
"""

import asyncio
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# 项目根目录
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

SNAPSHOT_FILE = DATA_DIR / "last_check.json"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

# 美团后台各页面URL（hash路由）
URLS = {
    "home": "https://e.waimai.meituan.com/",
    "messages": "https://e.waimai.meituan.com/new_fe/business_gw#/msgbox",
    "reviews": "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/frontweb/ffw/userComment_gw",
    "activities": "https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/igate/wmactpc/my",
}


def get_ws_url():
    """获取Chrome WebSocket调试URL"""
    result = subprocess.run(
        ["curl", "--noproxy", "localhost", "-s", "http://localhost:9222/json/version"],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode != 0:
        raise ConnectionError("Chrome调试端口未响应，请用 --remote-debugging-port=9222 启动Chrome")
    return json.loads(result.stdout)["webSocketDebuggerUrl"]


def load_snapshot():
    if SNAPSHOT_FILE.exists():
        return json.loads(SNAPSHOT_FILE.read_text())
    return {"messages": [], "scores": {}, "activities": {}}


def save_snapshot(data):
    data["check_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    SNAPSHOT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


async def wait_for_frame(page, url_keyword, timeout=10):
    """等待包含指定关键词的frame加载完成"""
    for _ in range(timeout * 2):
        for f in page.frames:
            if url_keyword in f.url:
                text = await f.evaluate("() => document.body.innerText || ''")
                if len(text.strip()) > 50:
                    return f
        await asyncio.sleep(0.5)
    return None


async def scrape_messages(page):
    """抓取消息中心 - 通过API拦截获取完整消息数据"""
    print("[消息中心] 导航中...")

    msg_data = None

    async def on_response(response):
        nonlocal msg_data
        if 'message/category/list' in response.url:
            try:
                msg_data = await response.json()
            except:
                pass

    page.on("response", on_response)
    await page.goto(URLS["messages"], wait_until="commit", timeout=15000)
    await asyncio.sleep(2)
    if not msg_data:
        await page.reload(wait_until="commit", timeout=15000)
        await asyncio.sleep(2)
    page.remove_listener("response", on_response)

    # 截图
    await page.screenshot(path=str(SCREENSHOT_DIR / "messages.png"), full_page=False)

    messages = []
    if msg_data and msg_data.get('data', {}).get('wmENoticeResults'):
        for item in msg_data['data']['wmENoticeResults']:
            # 去掉HTML标签提取纯文本内容
            content = item.get('content', '')
            if content.startswith('<'):
                content = re.sub(r'<[^>]+>', '', content).strip()

            messages.append({
                "title": item.get('title', ''),
                "time": datetime.fromtimestamp(item['ctime']).strftime('%Y-%m-%d %H:%M:%S'),
                "ctime": item.get('ctime', 0),
                "summary": item.get('preView', ''),
                "content": content,
                "category": item.get('categoryName', ''),
                "read": item.get('read', 0),
            })
        print(f"[消息中心] API抓到 {len(messages)} 条消息")
    else:
        # fallback: DOM抓取
        print("[消息中心] API未捕获，降级DOM抓取")
        for f in page.frames:
            try:
                text = await f.evaluate("() => document.body.innerText")
                if not text or len(text.strip()) < 50:
                    continue
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                skip_titles = {'全部', '重要消息', '平台通知', '店铺动态', '活动推广',
                              '商家成长', '其他消息', '平台公告', '系统信息', '营销信息',
                              '只看未读'}
                i = 0
                while i < len(lines) - 1:
                    if i + 1 < len(lines) and ('2026-' in lines[i + 1] or '2025-' in lines[i + 1]):
                        title = lines[i]
                        timestamp = lines[i + 1]
                        summary = ""
                        if i + 2 < len(lines) and '2026-' not in lines[i + 2] and '2025-' not in lines[i + 2]:
                            summary = lines[i + 2]
                        if len(title) > 2 and title not in skip_titles:
                            messages.append({"title": title, "time": timestamp, "summary": summary,
                                           "content": "", "category": "", "read": 0, "ctime": 0})
                        i += 3
                    else:
                        i += 1
            except:
                continue
        # 去重
        seen = set()
        messages = [m for m in messages if not (m["title"] + m["time"] in seen or seen.add(m["title"] + m["time"]))]
        print(f"[消息中心] DOM抓到 {len(messages)} 条消息")

    return messages


async def scrape_scores(page):
    """抓取评分页面 - 通过拦截API获取精确数据 + 截图"""
    print("[评分页面] 导航中...")

    captured = {}

    async def on_response(response):
        url = response.url
        try:
            if 'comment/poi/scores' in url and 'detail' not in url:
                captured['poi_scores'] = await response.json()
            elif 'scores/detail' in url:
                captured['detail'] = await response.json()
            elif '/comment/scores' in url and 'detail' not in url and 'update' not in url:
                captured['scores'] = await response.json()
            elif 'comment/list?' in url:
                data = await response.json()
                if data.get('success'):
                    captured.setdefault('reviews_all', []).extend(data['data'].get('list', []))
                    captured['reviews_total'] = data['data'].get('total', 0)
        except:
            pass

    page.on("response", on_response)

    # 先去首页清状态，再进评分页确保API触发
    await page.goto("https://e.waimai.meituan.com/", wait_until="commit", timeout=15000)
    await asyncio.sleep(2)
    await page.goto(URLS["reviews"], wait_until="commit", timeout=15000)
    await asyncio.sleep(5)
    if not captured.get('detail'):
        await page.reload(wait_until="commit", timeout=15000)
        await asyncio.sleep(5)

    # 截图评分页
    screenshot_path = str(SCREENSHOT_DIR / "scores.png")
    await page.screenshot(path=screenshot_path, full_page=False)

    # 点击"外卖评价列表"tab获取评价内容
    for f in page.frames:
        try:
            has_glass = await f.evaluate("() => !!document.querySelector('flt-glass-pane')")
            if has_glass:
                await f.evaluate("""() => {
                    const glass = document.querySelector('flt-glass-pane');
                    const spans = glass.shadowRoot.querySelectorAll('flt-span, span');
                    for (const s of spans) {
                        if (s.textContent?.trim() === '外卖评价列表') {
                            const rect = s.getBoundingClientRect();
                            glass.dispatchEvent(new PointerEvent('pointerdown', {
                                clientX: rect.x + rect.width/2, clientY: rect.y + rect.height/2,
                                bubbles: true, pointerId: 1, pointerType: 'mouse'
                            }));
                            glass.dispatchEvent(new PointerEvent('pointerup', {
                                clientX: rect.x + rect.width/2, clientY: rect.y + rect.height/2,
                                bubbles: true, pointerId: 1, pointerType: 'mouse'
                            }));
                            return;
                        }
                    }
                }""")
                break
        except:
            pass
    await asyncio.sleep(2)

    # 继续点差评/中评筛选获取中差评
    glass_frame = None
    for f in page.frames:
        try:
            has = await f.evaluate("() => !!document.querySelector('flt-glass-pane')")
            if has:
                glass_frame = f
                break
        except:
            pass

    for filter_name in ['差评(含1-2星打分项)', '中评(含3星打分项)']:
        if glass_frame:
            try:
                await glass_frame.evaluate(f"""() => {{
                    const glass = document.querySelector('flt-glass-pane');
                    const spans = glass.shadowRoot.querySelectorAll('flt-span, span');
                    for (const s of spans) {{
                        if (s.textContent?.trim() === '{filter_name}') {{
                            const rect = s.getBoundingClientRect();
                            glass.dispatchEvent(new PointerEvent('pointerdown', {{
                                clientX: rect.x+rect.width/2, clientY: rect.y+rect.height/2,
                                bubbles:true, pointerId:1, pointerType:'mouse'
                            }}));
                            glass.dispatchEvent(new PointerEvent('pointerup', {{
                                clientX: rect.x+rect.width/2, clientY: rect.y+rect.height/2,
                                bubbles:true, pointerId:1, pointerType:'mouse'
                            }}));
                            return;
                        }}
                    }}
                }}""")
                await asyncio.sleep(2)
            except:
                pass

    page.remove_listener("response", on_response)

    # 解析API数据
    result = {"screenshot": screenshot_path, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # 三个大分
    poi = captured.get('poi_scores', {}).get('data', {})
    if poi:
        result["综合体验分"] = poi.get("poiScoreNew")
        result["商品质量分"] = poi.get("qualityScore")
        result["服务体验分"] = poi.get("serviceScore")
        result["综合_领先同行"] = f"{round(poi.get('resultScorePercent', 0) * 100)}%"
        result["商品_领先同行"] = f"{round(poi.get('qualityScorePercent', 0) * 100)}%"
        result["服务_领先同行"] = f"{round(poi.get('serviceScorePercent', 0) * 100)}%"

    # 评价评分（近30天）
    scores_data = captured.get('scores', {}).get('data', {})
    if scores_data:
        result["评价分"] = scores_data.get("poiScore")
        result["口味评分"] = scores_data.get("foodScore")
        result["包装评分"] = scores_data.get("packageScore")
        result["好评率"] = scores_data.get("prisePercent")

        # 解析各星级评价数量
        merchant_score = scores_data.get("merchantScore", "")
        star_counts = {}
        for star in range(1, 6):
            m = re.search(rf'{star}星评价：商家(\d+)条/口味(\d+)条/包装(\d+)条', merchant_score)
            if m:
                star_counts[f"{star}星"] = {"商家": int(m.group(1)), "口味": int(m.group(2)), "包装": int(m.group(3))}
        result["星级分布"] = star_counts

        # 中差评数量（1-3星）
        bad_count = sum(star_counts.get(f"{s}星", {}).get("口味", 0) for s in [1, 2, 3])
        total_count = sum(star_counts.get(f"{s}星", {}).get("口味", 0) for s in range(1, 6))
        result["近30天评价总数"] = total_count
        result["近30天中差评数"] = bad_count

    # 6项明细
    detail = captured.get('detail', {}).get('data', [])
    details = []
    for group in detail:
        for item in group.get('list', []):
            details.append({
                "指标": item["indexName"],
                "数据表现": item["value"],
                "得分": item["score"],
                "权重": f"{round(item['weight'] * 100)}%",
                "提升建议": item.get("proposal", ""),
            })
    result["明细"] = details

    # 评价列表 - 合并所有API响应（含全部+差评筛选+中评筛选）
    reviews = []
    seen_ids = set()
    for r in captured.get('reviews_all', []):
        rid = r.get('id', 0)
        if rid in seen_ids:
            continue
        seen_ids.add(rid)
        review = {
            "stars": r.get('orderCommentScore', 0),
            "user": r.get('userName', ''),
            "comment": r.get('cleanComment', r.get('comment', '')),
            "time": r.get('createTime', r.get('commentTime', '')),
            "foods": [f.get('foodName', '') for f in r.get('orderDetails', r.get('foodList', []))],
            "reply": "",
            "food_score": r.get('tasteScore', r.get('foodCommentScore', 0)),
            "pack_score": r.get('packagingScore', r.get('packCommentScore', 0)),
            "delivery_score": r.get('deliveryCommentScore', 0),
            "appeal_status": (r.get('wmCommentReportInfo') or {}).get('reportReviewStatusDesc', ''),
        }
        replies = r.get('eCommentList', [])
        if replies:
            review["reply"] = replies[0].get('cleanComment', '')
            reply_ctime = replies[0].get('ctime', 0)
            if reply_ctime:
                review["reply_time"] = datetime.fromtimestamp(reply_ctime).strftime('%Y-%m-%d %H:%M:%S')
        reviews.append(review)

    result["评价列表"] = reviews
    result["评价总数"] = captured.get('reviews_total', 0)
    bad_reviews = [r for r in reviews if r['stars'] <= 3]
    result["中差评"] = bad_reviews
    print(f"[评价列表] 总{result['评价总数']}条，已加载{len(reviews)}条，中差评{len(bad_reviews)}条")

    if poi:
        print(f"[评分页面] 综合 {result.get('综合体验分')} | 商品 {result.get('商品质量分')} | 服务 {result.get('服务体验分')}")
    else:
        print("[评分页面] API未捕获到，仅保存截图")

    return result


async def _wait_act_list(page, timeout=15):
    """等活动列表iframe加载完成"""
    for _ in range(timeout):
        await asyncio.sleep(1)
        for f in page.frames:
            if 'wmact' in f.url and 'my.html' in f.url:
                try:
                    text = await f.evaluate("() => document.body.innerText")
                    if '操作' in text and len(text) > 200:
                        return f
                except:
                    pass
    return None


async def _nav_to_activity_list(page):
    """通过左侧菜单导航到'我的活动'"""
    main_frame = page.frames[0]
    await main_frame.evaluate("""() => {
        document.querySelector('#活动中心 > li > div')?.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    }""")
    await asyncio.sleep(1)
    await main_frame.evaluate("""() => {
        document.querySelector('#我的活动 li')?.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    }""")
    return await _wait_act_list(page)


async def scrape_activities(page):
    """抓取活动页面 - 列表预览/销量 + 逐个点详情获取到期日期"""
    print("[活动中心] 导航中...")

    act_frame = await _nav_to_activity_list(page)
    if not act_frame:
        # 重试：goto活动页面再导航
        print("[活动中心] 首次加载失败，重试...")
        await page.goto(URLS["activities"], wait_until="commit", timeout=15000)
        await asyncio.sleep(2)
        act_frame = await _nav_to_activity_list(page)
    if not act_frame:
        print("[活动中心] 列表加载失败")
        return {"items": [], "expiring": [], "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # 关闭弹窗
    for f in page.frames:
        try:
            await f.evaluate("""() => {
                document.querySelectorAll('button, span, a').forEach(btn => {
                    const t = btn.textContent.trim();
                    if (['×','X','关闭','我知道了','点击查看'].includes(t)) btn.click();
                });
            }""")
        except:
            pass
    await asyncio.sleep(1)

    # 从列表表格提取预览和销量
    list_rows = await act_frame.evaluate("""() => {
        const rows = [];
        const trs = document.querySelectorAll('tr');
        for (const tr of trs) {
            const tds = tr.querySelectorAll('td');
            if (tds.length >= 4) {
                rows.push({
                    type: tds[1]?.innerText?.trim() || '',
                    preview: tds[2]?.innerText?.trim() || '',
                    sales_7d: tds[3]?.innerText?.trim() || '',
                });
            }
        }
        return rows;
    }""")

    # 统计详情按钮数（排除"管理"类的折扣商品行）
    detail_count = await act_frame.evaluate("""() => {
        let c = 0;
        document.querySelectorAll('span').forEach(s => { if (s.textContent.trim() === '详情') c++; });
        return c;
    }""")

    activities = {"items": [], "expiring": [], "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    today = datetime.now().date()

    for idx in range(detail_count):
        # 列表行数据
        row = list_rows[idx] if idx < len(list_rows) else {}

        # 点第idx个详情
        await act_frame.evaluate(f"""() => {{
            let c = 0;
            document.querySelectorAll('span').forEach(s => {{
                if (s.textContent.trim() === '详情') {{
                    if (c === {idx}) s.click();
                    c++;
                }}
            }});
        }}""")

        # 等detailAct frame加载完成（包含日期信息）
        detail_text = ""
        detail_frame = None
        for _ in range(10):
            await asyncio.sleep(1)
            for f in page.frames:
                if 'detailAct' not in f.url:
                    continue
                try:
                    t = await f.evaluate("() => document.body.innerText")
                    if t and len(t) > 100 and re.search(r'\d{4}[/-]\d{2}[/-]\d{2}', t):
                        detail_text = t
                        detail_frame = f
                        break
                except:
                    pass
            if detail_text:
                break

        act = {
            "index": idx + 1,
            "type": row.get("type", ""),
            "preview": row.get("preview", ""),
            "sales_7d": row.get("sales_7d", ""),
            "detail": "",
            "start_date": "", "end_date": "",
            "auto_extend": False, "days_left": None, "needs_alert": False,
            "op_logs": [],
        }

        text = detail_text
        if not text:
            print(f"  [{idx+1}] 详情页加载超时，跳过")
        else:
            # 活动类型（详情页补充，列表已有则不覆盖）
            if not act["type"]:
                m = re.search(r'(满减活动|门店新客立减|减配送费|优惠券|折扣商品)', text)
                if m:
                    act["type"] = m.group(1)

            # 日期
            dm = re.search(r'(\d{4}[/-]\d{2}[/-]\d{2})\s*至\s*(\d{4}[/-]\d{2}[/-]\d{2})', text)
            if dm:
                act["start_date"] = dm.group(1).replace('/', '-')
                act["end_date"] = dm.group(2).replace('/', '-')

                from datetime import date
                end = date.fromisoformat(act["end_date"])
                act["days_left"] = (end - today).days
                act["auto_extend"] = '到期自动延期' in text
                if act["days_left"] <= 7 and not act["auto_extend"]:
                    act["needs_alert"] = True

            # 活动详情（从详情页补充）
            dm2 = re.search(r'(\d+减\d+(?:.*?\d+减\d+)*|新客立减\d+元|配送费立减[\d.]+元)', text)
            if dm2:
                act["detail"] = dm2.group(0).strip()

            # 点"操作记录"tab抓操作日志
            if detail_frame:
                try:
                    await detail_frame.evaluate("""() => {
                        // 只点击叶子节点的"操作记录"（tab按钮），避免点到外层容器
                        document.querySelectorAll('a, span, div').forEach(el => {
                            if (el.textContent.trim() === '操作记录' && el.children.length === 0) {
                                el.click();
                            }
                        });
                    }""")
                    await asyncio.sleep(2)
                    op_text = await detail_frame.evaluate("() => document.body.innerText")
                    # 解析操作记录表格
                    start = op_text.find('操作类型\t操作时间')
                    if start < 0:
                        start = op_text.find('操作类型')
                    if start >= 0:
                        end_mark = op_text.find('修改活动', start)
                        if end_mark < 0:
                            end_mark = op_text.find('删除活动', start)
                        if end_mark < 0:
                            end_mark = len(op_text)
                        records_text = op_text[start:end_mark].strip()
                        lines = records_text.split('\n')
                        for line in lines[1:]:  # 跳过表头
                            parts = line.split('\t')
                            if len(parts) >= 2 and re.search(r'\d{4}', parts[1]):
                                act["op_logs"].append({
                                    "操作类型": parts[0].strip(),
                                    "操作时间": parts[1].strip(),
                                })
                except Exception as e:
                    print(f"    操作记录抓取失败: {e}")

        status = ""
        if act["days_left"] is not None:
            if act["needs_alert"]:
                status = f"⚠️ {act['days_left']}天后到期!"
            elif act["auto_extend"]:
                status = f"✅ {act['days_left']}天后到期(自动延期)"
            else:
                status = f"✅ {act['days_left']}天后到期"

        op_info = ""
        if act["op_logs"]:
            latest = act["op_logs"][-1]
            op_info = f" | 最近操作:{latest['操作类型']} {latest['操作时间']}"
        print(f"  [{idx+1}] {act['type']}: {act['preview']} | 7日销量:{act['sales_7d']} | {act['end_date']} {status}{op_info}")

        activities["items"].append(act)
        if act["needs_alert"]:
            activities["expiring"].append(act)

        # 回到列表 - 先试左侧菜单，失败则goto重新加载
        main_frame = page.frames[0]
        await main_frame.evaluate("""() => {
            document.querySelector('#我的活动 li')?.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        }""")
        act_frame = await _wait_act_list(page, timeout=8)
        if not act_frame:
            await page.goto(URLS["activities"], wait_until="commit", timeout=15000)
            await asyncio.sleep(2)
            act_frame = await _nav_to_activity_list(page)
        if not act_frame:
            print("  列表加载失败，停止")
            break

    # 补充折扣商品等没有"详情"按钮的行
    for i in range(detail_count, len(list_rows)):
        row = list_rows[i]
        activities["items"].append({
            "index": i + 1,
            "type": row.get("type", ""),
            "preview": row.get("preview", ""),
            "sales_7d": row.get("sales_7d", ""),
            "detail": "", "start_date": "", "end_date": "",
            "auto_extend": False, "days_left": None, "needs_alert": False,
        })
        print(f"  [{i+1}] {row.get('type','')}: {row.get('preview','')} | 7日销量:{row.get('sales_7d','')}")

    screenshot_path = str(SCREENSHOT_DIR / "activities.png")
    await page.screenshot(path=screenshot_path, full_page=False)
    activities["screenshot"] = screenshot_path

    print(f"[活动中心] 共 {len(activities['items'])} 个活动，{len(activities['expiring'])} 个需要提醒")
    return activities


def diff_messages(old_msgs, new_msgs):
    old_keys = {m["title"] + m["time"] for m in old_msgs}
    return [m for m in new_msgs if m["title"] + m["time"] not in old_keys]


def format_alert(store_name, alert_type, items):
    if alert_type == "new_messages":
        lines = [f"【盯店·新通知】{store_name}", "━━━━━━━━━━━━"]
        for item in items:
            lines.append(f"📌 {item['title']}")
            lines.append(f"   时间：{item['time']}")
            if item.get('summary'):
                lines.append(f"   摘要：{item['summary']}")
            lines.append("")
        lines.append("━━━━━━━━━━━━")
        lines.append("请及时处理")
        return "\n".join(lines)

    if alert_type == "expiring_activities":
        lines = [f"【盯店·活动到期预警】{store_name}", "━━━━━━━━━━━━"]
        for act in items:
            days = act.get('days_left', '?')
            lines.append(f"⚠️ {act['type']} — 还剩{days}天到期")
            lines.append(f"   到期日：{act.get('end_date', '?')}")
            if act.get('detail'):
                lines.append(f"   内容：{act['detail']}")
            lines.append(f"   👉 请尽快延期")
            lines.append("")
        lines.append("━━━━━━━━━━━━")
        lines.append(f"共 {len(items)} 个活动需要延期")
        return "\n".join(lines)

    return ""


async def get_store_name(page):
    """从页面获取店铺名"""
    for f in page.frames:
        try:
            name = await f.evaluate("""() => {
                const els = document.querySelectorAll('span, div');
                for (const el of els) {
                    const t = el.textContent.trim();
                    if (t.includes('（') && t.includes('）') && t.length < 30 && t.length > 4) return t;
                }
                return '';
            }""")
            if name:
                return name
        except:
            continue
    return "未知店铺"


async def run_check():
    """执行一次完整巡检"""
    print(f"\n{'='*50}")
    print(f"开始巡检 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    from browser import launch as launch_browser
    pw = await async_playwright().start()
    try:
        browser, context = await launch_browser(pw)
        page = context.pages[0]

        print(f"✅ 已连接浏览器 - {await page.title()}")

        # 检测是否有饿了么页面，有则一并巡检
        has_eleme = any('ele.me' in p.url for p in context.pages)
        eleme_data = None
        if has_eleme:
            from monitor_eleme import scrape_eleme, format_eleme_report
            eleme_data = await scrape_eleme(page)

        snapshot = load_snapshot()

        # 1. 消息中心（美团）
        # 检测当前是否有美团页面
        has_meituan = any('waimai.meituan.com' in p.url for p in context.pages)
        if not has_meituan:
            # 只有饿了么，跳过美团巡检
            new_messages = []
            scores = {}
            activities = {"items": [], "expiring": []}
        else:
            new_messages = await scrape_messages(page)

            # 2. 评分/评价（截图）
            scores = await scrape_scores(page)

            # 3. 活动
            activities = await scrape_activities(page)

        # 获取店铺名（去掉"营业中xxx"后缀）
        store_name = await get_store_name(page)
        store_name = re.sub(r'[（(].+?[）)].*$', lambda m: m.group(0).split('）')[0] + '）' if '）' in m.group(0) else m.group(0).split(')')[0] + ')', store_name)
        store_name = re.sub(r'(营业中|休息中|歇业中).*$', '', store_name).strip()

        alerts = []

        # ==================== 输出汇总 ====================
        print(f"\n{'='*50}")
        print(f"【{store_name}】巡检报告")
        print(f"{'='*50}")

        today_str = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now().replace(hour=0, minute=0, second=0) - __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d')
        three_days_ago = (datetime.now() - __import__('datetime').timedelta(days=3)).strftime('%Y-%m-%d')
        cutoff_ts = datetime.now().timestamp() - 3 * 86400

        def short_date(d):
            """2026-03-16 → 3月16日"""
            if not d:
                return ""
            m = re.match(r'\d{4}-(\d{2})-(\d{2})', str(d))
            return f"{int(m.group(1))}月{int(m.group(2))}日" if m else str(d)

        def short_dt(d):
            """2026.03.16 11:28:18 → 3月16日11点"""
            m = re.match(r'\d{4}[.-](\d{2})[.-](\d{2})\s+(\d{2}):\d{2}', str(d))
            return f"{int(m.group(1))}月{int(m.group(2))}日{int(m.group(3))}点" if m else short_date(d)

        def short_time(t):
            """2026-03-19 01:57:55 → 3月19日"""
            m = re.match(r'\d{4}-(\d{2})-(\d{2})', str(t))
            return f"{int(m.group(1))}月{int(m.group(2))}日" if m else str(t)

        # --- 1. 评价 ---
        reviews = scores.get("评价列表", [])
        bad_reviews = scores.get("中差评", [])
        yesterday_good = len([r for r in reviews if r.get('time') == yesterday and r['stars'] >= 4])
        yesterday_mid = len([r for r in reviews if r.get('time') == yesterday and r['stars'] == 3])
        yesterday_bad = len([r for r in reviews if r.get('time') == yesterday and r['stars'] <= 2])
        recent_bad = [r for r in bad_reviews if r.get('time', '') >= three_days_ago]

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

        # --- 2. 活动 ---
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

        # --- 3. 近3日通知 ---
        print(f"\n📬 近3日通知")
        alert_keywords = ['到期', '失败', '超时', '变更']
        important_msgs = []
        for m in new_messages:
            if m.get("ctime", 0) < cutoff_ts:
                continue
            title = m.get('title', '')
            category = m.get('category', '')
            if category == '店铺动态':
                # 过滤平台广告类通知：标题带【】、招商、上线、升级、覆盖全国等
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
                print(f"  [{m.get('category','')}] {m['title']} — {short_time(m['time'])}")
                detail = m.get('content', m.get('summary', ''))
                if detail:
                    clean = re.sub(r'<[^>]+>', '', detail).strip()
                    if clean and not clean.startswith('http'):
                        print(f"    {clean[:150]}")
        else:
            print("  ✅ 无重要通知")

        # 新消息对比
        new_items = diff_messages(snapshot.get("messages", []), new_messages)
        if new_items:
            alerts.append(format_alert(store_name, "new_messages", new_items))

        if activities.get("expiring"):
            alert = format_alert(store_name, "expiring_activities", activities["expiring"])
            alerts.append(alert)

        # TODO: 推送告警到飞书
        # if alerts:
        #     for alert in alerts:
        #         push_to_feishu(alert)

        save_snapshot({
            "messages": new_messages,
            "scores": scores,
            "activities": activities,
            "eleme": eleme_data,
        })

        # 饿了么报告
        if eleme_data:
            print(format_eleme_report(eleme_data))

        print(f"\n巡检完成 - 截图保存在 {SCREENSHOT_DIR}")

    except Exception as e:
        print(f"❌ 巡检出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(run_check())
