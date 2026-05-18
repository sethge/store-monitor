#!/usr/bin/env python3
"""
Ops Logger - 店铺初始化快照 v2
通过CDP连接Tabbit，在已打开的饿了么菜品管理页面里：
1. 找到goods iframe (napos-goods-pc)
2. 逐个点击分类tab，触发queryFoodsByGroupGlobalId API
3. 通过Network.getResponseBody捕获每个分类的菜品数据
4. 解析并保存到food_cache + food_snapshot + shop_cache

前提: Tabbit已打开饿了么商家后台的菜品管理页面

用法:
  python3 init_snapshot.py              # 自动初始化当前打开的店铺
  python3 init_snapshot.py 529717284    # 指定shopId
"""

import json, time, sqlite3, os, sys
import websocket
import requests

CDP_PORT = 9444
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ops_logs.db")
SERVER_URL = "http://127.0.0.1:5500"


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(
            ws_url, timeout=60,
            suppress_origin=True,
            header=[f"Origin: http://127.0.0.1:{CDP_PORT}"]
        )
        self._id = 0

    def call(self, method, params=None, timeout=30):
        self._id += 1
        mid = self._id
        msg = {"id": mid, "method": method}
        if params:
            msg["params"] = params
        self.ws.send(json.dumps(msg))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.ws.settimeout(max(0.1, deadline - time.time()))
                resp = json.loads(self.ws.recv())
                if resp.get("id") == mid:
                    if "error" in resp:
                        print(f"  [CDP error] {resp['error'].get('message', '')}")
                    return resp
                # discard events silently
            except websocket.WebSocketTimeoutException:
                continue
        return None

    def drain(self, timeout=0.3):
        """Drain all pending messages"""
        while True:
            try:
                self.ws.settimeout(timeout)
                self.ws.recv()
            except:
                break

    def wait_for_api_response(self, url_match, timeout=8):
        """Wait for a Network.responseReceived matching url_match, return requestId"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.ws.settimeout(max(0.1, deadline - time.time()))
                evt = json.loads(self.ws.recv())
                if evt.get("method") == "Network.responseReceived":
                    url = evt["params"].get("response", {}).get("url", "")
                    if url_match in url:
                        return evt["params"].get("requestId")
            except websocket.WebSocketTimeoutException:
                continue
        return None

    def get_response_body(self, request_id, timeout=10):
        """Get response body for a request ID"""
        time.sleep(0.3)
        resp = self.call("Network.getResponseBody", {"requestId": request_id}, timeout)
        if resp and "result" in resp:
            return resp["result"].get("body", "")
        return None

    def eval_in_context(self, js, context_id, timeout=15):
        resp = self.call("Runtime.evaluate", {
            "expression": js,
            "contextId": context_id,
            "returnByValue": True,
        }, timeout)
        if not resp or "result" not in resp:
            return None
        return resp["result"].get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except:
            pass


def find_page_tab():
    targets = requests.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=5).json()
    for t in targets:
        if t.get("type") == "page" and "ele.me" in t.get("url", "") and "webSocketDebuggerUrl" in t:
            return t
    return None


def find_goods_iframe(cdp):
    resp = cdp.call("Page.getFrameTree")
    if not resp or "result" not in resp:
        return None
    def search(node):
        f = node.get("frame", {})
        if "napos-goods" in f.get("url", ""):
            return f.get("id")
        for c in node.get("childFrames", []):
            r = search(c)
            if r:
                return r
        return None
    return search(resp["result"]["frameTree"])


def parse_foods(body_text, category_name=""):
    """Parse queryFoodsByGroupGlobalId response"""
    try:
        data = json.loads(body_text)
    except:
        return []

    foods_raw = data.get("result", {}).get("foods", [])
    foods = []
    for f in foods_raw:
        if not isinstance(f, dict) or not f.get("name"):
            continue

        # Price from specs
        price = 0
        specs = f.get("specs", [])
        parsed_specs = []
        if isinstance(specs, list):
            for s in specs:
                if isinstance(s, dict):
                    sp = {
                        "id": str(s.get("id", s.get("specGlobalId", ""))),
                        "name": s.get("name", ""),
                        "price": s.get("price", 0),
                        "stock": s.get("stock", -1),
                    }
                    parsed_specs.append(sp)
                    if sp["price"] and not price:
                        price = sp["price"]

        foods.append({
            "itemId": str(f.get("vfoodId", "")),
            "itemGlobalId": str(f.get("itemGlobalId", "")),
            "name": f["name"],
            "price": price,
            "image": f.get("imageUrl", ""),
            "description": "",
            "status": "上架" if f.get("onShelf", True) else "下架",
            "monthlySales": f.get("recentSales", 0),
            "categoryName": category_name,
            "specs": parsed_specs,
            "shopId": str(f.get("restaurantId", "")),
        })

    return foods


def save_to_db(shop_id, shop_name, all_foods):
    """Save to food_cache + food_snapshot + shop_cache"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Ensure tables
    for sql in [
        """CREATE TABLE IF NOT EXISTS food_cache (
            item_key TEXT PRIMARY KEY, item_id TEXT, shop_id TEXT,
            name TEXT, price REAL, specs TEXT, updated_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS shop_cache (
            shop_id TEXT PRIMARY KEY, shop_name TEXT, platform TEXT, updated_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS food_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id TEXT, shop_name TEXT, platform TEXT DEFAULT 'eleme',
            item_id TEXT, item_global_id TEXT, category_name TEXT,
            name TEXT, price REAL, image_url TEXT, specs TEXT,
            status TEXT, monthly_sales INTEGER DEFAULT 0,
            description TEXT, snapshot_at TEXT, raw_data TEXT)""",
    ]:
        conn.execute(sql)

    # Clear old data
    conn.execute("DELETE FROM food_cache WHERE shop_id=?", (shop_id,))
    conn.execute("DELETE FROM food_snapshot WHERE shop_id=?", (shop_id,))

    if shop_name:
        conn.execute(
            "INSERT OR REPLACE INTO shop_cache (shop_id, shop_name, platform, updated_at) VALUES (?,?,?,?)",
            (shop_id, shop_name, "eleme", now))

    # Dedup
    seen = set()
    unique = []
    for f in all_foods:
        key = f["itemGlobalId"] or f["itemId"]
        if key and key not in seen:
            seen.add(key)
            unique.append(f)

    for f in unique:
        cache_data = json.dumps({
            "name": f["name"], "price": f["price"],
            "image": f.get("image", ""),
            "description": f.get("description", ""),
            "monthlySales": f.get("monthlySales", 0),
            "status": f["status"],
            "category": f.get("categoryName", ""),
            "specs": f.get("specs", []),
        }, ensure_ascii=False)

        for key in [f["itemId"], f["itemGlobalId"]]:
            if key and key != "None" and key != "":
                conn.execute(
                    "INSERT OR REPLACE INTO food_cache (item_key, item_id, shop_id, name, price, specs, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (str(key), f["itemId"], shop_id, f["name"], f["price"], cache_data, now))

        conn.execute(
            """INSERT INTO food_snapshot
            (shop_id, shop_name, platform, item_id, item_global_id, category_name,
             name, price, image_url, specs, status, monthly_sales, description, snapshot_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (shop_id, shop_name or "", "eleme",
             f["itemId"], f["itemGlobalId"], f.get("categoryName", ""),
             f["name"], f["price"], f.get("image", ""),
             json.dumps(f.get("specs", []), ensure_ascii=False),
             f["status"], f.get("monthlySales", 0),
             f.get("description", ""), now))

    conn.commit()
    fc = conn.execute("SELECT count(*) FROM food_cache WHERE shop_id=?", (shop_id,)).fetchone()[0]
    fs = conn.execute("SELECT count(*) FROM food_snapshot WHERE shop_id=?", (shop_id,)).fetchone()[0]
    sc = conn.execute("SELECT count(*) FROM shop_cache").fetchone()[0]
    conn.close()
    print(f"\n  [DB] food_cache={fc}, food_snapshot={fs}, shop_cache={sc}")
    return len(unique)


def sync_to_server(shop_id, shop_name, all_foods):
    """Sync to server /api/cache/sync"""
    try:
        food_data = [{
            "itemId": f["itemId"], "itemGlobalId": f["itemGlobalId"],
            "name": f["name"], "price": f["price"], "shopId": shop_id,
            "image": f.get("image", ""), "description": f.get("description", ""),
            "monthlySales": f.get("monthlySales", 0),
            "isOnShelf": f["status"] == "上架",
            "categoryName": f.get("categoryName", ""),
            "specs": f.get("specs", []),
        } for f in all_foods]

        if food_data:
            r = requests.post(f"{SERVER_URL}/api/cache/sync",
                json={"type": "foods", "data": food_data}, timeout=10)
            print(f"  [server] foods: {r.json()}")

        if shop_name:
            r = requests.post(f"{SERVER_URL}/api/cache/sync",
                json={"type": "shops", "data": [{"shopId": shop_id, "shopName": shop_name}]},
                timeout=10)
            print(f"  [server] shop: {r.json()}")
    except Exception as e:
        print(f"  [server] sync error: {e}")


def main():
    print("Ops Logger - 店铺初始化快照 v2")
    print("=" * 50)

    tab = find_page_tab()
    if not tab:
        print("[error] 没有打开饿了么页面")
        sys.exit(1)

    print(f"[ok] 连接: {tab['url'][:80]}")
    cdp = CDP(tab["webSocketDebuggerUrl"])
    cdp.call("Network.enable", {"maxTotalBufferSize": 10000000})
    cdp.call("Page.enable")

    # Shop ID
    shop_id = ""
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        shop_id = sys.argv[1]
    else:
        resp = cdp.call("Runtime.evaluate", {
            "expression": "(location.href.match(/shop\\/(\\d+)/) || [])[1] || ''",
            "returnByValue": True
        })
        if resp:
            shop_id = resp.get("result", {}).get("result", {}).get("value", "")

    if not shop_id:
        print("[error] 无法获取shopId")
        cdp.close()
        sys.exit(1)
    print(f"[ok] shopId: {shop_id}")

    # Shop name from DOM sidebar
    shop_name = ""
    resp = cdp.call("Runtime.evaluate", {
        "expression": """
        (function() {
            // Ele.me merchant backend: shop name is in sidebar, typically a span with fontSize>=14
            // that contains Chinese chars and isn't a menu item
            var sidebar = document.querySelector('[class*="aside"], [class*="sidebar"], [class*="layout"]');
            if (sidebar) {
                var spans = sidebar.querySelectorAll('span');
                for (var s of spans) {
                    var t = s.textContent.trim();
                    // Shop name pattern: Chinese chars, contains · or ( or is 3-30 chars
                    if (t.length > 3 && t.length < 40 && s.children.length === 0
                        && /[\u4e00-\u9fff]/.test(t)
                        && !['商家版','搜 索','门店已下线'].includes(t)
                        && !/管理|中心|首页|订单|商品|顾客|数据|财务|营销|推广|成长|安全|金融|服务|搜索/.test(t)) {
                        return t;
                    }
                }
            }
            return '';
        })()
        """,
        "returnByValue": True
    })
    if resp:
        shop_name = resp.get("result", {}).get("result", {}).get("value", "")
    print(f"[info] 店铺名: {shop_name or '(待从API获取)'}")

    # Find goods iframe
    iframe_id = find_goods_iframe(cdp)
    if not iframe_id:
        print("[error] 找不到菜品管理iframe")
        cdp.close()
        sys.exit(1)

    # Create isolated world
    resp = cdp.call("Page.createIsolatedWorld", {
        "frameId": iframe_id, "worldName": "OpsInit"
    })
    if not resp or "result" not in resp:
        print("[error] 无法创建iframe执行上下文")
        cdp.close()
        sys.exit(1)
    ctx_id = resp["result"]["executionContextId"]
    print(f"[ok] iframe context: {ctx_id}")

    # Get categories
    cats_json = cdp.eval_in_context("""
    (function() {
        var tabs = document.querySelectorAll('[class*="groupItemContainer"]');
        var cats = [];
        for (var i = 0; i < tabs.length; i++) {
            cats.push({i: i, text: tabs[i].textContent.trim()});
        }
        return JSON.stringify(cats);
    })()
    """, ctx_id)

    categories = json.loads(cats_json) if isinstance(cats_json, str) else (cats_json or [])
    if not categories:
        print("[error] 找不到分类tab")
        cdp.close()
        sys.exit(1)

    print(f"[ok] {len(categories)} 个分类:")
    for c in categories:
        # Clean name: remove trailing count like (5)
        name = c["text"]
        print(f"     {c['i']}: {name}")

    # Click each category and capture food data
    all_foods = []
    for cat in categories:
        cat_name = cat["text"]
        # Clean: remove count suffix like (5), 限时置顶 etc
        import re
        clean_name = re.sub(r'\(\d+\).*$', '', cat_name).strip()

        print(f"\n  [{cat['i']+1}/{len(categories)}] {clean_name}")

        # Drain old events
        cdp.drain(0.3)

        # Click
        click_result = cdp.eval_in_context(
            f"document.querySelectorAll('[class*=\"groupItemContainer\"]')[{cat['i']}].click(); 'ok'",
            ctx_id, timeout=5)

        if click_result != "ok":
            print(f"    [warn] click failed")
            continue

        # Wait for API response
        time.sleep(1.5)
        rid = cdp.wait_for_api_response("app-api.shop.ele.me", timeout=6)

        if not rid:
            print(f"    [warn] no API response")
            continue

        body = cdp.get_response_body(rid)
        if not body:
            print(f"    [warn] no response body")
            continue

        foods = parse_foods(body, clean_name)
        all_foods.extend(foods)

        # Show what we got
        for f in foods:
            s = "✓" if f["status"] == "上架" else "✗"
            p = f["price"]
            print(f"    [{s}] {f['name']}  ¥{p}  月售{f['monthlySales']}")

        if not foods:
            print(f"    (无菜品)")

        time.sleep(0.3)

    # Dedup
    seen = set()
    unique = []
    for f in all_foods:
        key = f["itemGlobalId"] or f["itemId"]
        if key and key not in seen:
            seen.add(key)
            unique.append(f)

    print(f"\n{'='*50}")
    print(f"捕获完成: {len(unique)} 个菜品")

    # Summary by category
    cats_summary = {}
    for f in unique:
        cat = f.get("categoryName", "未分类")
        cats_summary[cat] = cats_summary.get(cat, 0) + 1
    for cat, count in cats_summary.items():
        print(f"  {cat}: {count}")

    if not unique:
        print("\n[error] 没有捕获到菜品!")
        cdp.close()
        sys.exit(1)

    # Save
    save_to_db(shop_id, shop_name, unique)
    sync_to_server(shop_id, shop_name, unique)

    cdp.call("Network.disable")
    cdp.close()

    print(f"\n初始化完成! {shop_name or shop_id}: {len(unique)}个菜品")


if __name__ == "__main__":
    main()
