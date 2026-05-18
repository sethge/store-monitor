"""
collect_tracking.py — 自动采集到期跟踪任务的数据
从美团/饿了么后台抓取商品销量等指标，填充tracking的metrics_after

用法:
  python3 collect_tracking.py          # 处理所有到期任务
  python3 collect_tracking.py --dry    # 只看有哪些到期，不采集

数据源:
  - 饿了么: food_cache (被动缓存，从extension自动同步)
  - 美团: /gw/bizproduct/v3/food/r/getSpuListCommon API (CDP抓取)

参考SKILL: V-3 验证方式, SF-6 必须用相对数, SF-8 美团数据路径
"""
import json, sys, sqlite3, requests
from datetime import datetime

SERVER = "http://127.0.0.1:5500"
DB_PATH = "ops_logs.db"
CDP_PORT = 9444


def get_due_tasks():
    """Fetch due tracking tasks from server."""
    r = requests.get(f"{SERVER}/api/tracking/due")
    return r.json()


def collect_eleme_metrics(shop_id, item_ids=None):
    """Collect metrics from food_cache (饿了么 passive cache from extension)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    metrics = {}

    if item_ids:
        for iid in item_ids.split(","):
            iid = iid.strip()
            if not iid:
                continue
            row = conn.execute("SELECT name, price, specs FROM food_cache WHERE item_key=?", (iid,)).fetchone()
            if row:
                try:
                    specs = json.loads(row["specs"]) if row["specs"] else {}
                except:
                    specs = {}
                metrics[iid] = {
                    "name": row["name"] or "",
                    "price": row["price"] or 0,
                    "status": specs.get("status", ""),
                    "monthlySales": specs.get("monthlySales", 0),
                }

    # Shop level
    shop_items = conn.execute("SELECT COUNT(*) as cnt FROM food_cache WHERE shop_id=?", (shop_id,)).fetchone()
    metrics["_shop"] = {"item_count": shop_items["cnt"] if shop_items else 0}
    conn.close()
    return metrics


def collect_meituan_metrics_cdp(shop_id, item_ids=None):
    """Collect metrics from 美团 backend via CDP (read-only).
    Navigates to 商品列表 and reads getSpuListCommon response.
    """
    import asyncio
    try:
        import websockets
    except ImportError:
        print("  [WARN] websockets not installed, skip meituan CDP collection")
        return {}

    async def _collect():
        # Find meituan tab
        try:
            import urllib.request
            tabs_raw = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json").read()
            tabs = json.loads(tabs_raw)
        except:
            print("  [WARN] CDP not available")
            return {}

        mt_tab = None
        for t in tabs:
            if t.get("type") == "page" and "meituan" in t.get("url", ""):
                mt_tab = t
                break
        if not mt_tab:
            print("  [WARN] No meituan tab found")
            return {}

        ws_url = mt_tab["webSocketDebuggerUrl"]
        async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
            # Enable network to capture response
            await ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
            await ws.recv()

            # Click 商品列表 to trigger data refresh
            await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": """
                (function() {
                    var items = document.querySelectorAll('.sub-menu-item_12D-nq');
                    for (var i = 0; i < items.length; i++) {
                        if (items[i].innerText.trim() === '商品列表') {
                            items[i].click();
                            return 'ok';
                        }
                    }
                    return 'not found';
                })()
            """}}))
            await ws.recv()

            # Wait for getSpuListCommon response
            spu_data = None
            req_map = {}
            try:
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    m = msg.get("method", "")
                    if m == "Network.requestWillBeSent":
                        url = msg["params"]["request"]["url"]
                        rid = msg["params"]["requestId"]
                        if "getSpuListCommon" in url:
                            req_map[rid] = True
                    elif m == "Network.loadingFinished":
                        rid = msg["params"]["requestId"]
                        if rid in req_map:
                            await ws.send(json.dumps({
                                "id": 300,
                                "method": "Network.getResponseBody",
                                "params": {"requestId": rid}
                            }))
                    elif "result" in msg and "body" in msg.get("result", {}):
                        try:
                            body = json.loads(msg["result"]["body"])
                            if body.get("data", {}).get("spuListVos"):
                                spu_data = body["data"]["spuListVos"]
                                break
                        except:
                            pass
            except asyncio.TimeoutError:
                pass

            if not spu_data:
                print("  [WARN] Could not get meituan product data")
                return {}

            metrics = {}
            target_ids = set(item_ids.split(",")) if item_ids else set()

            for spu in spu_data:
                spu_id = str(spu.get("id", ""))
                entry = {
                    "name": spu.get("name", ""),
                    "price": spu.get("price", 0),
                    "monthlySales": spu.get("monthSale", 0),
                    "status": "下架" if spu.get("sellStatus", 0) != 0 else "在售",
                    "discountPrice": spu.get("discountPrice", 0),
                }
                # If we have target item_ids, only include those; otherwise include all
                if target_ids:
                    if spu_id in target_ids:
                        metrics[spu_id] = entry
                else:
                    metrics[spu_id] = entry

            metrics["_shop"] = {
                "item_count": len(spu_data),
                "total_monthly_sales": sum(s.get("monthSale", 0) for s in spu_data),
            }
            return metrics

    return asyncio.run(_collect())


def process_due_tasks(dry_run=False):
    tasks = get_due_tasks()
    if not tasks:
        print("No due tracking tasks.")
        return

    print(f"Found {len(tasks)} due tracking tasks:")
    for t in tasks:
        print(f"  [{t['check_type']}] {t.get('shop_name','')} - {t.get('change_summary','')} (due {t['check_date']})")

    if dry_run:
        return

    for t in tasks:
        tid = t["id"]
        shop_id = t["shop_id"]
        platform = t["platform"]
        item_id = t.get("item_id", "")

        print(f"\nCollecting {t['check_type']} for {t.get('shop_name', shop_id)}...")

        if platform == "eleme":
            metrics = collect_eleme_metrics(shop_id, item_id)
        elif platform == "meituan":
            metrics = collect_meituan_metrics_cdp(shop_id, item_id)
        else:
            metrics = collect_eleme_metrics(shop_id, item_id)  # fallback

        if metrics:
            r = requests.post(f"{SERVER}/api/tracking/{tid}/collect", json={"metrics": metrics})
            print(f"  Saved: {r.json()}")
        else:
            print(f"  No metrics collected, skipping")


if __name__ == "__main__":
    dry_run = "--dry" in sys.argv
    process_due_tasks(dry_run=dry_run)
