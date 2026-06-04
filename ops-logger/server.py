"""
Ops Logger Server v4.0 - 接收运营操作日志 + 结构化解析 + 改前值追踪 + 巡检/预警直执行
端口: 5500
"""
import json, sqlite3, os, re, subprocess, threading, sys, socket
import requests as http_requests
from datetime import datetime, timedelta, timezone

# 统一用北京时间（UTC+8），不依赖系统时区
_CN_TZ = timezone(timedelta(hours=8))
def cn_now():
    return datetime.now(_CN_TZ)
from flask import Flask, request, jsonify, render_template_string, send_from_directory

PYTHON = sys.executable

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route("/chat-test")
def chat_test_page():
    return send_from_directory(os.path.dirname(__file__), "chat_test.html")

DB_PATH = os.path.join(os.path.dirname(__file__), "ops_logs.db")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT,
            timestamp TEXT,
            api_method TEXT,
            url TEXT,
            body_full TEXT,
            platform TEXT,
            shop_id TEXT,
            shop_name TEXT,
            tab_id INTEGER,
            item_id TEXT,
            item_name TEXT,
            action_type TEXT,
            action_detail TEXT,
            before_snapshot TEXT,
            changes TEXT,
            page_type TEXT,
            received_at TEXT DEFAULT (datetime('now','localtime')),
            reported INTEGER DEFAULT 0,
            change_summary TEXT
        )
    """)
    # 兼容旧表：加reported列（如果不存在）
    try:
        conn.execute("SELECT reported FROM logs LIMIT 1")
    except:
        try:
            conn.execute("ALTER TABLE logs ADD COLUMN reported INTEGER DEFAULT 0")
        except:
            pass
    try:
        conn.execute("SELECT change_summary FROM logs LIMIT 1")
    except:
        try:
            conn.execute("ALTER TABLE logs ADD COLUMN change_summary TEXT")
        except:
            pass
    # v3: changes + page_type columns
    for col, ctype in [("changes", "TEXT"), ("page_type", "TEXT")]:
        try:
            conn.execute(f"SELECT {col} FROM logs LIMIT 1")
        except:
            try:
                conn.execute(f"ALTER TABLE logs ADD COLUMN {col} {ctype}")
            except:
                pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS food_cache (
            item_key TEXT PRIMARY KEY,
            item_id TEXT,
            shop_id TEXT,
            name TEXT,
            price REAL,
            specs TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shop_cache (
            shop_id TEXT PRIMARY KEY,
            shop_name TEXT,
            platform TEXT,
            updated_at TEXT
        )
    """)
    # Migrate old table if needed
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(logs)").fetchall()]
        migrations = {
            "item_id": "ALTER TABLE logs ADD COLUMN item_id TEXT",
            "item_name": "ALTER TABLE logs ADD COLUMN item_name TEXT",
            "action_type": "ALTER TABLE logs ADD COLUMN action_type TEXT",
            "action_detail": "ALTER TABLE logs ADD COLUMN action_detail TEXT",
            "before_snapshot": "ALTER TABLE logs ADD COLUMN before_snapshot TEXT",
            "body_full": "ALTER TABLE logs ADD COLUMN body_full TEXT",
            "shop_name": "ALTER TABLE logs ADD COLUMN shop_name TEXT",
            "change_summary": "ALTER TABLE logs ADD COLUMN change_summary TEXT",
            "after_snapshot": "ALTER TABLE logs ADD COLUMN after_snapshot TEXT",
        }
        for col, sql in migrations.items():
            if col not in cols:
                conn.execute(sql)
    except Exception as e:
        print(f"[migration] {e}")
    # food_snapshot table (created by init_snapshot.py, ensure it exists)
    # Change tracking: auto follow-up at T+3 and T+7
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operator_stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT,
            brand TEXT,
            store TEXT,
            shop_id TEXT,
            platform TEXT,
            ish_id TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS change_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_id INTEGER,
            shop_id TEXT,
            platform TEXT,
            action_type TEXT,
            check_type TEXT,
            check_date TEXT,
            status TEXT DEFAULT 'pending',
            metrics_before TEXT,
            metrics_after TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            checked_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shop_metrics_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id TEXT,
            platform TEXT,
            snapshot_date TEXT,
            metrics TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS food_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id TEXT, shop_name TEXT, platform TEXT DEFAULT 'eleme',
            item_id TEXT, item_global_id TEXT, category_name TEXT,
            name TEXT, price REAL, image_url TEXT, specs TEXT,
            status TEXT, monthly_sales INTEGER DEFAULT 0,
            description TEXT, snapshot_at TEXT, raw_data TEXT
        )
    """)
    # 小q主动消息队列
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT,
            trigger_type TEXT,
            trigger_key TEXT,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            read_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return DEFAULT_CONFIG

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

DEFAULT_CONFIG = {
    "version": 1,
    "ignore_api_methods": [
        "HeadNoticeService.queryTabHeadNotice",
        "TraceService.trace",
        "PollingService.unprocessedOrders",
        "PollingService.abnormalOrders",
        "PollingService.nonCoreOrders",
        "PollingService.getPollingStrategy",
        "PushService.polling",
        "IMChatService.getChatInfo",
        "IMChatService.getImInfo",
        "ShopMessageService.pollingNotifyV2",
        "ShopMessageService.getShopMessageList",
        "ShopMessageService.getMessageTabShowStyle",
        "SceneManageService.getSpaceInfoBySpaceCodes",
        "OrderWebService.queryInProcessOrders",
        "OrderWebService.queryHeadDataByInProcessQueryType",
        "OrderWebService.queryTabDataForWeb",
        "OrderWebService.countMenuOrder",
        "OrderWebService.getWebClientSettings",
        "ShopQueryService.queryAdBanner",
        "ShopQueryService.queryExceptionInfo",
        "ShopQueryService.queryDataByTab",
        "ShopQueryService.hitAutoMealRightGray",
        "ShopSettingService.getOrderSetting",
        "ShopSettingService.getRemindCookTimeSetting",
        "OrderSettingService.checkSettingStatus",
        "BusinessAssistService.getOrderProcessTips",
        "DeliveryClaimService.getOrderClaimTips",
        "RpcStrategyTriggerService.getOfflineMessage",
        "GrayService.inGray",
        "GrayService.getGrayStatusByKeys",
        "GrayService.getRestaurantAttribute",
        "GrayService.grayMenuAppealCompensation2Gray",
        "GrayNcpService.isInGray",
        "GrayControlService.getConfigV2",
        "ABTestService.getResult",
        "AlscTagService.queryTagsByTagId",
        "AssistantEntranceService.getAssistantEntranceInfo",
        "AssistantEntranceService.getValidPages",
        "AuthCenterService.getToken",
        "CrmOpenService.checkCrmEntry",
        "DownloadDataService.queryHistoryList",
        "ExportRatingTaskService.queryExportRatingTasks",
        "FoodService2.getFoodTabWithType",
        "FoodService2.getPcFoodManageButton",
        "FoodService2.queryCategoryWithFoodFilter",
        "KeeperService.getKeeper",
        "PackageItemService.getRecommendPackageMigradeList",
        "PersonalCustomerManageService.personalCustomerGray",
        "ShopService.queryAgreement",
        "AssistantService2.getShopIntelligentSortStatus",
        "queryShop.getShopView",
        "shopRating.countNewShopRating",
        "ShopMessageService.setNotifiedV2",
        "ShopMessageService.setAllNotified",
        "ShopMessageService.getUnreadCount",
        "ShopService.getShopInfo",
        "DeliveryService.getDeliveryManageAdditionalView",
        "NewCustomerService.validateChannelPriorityWhenCreate",
        "DownloadDataService.queryHistoryList"
    ],
    "ignore_api_prefixes": [
        "xtop.shop.shopBusinessQueryTop.",
        "xtop.arena.",
        "xtop.napos.",
        "xtop.pts.",
        "xtop.ebot."
    ],
    "ignore_urls": [
        "/log/", "/track/", "/beacon/", "/analytics/", "/collect",
        "report.meituan.com", "sentry", "aegis", "arms-retcode",
        "/pv", "/webdfpid", "/fingerprint/", "/bio/info/report",
        "spiderindefence", "yoda_seed", "sdk_ver",
        ".png", ".jpg", ".gif", ".css", ".woff", ".ttf"
    ]
}

# ========== Action parsing ==========

def parse_body(body_str):
    """Parse body JSON string, return dict or empty dict"""
    if not body_str:
        return {}
    try:
        return json.loads(body_str) if isinstance(body_str, str) else body_str
    except:
        return {}

def extract_shop_id(body):
    """Extract shopId from parsed body"""
    if not isinstance(body, dict):
        return ""
    metas = body.get("metas", {})
    if metas and metas.get("shopId"):
        return str(metas["shopId"])
    params = body.get("params", {})
    # Top-level shopId in params (e.g. NewCustomerService.createActivity)
    if params.get("shopId"):
        return str(params["shopId"])
    for v in params.values():
        if isinstance(v, dict) and v.get("shopId"):
            return str(v["shopId"])
    return ""

def extract_item_id_from_body(api_method, body):
    """Server-side extraction of item_id from body (fallback when extension fails)"""
    if not isinstance(body, dict):
        return ""
    params = body.get("params", {})

    # updateGoodsAttr
    if "updateGoodsAttr" in api_method:
        attr = params.get("updateGoodsAttr", {})
        if isinstance(attr, dict) and attr.get("itemId"):
            return str(attr["itemId"])

    # batchUpdateFood
    if "batchUpdateFood" in api_method:
        req = params.get("request", {})
        ids = req.get("itemGlobalIds", [])
        if ids:
            return ",".join(str(i) for i in ids)

    # updateFood / generic
    for key in ("food", "request"):
        food = params.get(key, {})
        if isinstance(food, dict):
            for id_key in ("id", "itemId", "itemGlobalId"):
                if food.get(id_key):
                    return str(food[id_key])

    return ""

def extract_item_name_from_body(api_method, body):
    """Server-side extraction of item_name from body"""
    if not isinstance(body, dict):
        return ""
    params = body.get("params", {})

    if "updateGoodsAttr" in api_method:
        attr = params.get("updateGoodsAttr", {})
        return attr.get("name", "")

    for key in ("food", "request"):
        food = params.get(key, {})
        if isinstance(food, dict):
            return food.get("name", food.get("foodName", ""))

    return ""

def parse_action(api_method, body, conn=None):
    """Parse API + body into (action_type, action_detail)
    Covers: 饿了么 + 美团 merchant backend APIs
    conn: optional DB connection for looking up food names from cache
    """
    params = body.get("params", {}) if isinstance(body, dict) else {}
    m = api_method.lower()

    # ====== 菜品管理 ======

    # 上下架 (饿了么 batchUpdateFood / 美团 batchOnShelf/batchOffShelf)
    if "batchupdatefood" in m or "batchonshelf" in m or "batchoffshelf" in m:
        req = params.get("request", {})
        is_on = req.get("isOnShelf")
        if is_on is None:
            is_on = "onshelf" in m
        ids = req.get("itemGlobalIds", req.get("foodIds", req.get("spuIds", [])))
        names = []
        if conn and ids:
            for gid in ids:
                cached = conn.execute("SELECT name FROM food_cache WHERE item_key=?", (str(gid),)).fetchone()
                if cached and cached["name"]:
                    names.append(cached["name"])
        name_str = ", ".join(names) if names else f"{len(ids)}个菜品"
        if is_on is True or is_on == True:
            return "上架", name_str
        elif is_on is False or is_on == False:
            return "下架", name_str
        return "批量修改", name_str

    # 改属性/价格/名称 (饿了么 updateGoodsAttr)
    if "updategoodsattr" in m:
        attr = params.get("updateGoodsAttr", {})
        name = attr.get("name", "")
        specs = attr.get("sfoodSpecs", [])
        if specs and any(s.get("price") is not None for s in specs):
            return "改价", name
        if specs:
            return "改规格", name
        if attr.get("imagePath") or attr.get("image"):
            return "改图片", name
        if name:
            return "改名", name
        return "改属性", name

    # 修改菜品 (通用: updateFood/editFood/updateSku)
    if ("updatefood" in m or "editfood" in m or "modifyfood" in m or "updatesku" in m) and "batch" not in m:
        food = params.get("food", params.get("request", params))
        name = food.get("name", food.get("foodName", "")) if isinstance(food, dict) else ""
        return "修改菜品", name

    # 新建菜品
    if "createfood" in m or "addfood" in m or "savefood" in m:
        food = params.get("food", params.get("request", params))
        name = food.get("name", "") if isinstance(food, dict) else ""
        return "新建菜品", name

    # 删除菜品
    if "deletefood" in m or "removefood" in m:
        return "删除菜品", ""

    # 菜品排序 (饿了么 sortFood / 美团 sortSpu)
    if "sortfood" in m or "sortspu" in m or "sortgoods" in m or ("sort" in m and "food" in m):
        return "菜品排序", ""

    # 菜品图片 (饿了么 uploadImage / updateImage / 美团 saveFoodImage)
    if ("image" in m or "picture" in m or "photo" in m) and ("upload" in m or "update" in m or "save" in m):
        return "改图片", ""

    # ====== 套餐 ======
    if "combo" in m or "package" in m or "setmeal" in m or "taocan" in m:
        if "create" in m or "add" in m or "save" in m:
            return "新建套餐", ""
        if "update" in m or "edit" in m or "modify" in m:
            return "修改套餐", ""
        if "delete" in m or "remove" in m:
            return "删除套餐", ""

    # ====== 分类 ======
    if "category" in m or "group" in m and "food" not in m:
        cat = params.get("category", params.get("request", {}))
        name = cat.get("name", cat.get("categoryName", "")) if isinstance(cat, dict) else ""
        if "create" in m or "add" in m:
            return "新建分类", name
        if "update" in m or "edit" in m or "modify" in m:
            return "修改分类", name
        if "delete" in m or "remove" in m:
            return "删除分类", name
        if "sort" in m:
            return "排序分类", ""

    # ====== 满减活动 ======
    # 饿了么: FullReductionService / manjian / SkuActivityService
    # 美团: wmactpc related, activitySave, discount
    if any(kw in m for kw in ("fullreduction", "manjian", "skuactivity", "减")) and "skudiscount" not in m:
        if "delete" in m or "close" in m or "cancel" in m or "stop" in m:
            return "关闭满减", ""
        if "update" in m or "edit" in m or "modify" in m:
            return "修改满减", ""
        return "创建满减", ""

    # ====== 新客立减 ======
    if "newcustomer" in m or "新客" in m:
        if "close" in m or "delete" in m or "cancel" in m:
            return "关闭活动", ""
        if "update" in m or "edit" in m:
            return "修改活动", ""
        return "创建活动", ""

    # ====== 天天神券 ======
    if any(kw in m for kw in ("coupon", "voucher", "神券", "券")):
        if "delete" in m or "close" in m or "quit" in m or "cancel" in m:
            return "关闭神券", ""
        if "update" in m or "edit" in m:
            return "修改神券", ""
        return "设置神券", ""

    # 折扣商品 (饿了么 SkuDiscount / 美团 折扣)
    if "skudiscount" in m or ("折扣" in m) or ("flashsale" in m):
        if "delete" in m or "close" in m:
            return "关闭折扣", ""
        if "update" in m or "edit" in m:
            return "修改折扣", ""
        return "设置折扣", ""

    # ====== 通用活动（Activity 兜底）======
    if "activity" in m:
        if "delete" in m or "close" in m or "cancel" in m or "stop" in m:
            return "关闭活动", ""
        if "update" in m or "edit" in m or "modify" in m:
            return "修改活动", ""
        return "创建活动", ""

    # ====== 推广 ======
    if any(kw in m for kw in ("promotion", "ad", "推广", "cpc", "bid", "campaign", "adgroup")):
        if "delete" in m or "close" in m or "stop" in m or "pause" in m or "cancel" in m:
            return "关闭推广", ""
        if "update" in m or "edit" in m or "modify" in m or "adjust" in m or "set" in m:
            return "调整推广", ""
        return "开启推广", ""

    # ====== 配送费 ======
    if any(kw in m for kw in ("delivery", "shipping", "配送", "运费")):
        return "修改配送费", ""

    # ====== 评价回复 ======
    if "reply" in m or "replyrating" in m or "回复" in m:
        content = ""
        for v in params.values():
            if isinstance(v, dict) and v.get("replyContent"):
                content = v["replyContent"][:50]
                break
            if isinstance(v, str) and len(v) > 5:
                content = v[:50]
                break
        return "回复评价", content

    # ====== 店铺信息 ======
    if any(kw in m for kw in ("updateshop", "shopservice.update", "saveshop", "editshop",
                               "shopinfo", "shopname", "shoplogo", "announcement")):
        return "修改店铺信息", ""

    # ====== 美团特有 ======
    # 美团拼好饭
    if "pinhao" in m or "拼好饭" in m or "pinhaofan" in m:
        if "quit" in m or "cancel" in m or "delete" in m:
            return "退出拼好饭", ""
        return "报名拼好饭", ""

    # 美团超抢手/爆品团
    if any(kw in m for kw in ("superstar", "超抢手", "爆品", "hotdeal", "hotsale")):
        if "quit" in m or "cancel" in m or "close" in m or "delete" in m:
            return "关闭超抢手", ""
        return "设置超抢手", ""

    # ====== Fallback ======
    method_name = api_method.split(".")[-1] if "." in api_method else api_method
    return method_name, ""


def _build_summary_from_changes(changes_str, action_type=""):
    """从v3快照diff生成人话摘要。changes是JSON数组: [{target, field, from, to}, ...]"""
    try:
        changes = json.loads(changes_str) if isinstance(changes_str, str) else changes_str
    except:
        return ""
    if not changes or not isinstance(changes, list):
        return ""

    parts = []
    for c in changes[:5]:  # 最多显示5条变化
        target = c.get("target", "")
        field = c.get("field", "")
        frm = c.get("from", "")
        to = c.get("to", "")
        if target and frm and to:
            parts.append(f"「{target}」{field}: {frm} → {to}")
        elif target and to:
            parts.append(f"「{target}」{field}: → {to}")
        elif target:
            parts.append(f"「{target}」{field}")
        elif frm and to:
            parts.append(f"{field}: {frm} → {to}")
        elif to:
            parts.append(f"{field}: → {to}")
    if len(changes) > 5:
        parts.append(f"...等{len(changes)}项变化")
    return "; ".join(parts)


def build_change_summary(action_type, api_method, body, before_snapshot):
    """Build one-line human-readable change summary.
    This is THE field shown on dashboard — must be immediately understandable.
    """
    params = body.get("params", {}) if isinstance(body, dict) else {}

    try:
        before = json.loads(before_snapshot) if isinstance(before_snapshot, str) else before_snapshot
    except:
        before = {}
    if not before:
        before = {}

    # DOM快照格式兼容：{"source":"dom","foods":[...],"cache":{...}}
    # 优先用cache（foodCache精确数据），降级用foods列表第一个
    if isinstance(before, dict) and before.get("source") == "dom":
        if isinstance(before.get("cache"), dict):
            before = before["cache"]
        elif isinstance(before.get("foods"), list) and len(before["foods"]) == 1:
            before = before["foods"][0]

    item_name = ""
    # Try to get item name from before or body
    if isinstance(before, dict) and "name" in before:
        item_name = before["name"]

    # ===== 菜品改价 =====
    if action_type == "改价":
        attr = params.get("updateGoodsAttr", {})
        new_specs = attr.get("sfoodSpecs", [])
        name = attr.get("name", "") or item_name
        old_price = before.get("price", 0) if before else 0
        new_price = new_specs[0].get("price", 0) if new_specs else 0
        if old_price and new_price and old_price != new_price:
            return f"「{name}」¥{old_price} → ¥{new_price}"
        elif new_price:
            return f"「{name}」→ ¥{new_price}"
        return f"「{name}」价格修改"

    # ===== 菜品改名 =====
    if action_type == "改名":
        attr = params.get("updateGoodsAttr", {})
        new_name = attr.get("name", "")
        old_name = before.get("name", "") if before else ""
        if old_name and new_name and old_name != new_name:
            return f"「{old_name}」→「{new_name}」"
        elif new_name:
            return f"→「{new_name}」"
        return "菜品改名"

    # ===== 上架/下架 =====
    if action_type in ("上架", "下架"):
        # Get names from before_snapshot (could be single or batch)
        names = []
        if isinstance(before, dict):
            if "name" in before:
                names = [before["name"]]
            elif all(isinstance(v, dict) for v in before.values()):
                names = [v.get("name", "?") for v in before.values() if v.get("name")]

        old_status = ""
        if isinstance(before, dict) and "status" in before:
            old_status = before["status"]
        elif isinstance(before, dict) and all(isinstance(v, dict) for v in before.values()):
            statuses = [v.get("status", "") for v in before.values()]
            if statuses:
                old_status = statuses[0]

        if len(names) == 1:
            if old_status:
                return f"「{names[0]}」{old_status} → {action_type}"
            return f"「{names[0]}」{action_type}"
        elif len(names) > 1:
            return f"{len(names)}个菜品{action_type}: {', '.join(names[:5])}"
        return f"菜品{action_type}"

    # ===== 改规格 =====
    if action_type == "改规格":
        attr = params.get("updateGoodsAttr", {})
        name = attr.get("name", "") or item_name
        new_specs = attr.get("sfoodSpecs", [])
        parts = []
        for s in new_specs:
            sp = []
            if s.get("price") is not None:
                sp.append(f"¥{s['price']}")
            if s.get("stock") is not None:
                sp.append(f"库存{s['stock']}")
            if sp:
                parts.append("/".join(sp))
        if parts:
            return f"「{name}」规格修改: {', '.join(parts)}"
        return f"「{name}」规格修改"

    # ===== 改属性 =====
    if action_type == "改属性":
        attr = params.get("updateGoodsAttr", {})
        name = attr.get("name", "") or item_name
        return f"「{name}」属性修改"

    # ===== 创建活动 =====
    if action_type == "创建活动":
        # NewCustomerService — 新客立减
        if "NewCustomer" in api_method:
            activity = params.get("activity", {})
            reduction = activity.get("reduction", "")
            begin = activity.get("beginDate", "")
            end = activity.get("endDate", "")
            date_range = ""
            if begin and end:
                date_range = f"（{begin[5:]}~{end[5:]}）"
            elif begin:
                date_range = f"（{begin[5:]}起）"
            if reduction:
                return f"新建 新客立减¥{reduction}{date_range}"
            return f"新建 新客活动{date_range}"

        # 满减活动
        if "manjian" in api_method.lower() or "fullReduction" in api_method:
            rules = params.get("rules", params.get("activity", {}).get("rules", []))
            if isinstance(rules, list) and rules:
                tiers = []
                for r in rules:
                    threshold = r.get("threshold", r.get("min", ""))
                    discount = r.get("discount", r.get("reduction", ""))
                    if threshold and discount:
                        tiers.append(f"{threshold}减{discount}")
                if tiers:
                    return f"新建 满减: {' / '.join(tiers)}"

        # Generic activity
        activity = params.get("activity", params)
        name = ""
        if isinstance(activity, dict):
            name = activity.get("activityName", activity.get("name", ""))
        return f"新建活动{': ' + name if name else ''}"

    # ===== 修改活动 =====
    if action_type == "修改活动":
        return "修改活动"

    # ===== 关闭活动 =====
    if action_type == "关闭活动":
        return "关闭活动"

    # ===== 新建菜品 =====
    if action_type == "新建菜品":
        food = params.get("food", params.get("request", {}))
        if isinstance(food, dict):
            name = food.get("name", "")
            price = food.get("price", 0)
            cat = food.get("categoryName", "")
            parts = [f"新建「{name}」"]
            if price:
                parts.append(f"¥{price}")
            if cat:
                parts.append(f"归入「{cat}」")
            return " ".join(parts)
        return "新建菜品"

    # ===== 删除菜品 =====
    if action_type == "删除菜品":
        if item_name:
            return f"删除「{item_name}」"
        return "删除菜品"

    # ===== 修改菜品 =====
    if action_type == "修改菜品":
        food = params.get("food", params.get("request", {}))
        name = food.get("name", food.get("foodName", "")) if isinstance(food, dict) else ""
        name = name or item_name
        return f"修改「{name}」" if name else "修改菜品"

    # ===== 分类操作 =====
    if "分类" in action_type:
        cat = params.get("category", params.get("request", {}))
        name = cat.get("name", cat.get("categoryName", "")) if isinstance(cat, dict) else ""
        if name:
            return f"{action_type}「{name}」"
        return action_type

    # ===== 回复评价 =====
    if action_type == "回复评价":
        content = ""
        for v in params.values():
            if isinstance(v, dict) and v.get("replyContent"):
                content = v["replyContent"][:40]
                break
        if content:
            return f"回复评价: \"{content}...\""
        return "回复评价"

    # ===== 批量修改 =====
    if action_type == "批量修改":
        names = []
        if isinstance(before, dict) and all(isinstance(v, dict) for v in before.values()):
            names = [v.get("name", "?") for v in before.values() if v.get("name")]
        if names:
            return f"批量修改: {', '.join(names[:5])}"
        return "批量修改"

    # ===== 修改店铺信息 =====
    if action_type == "修改店铺信息":
        return "修改店铺信息"

    # ===== 满减活动 =====
    if "满减" in action_type:
        # Try to extract tiers from params first, then body directly
        rules = _extract_manjian_rules(params) or _extract_manjian_rules(body if isinstance(body, dict) else {})
        if rules:
            return f"{action_type}: {' / '.join(rules)}"
        return action_type

    # ===== 改图片 =====
    if action_type == "改图片":
        attr = params.get("updateGoodsAttr", {})
        name = attr.get("name", "") or item_name
        return f"「{name}」更换图片" if name else "更换菜品图片"

    # ===== 菜品排序 =====
    if action_type == "菜品排序":
        return "调整菜品排序"

    # ===== 套餐 =====
    if "套餐" in action_type:
        food = params.get("food", params.get("request", params.get("combo", params)))
        name = ""
        if isinstance(food, dict):
            name = food.get("name", food.get("comboName", food.get("packageName", "")))
        if name:
            return f"{action_type}「{name}」"
        return action_type

    # ===== 推广 =====
    if "推广" in action_type:
        # Try to extract budget/bid info from params or body
        budget = ""
        search_dicts = [params, body if isinstance(body, dict) else {}]
        for src in search_dicts:
            if budget:
                break
            # Check direct keys first
            b = src.get("budget", src.get("dailyBudget", src.get("totalBudget", "")))
            bid = src.get("bid", src.get("cpcBid", src.get("price", "")))
            if b:
                budget = f"预算¥{b}"
            if bid:
                budget += f" 出价¥{bid}" if budget else f"出价¥{bid}"
            # Also check nested dicts
            if not budget:
                for v in src.values():
                    if isinstance(v, dict):
                        b = v.get("budget", v.get("dailyBudget", v.get("totalBudget", "")))
                        bid = v.get("bid", v.get("cpcBid", v.get("price", "")))
                        if b:
                            budget = f"预算¥{b}"
                        if bid:
                            budget += f" 出价¥{bid}" if budget else f"出价¥{bid}"
                        if budget:
                            break
        if budget:
            return f"{action_type} {budget}"
        return action_type

    # ===== 神券/折扣/配送费/拼好饭/超抢手 =====
    if action_type in ("设置神券", "修改神券", "关闭神券",
                        "设置折扣", "修改折扣", "关闭折扣",
                        "修改配送费",
                        "报名拼好饭", "退出拼好饭",
                        "设置超抢手", "关闭超抢手"):
        return action_type

    # ===== Fallback =====
    return action_type or api_method.split(".")[-1]


def _extract_manjian_rules(params):
    """Try to extract 满减 tiers from various body formats"""
    # Look in common locations
    for key in ("rules", "activity", "request", "data"):
        obj = params.get(key, {})
        if isinstance(obj, dict):
            rules = obj.get("rules", obj.get("ruleList", obj.get("discountRules", [])))
        elif isinstance(obj, list):
            rules = obj
        else:
            continue
        if isinstance(rules, list) and rules:
            tiers = []
            for r in rules:
                if not isinstance(r, dict):
                    continue
                threshold = r.get("threshold", r.get("min", r.get("condition", r.get("fullAmount", ""))))
                discount = r.get("discount", r.get("reduction", r.get("reduceAmount", r.get("amount", ""))))
                if threshold and discount:
                    tiers.append(f"{threshold}减{discount}")
            if tiers:
                return tiers
    return []

# ========== Change Tracking Helpers ==========

def _get_current_metrics_json(conn, shop_id, platform, item_id=None):
    """Snapshot current metrics from food_cache for the shop/item."""
    metrics = {}
    if item_id:
        for iid in item_id.split(","):
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
    # Also store shop-level item count
    shop_items = conn.execute("SELECT COUNT(*) as cnt FROM food_cache WHERE shop_id=?", (shop_id,)).fetchone()
    metrics["_shop"] = {"item_count": shop_items["cnt"] if shop_items else 0}
    return json.dumps(metrics, ensure_ascii=False)


# ========== API ==========

@app.route("/api/config")
def get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["POST"])
def update_config():
    cfg = request.get_json(silent=True)
    if not cfg:
        return jsonify({"error": "no data"}), 400
    save_config(cfg)
    return jsonify({"ok": True})

@app.route("/api/logs", methods=["POST"])
def receive_logs():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "no data"}), 400

    operator = data.get("operator", "unknown")
    logs = data.get("logs", [])
    if not logs:
        return jsonify({"saved": 0})

    conn = get_db()
    saved = 0
    for log in logs:
        url = log.get("url", "")
        platform = "eleme" if "ele.me" in url or "eleme" in url else "meituan" if "meituan" in url else "other"

        # Full body (v2: no truncation; v1 compat: bodySnippet)
        body_str = log.get("body") or log.get("bodySnippet", "")
        body = parse_body(body_str)

        # Structured fields - prefer from extension, fallback to body parsing
        shop_id = log.get("shopId", "") or extract_shop_id(body)
        shop_name = log.get("shopName", "")
        item_id = log.get("itemId", "")
        item_name = log.get("itemName", "")
        before_snapshot = log.get("beforeSnapshot", "")

        # Filter bad shop names (tab title artifacts)
        _BAD_SHOP_NAMES = {'淘宝闪购商家版', '饿了么商家版', '美团外卖商家版', '商家版', 'melody'}
        if shop_name in _BAD_SHOP_NAMES:
            shop_name = ""

        # Lookup shop name: prefer operator_stores (authoritative), fallback to shop_cache
        if shop_id and not shop_name:
            os_row = conn.execute("SELECT store FROM operator_stores WHERE shop_id=?", (str(shop_id),)).fetchone()
            if os_row:
                shop_name = os_row["store"]
            else:
                cached_shop = conn.execute("SELECT shop_name FROM shop_cache WHERE shop_id=?", (shop_id,)).fetchone()
                if cached_shop and cached_shop["shop_name"] not in _BAD_SHOP_NAMES:
                    shop_name = cached_shop["shop_name"]

        # Save shop name to cache (only good names)
        if shop_id and shop_name and shop_name not in _BAD_SHOP_NAMES:
            conn.execute(
                "INSERT OR REPLACE INTO shop_cache (shop_id, shop_name, platform, updated_at) VALUES (?,?,?,?)",
                (shop_id, shop_name, platform, cn_now().isoformat())
            )

        api_method = log.get("apiMethod", "")

        # Server-side extraction from body as fallback
        if not item_id:
            item_id = extract_item_id_from_body(api_method, body)
        if not item_name:
            item_name = extract_item_name_from_body(api_method, body)
        # 从food_cache补全item_name（冷启动时extension的foodCache可能为空）
        if item_id and not item_name:
            names = []
            for iid in item_id.split(","):
                iid = iid.strip()
                if not iid:
                    continue
                row = conn.execute("SELECT name FROM food_cache WHERE item_key=?", (iid,)).fetchone()
                if row and row["name"]:
                    names.append(row["name"])
            if names:
                item_name = ",".join(names)

        # Use extension's beforeSnapshot if provided (captured at onBeforeRequest time, most accurate).
        # Only fallback to food_cache when extension didn't send beforeSnapshot.
        # Why: cache/sync from response interceptor may update food_cache BEFORE the log arrives,
        # causing a race condition where before_snapshot = after_snapshot.
        if item_id:
            cache_before = {}
            for iid in item_id.split(","):
                iid = iid.strip()
                if not iid:
                    continue
                cached = conn.execute("SELECT name, price, specs FROM food_cache WHERE item_key=?", (iid,)).fetchone()
                if cached:
                    if not item_name:
                        item_name = cached["name"] if not item_name else item_name
                    cache_before[iid] = {
                        "name": cached["name"] or "",
                        "price": cached["price"] or 0,
                    }
                    try:
                        specs_data = json.loads(cached["specs"]) if cached["specs"] else {}
                        if isinstance(specs_data, dict):
                            cache_before[iid].update({k: v for k, v in specs_data.items() if k in ("status", "category", "image")})
                    except:
                        pass
            if cache_before and not before_snapshot:
                # Fallback: extension didn't provide beforeSnapshot, use food_cache
                if len(cache_before) == 1:
                    before_snapshot = json.dumps(list(cache_before.values())[0], ensure_ascii=False)
                else:
                    before_snapshot = json.dumps(cache_before, ensure_ascii=False)

        # If still no item_name, try food_cache by item_id
        if item_id and not item_name:
            names = []
            for iid in item_id.split(","):
                cached = conn.execute("SELECT name FROM food_cache WHERE item_key=?", (iid.strip(),)).fetchone()
                if cached and cached["name"]:
                    names.append(cached["name"])
            if names:
                item_name = ", ".join(names)

        action_type, action_detail = parse_action(api_method, body, conn)

        # 跳过非运营操作：
        # 1. 查询型POST（get/query/list等开头）
        # 2. action_type是纯英文驼峰（说明parse_action没识别出来，不是正常操作）
        if action_type:
            at_lower = action_type.lower()
            if any(at_lower.startswith(p) for p in ('get', 'query', 'list', 'count', 'check', 'fetch', 'search', 'find',
                    'batchquery', 'batchget', 'batchfetch', 'batchcheck', 'batchlist', 'batchcount', 'batchfind', 'batchsearch', 'batchload')):
                continue
            # 纯英文action_type = parse_action没识别，说明不是正常运营操作
            import re
            if re.fullmatch(r'[a-zA-Z0-9_.]+', action_type):
                continue

        # Build one-line human-readable change summary
        change_summary = build_change_summary(action_type, api_method, body, before_snapshot)

        # Update food_cache with NEW state after modification
        # This ensures next modification picks up the correct "before" value
        if item_id:
            for i, iid in enumerate(item_id.split(",")):
                iid = iid.strip()
                if not iid:
                    continue
                # Get existing cache entry to preserve fields we're not changing
                existing = conn.execute("SELECT specs FROM food_cache WHERE item_key=?", (iid,)).fetchone()
                existing_data = {}
                if existing and existing["specs"]:
                    try:
                        existing_data = json.loads(existing["specs"])
                    except:
                        pass

                # Determine the new name
                names = item_name.split(",") if item_name else []
                new_name = names[i].strip() if i < len(names) else (names[-1].strip() if names else "")
                if not new_name and existing_data.get("name"):
                    new_name = existing_data["name"]

                # Determine new price
                new_price = existing_data.get("price", 0)
                if action_type in ("改价", "改规格", "改规格/价格"):
                    attr = (body.get("params", {}) if isinstance(body, dict) else {}).get("updateGoodsAttr", {})
                    new_specs = attr.get("sfoodSpecs", [])
                    if new_specs and new_specs[0].get("price") is not None:
                        new_price = new_specs[0]["price"]

                # Update status for shelf operations
                new_status = existing_data.get("status", "")
                if action_type == "上架":
                    new_status = "上架"
                elif action_type == "下架":
                    new_status = "下架"

                # Build updated cache data
                cache_data = {**existing_data, "name": new_name, "price": new_price, "status": new_status}

                conn.execute(
                    "INSERT OR REPLACE INTO food_cache (item_key, item_id, shop_id, name, price, specs, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (iid, iid, shop_id, new_name, new_price,
                     json.dumps(cache_data, ensure_ascii=False), cn_now().isoformat())
                )

        after_snapshot = log.get("afterSnapshot", "")
        changes_str = log.get("changes", "")
        page_type = log.get("pageType", "")

        # v3: 如果有changes（快照diff），用它增强change_summary
        if changes_str and not change_summary:
            change_summary = _build_summary_from_changes(changes_str, action_type)

        conn.execute(
            """INSERT INTO logs (operator, timestamp, api_method, url, body_full, platform,
                shop_id, shop_name, tab_id, item_id, item_name, action_type, action_detail,
                before_snapshot, after_snapshot, changes, page_type, change_summary)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (operator, log.get("timestamp", ""), api_method, url[:500], body_str,
             platform, shop_id, shop_name, log.get("tab_id", 0), item_id, item_name,
             action_type, action_detail, before_snapshot, after_snapshot,
             changes_str, page_type, change_summary)
        )
        log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Auto-create T+3 and T+7 tracking for meaningful operations
        _SKIP_TRACKING = {"回复评价", "菜品排序", "修改店铺信息", "排序分类"}
        if action_type and action_type not in _SKIP_TRACKING and shop_id:
            ts = log.get("timestamp", "") or cn_now().isoformat()
            try:
                base = datetime.fromisoformat(ts.replace("Z", "+00:00")).date() if "T" in ts else cn_now().date()
            except:
                base = cn_now().date()
            # Take a "before" metrics snapshot at time of change
            before_metrics = _get_current_metrics_json(conn, shop_id, platform, item_id)
            for days, ctype in [(3, "3day"), (7, "7day")]:
                check_date = (base + timedelta(days=days)).isoformat()
                conn.execute(
                    """INSERT INTO change_tracking
                       (log_id, shop_id, platform, action_type, check_type, check_date, metrics_before)
                       VALUES (?,?,?,?,?,?,?)""",
                    (log_id, shop_id, platform, action_type, ctype, check_date, before_metrics)
                )

        saved += 1
    conn.commit()
    conn.close()
    return jsonify({"saved": saved})

@app.route("/api/logs", methods=["GET"])
def query_logs():
    operator = request.args.get("operator", "")
    limit = int(request.args.get("limit", 200))
    conn = get_db()
    if operator:
        rows = conn.execute("SELECT * FROM logs WHERE operator=? ORDER BY id DESC LIMIT ?", (operator, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/backfill_summary", methods=["POST"])
def backfill_summary():
    """Regenerate change_summary for all existing logs from body_full + before_snapshot"""
    conn = get_db()
    rows = conn.execute("SELECT id, api_method, body_full, before_snapshot, action_type FROM logs").fetchall()
    updated = 0
    for row in rows:
        body = parse_body(row["body_full"])
        action_type = row["action_type"] or ""
        api_method = row["api_method"] or ""
        before_snapshot = row["before_snapshot"] or ""
        # Re-parse action_type with new logic
        if body and api_method:
            action_type, _ = parse_action(api_method, body)
        summary = build_change_summary(action_type, api_method, body, before_snapshot)
        if summary:
            conn.execute("UPDATE logs SET change_summary=?, action_type=? WHERE id=?",
                         (summary, action_type, row["id"]))
            updated += 1
    conn.commit()
    conn.close()
    return jsonify({"updated": updated})

@app.route("/api/tracking", methods=["GET"])
def get_tracking():
    """Get tracking records. ?status=pending|done|disabled&log_id=X&operator=X"""
    conn = get_db()
    status = request.args.get("status", "")
    log_id = request.args.get("log_id", "")
    operator = request.args.get("operator", "")
    # 所有查询都JOIN logs拿产品名和店铺名
    base_sql = """SELECT ct.*, l.item_name, l.shop_name, l.change_summary, l.action_type as log_action_type, l.operator
                  FROM change_tracking ct LEFT JOIN logs l ON ct.log_id = l.id"""
    if log_id:
        rows = conn.execute(base_sql + " WHERE ct.log_id=? ORDER BY ct.check_date", (log_id,)).fetchall()
    elif operator:
        sql = base_sql + " WHERE l.operator = ?"
        if status:
            sql += " AND ct.status = ?"
            rows = conn.execute(sql + " ORDER BY ct.check_date LIMIT 200", (operator, status)).fetchall()
        else:
            rows = conn.execute(sql + " ORDER BY ct.id DESC LIMIT 200", (operator,)).fetchall()
    elif status:
        rows = conn.execute(base_sql + " WHERE ct.status=? ORDER BY ct.check_date LIMIT 200", (status,)).fetchall()
    else:
        rows = conn.execute(base_sql + " ORDER BY ct.id DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tracking/<int:tid>/disable", methods=["POST"])
def disable_tracking(tid):
    """Disable tracking for a specific record (user opted out)."""
    conn = get_db()
    conn.execute("UPDATE change_tracking SET status='disabled' WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/tracking/disable_log/<int:log_id>", methods=["POST"])
def disable_tracking_for_log(log_id):
    """Disable all tracking for a specific log entry."""
    conn = get_db()
    conn.execute("UPDATE change_tracking SET status='disabled' WHERE log_id=?", (log_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/tracking/enable_log/<int:log_id>", methods=["POST"])
def enable_tracking_for_log(log_id):
    """Re-enable tracking for a log entry (set disabled back to pending)."""
    conn = get_db()
    updated = conn.execute("UPDATE change_tracking SET status='pending' WHERE log_id=? AND status='disabled'", (log_id,)).rowcount
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "updated": updated})


@app.route("/api/tracking/due", methods=["GET"])
def get_due_tracking():
    """Get tracking records that are due today or overdue (for data collection)."""
    conn = get_db()
    today = cn_now().date().isoformat()
    rows = conn.execute(
        """SELECT ct.*, l.shop_name, l.change_summary, l.item_id, l.item_name, l.action_type as log_action_type
           FROM change_tracking ct
           JOIN logs l ON ct.log_id = l.id
           WHERE ct.status='pending' AND ct.check_date <= ?
           ORDER BY ct.check_date""",
        (today,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tracking/<int:tid>/collect", methods=["POST"])
def collect_tracking_metrics(tid):
    """Store the 'after' metrics for a tracking record. Called by data collection script."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "no data"}), 400

    conn = get_db()
    conn.execute(
        "UPDATE change_tracking SET status='done', metrics_after=?, checked_at=? WHERE id=?",
        (json.dumps(data.get("metrics", {}), ensure_ascii=False), cn_now().isoformat(), tid)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/tracking/summary", methods=["GET"])
def tracking_summary():
    """Dashboard summary: count by status, upcoming checks."""
    conn = get_db()
    today = cn_now().date().isoformat()

    pending = conn.execute("SELECT COUNT(*) as c FROM change_tracking WHERE status='pending'").fetchone()["c"]
    due = conn.execute("SELECT COUNT(*) as c FROM change_tracking WHERE status='pending' AND check_date<=?", (today,)).fetchone()["c"]
    done = conn.execute("SELECT COUNT(*) as c FROM change_tracking WHERE status='done'").fetchone()["c"]
    disabled = conn.execute("SELECT COUNT(*) as c FROM change_tracking WHERE status='disabled'").fetchone()["c"]

    # Upcoming checks (next 7 days)
    from datetime import timedelta
    upcoming = conn.execute(
        """SELECT ct.check_date, ct.check_type, ct.action_type, l.shop_name, l.change_summary
           FROM change_tracking ct JOIN logs l ON ct.log_id = l.id
           WHERE ct.status='pending' AND ct.check_date > ? AND ct.check_date <= ?
           ORDER BY ct.check_date LIMIT 20""",
        (today, (cn_now().date() + timedelta(days=7)).isoformat())
    ).fetchall()

    conn.close()
    return jsonify({
        "pending": pending, "due": due, "done": done, "disabled": disabled,
        "upcoming": [dict(r) for r in upcoming]
    })


@app.route("/api/cache/sync", methods=["POST"])
def sync_cache():
    """Receive food/shop cache from extension (passive capture from API responses)"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "no data"}), 400

    cache_type = data.get("type", "")
    items = data.get("data", [])
    if not items:
        return jsonify({"saved": 0})

    conn = get_db()
    saved = 0
    now = cn_now().isoformat()

    if cache_type == "foods":
        for f in items:
            item_id = str(f.get("itemId", ""))
            item_global_id = str(f.get("itemGlobalId", ""))
            shop_id = str(f.get("shopId", ""))
            name = f.get("name", "")
            price = f.get("price", 0)

            # Build rich cache data
            cache_data = json.dumps({
                "name": name, "price": price,
                "image": f.get("image", ""),
                "description": f.get("description", ""),
                "monthlySales": f.get("monthlySales", 0),
                "status": "上架" if f.get("isOnShelf", True) else "下架",
                "category": f.get("categoryName", ""),
                "specs": f.get("specs", []),
            }, ensure_ascii=False)

            for key in [item_id, item_global_id]:
                if key and key != "None" and key != "":
                    conn.execute(
                        "INSERT OR REPLACE INTO food_cache (item_key, item_id, shop_id, name, price, specs, updated_at) VALUES (?,?,?,?,?,?,?)",
                        (key, item_id, shop_id, name, price, cache_data, now)
                    )
                    saved += 1

            # Also update food_snapshot if exists
            if item_id:
                existing = conn.execute("SELECT id FROM food_snapshot WHERE item_id=? AND shop_id=?", (item_id, shop_id)).fetchone()
                if not existing:
                    conn.execute(
                        """INSERT INTO food_snapshot
                        (shop_id, platform, item_id, item_global_id, category_name, name, price,
                         image_url, specs, status, monthly_sales, description, snapshot_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (shop_id, "eleme", item_id, item_global_id, f.get("categoryName", ""),
                         name, price, f.get("image", ""),
                         json.dumps(f.get("specs", []), ensure_ascii=False),
                         "上架" if f.get("isOnShelf", True) else "下架",
                         f.get("monthlySales", 0), f.get("description", ""), now)
                    )

    elif cache_type == "shops":
        for s in items:
            shop_id = str(s.get("shopId", ""))
            shop_name = s.get("shopName", "")
            if shop_id and shop_name:
                conn.execute(
                    "INSERT OR REPLACE INTO shop_cache (shop_id, shop_name, platform, updated_at) VALUES (?,?,?,?)",
                    (shop_id, shop_name, "eleme", now)
                )
                saved += 1

    conn.commit()
    conn.close()
    print(f"[cache sync] {cache_type}: {saved} items")
    return jsonify({"saved": saved})

@app.route("/api/food_cache", methods=["GET"])
def get_food_cache():
    conn = get_db()
    rows = conn.execute("SELECT * FROM food_cache ORDER BY updated_at DESC LIMIT 500").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/cache_summary", methods=["GET"])
def cache_summary():
    conn = get_db()
    food_count = conn.execute("SELECT count(DISTINCT item_id) FROM food_cache").fetchone()[0]
    shop_count = conn.execute("SELECT count(*) FROM shop_cache").fetchone()[0]
    shops = [dict(r) for r in conn.execute("SELECT * FROM shop_cache").fetchall()]
    snapshot_count = conn.execute("SELECT count(*) FROM food_snapshot").fetchone()[0]
    conn.close()
    return jsonify({
        "food_count": food_count,
        "shop_count": shop_count,
        "snapshot_count": snapshot_count,
        "shops": shops
    })

# ========== Dashboard ==========

PAGE_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><title>Ops Logger</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, sans-serif; margin: 0; background: #f5f5f5; color: #333; }
  .header { background: linear-gradient(135deg, #e94560 0%, #c23152 100%); color: white; padding: 20px 24px 16px; }
  .header h1 { font-size: 20px; margin: 0 0 4px; font-weight: 700; }
  .header .sub { font-size: 12px; opacity: 0.8; }
  .content { padding: 16px 24px; max-width: 900px; }
  .stats { display: flex; gap: 12px; margin: -30px 24px 16px; position: relative; z-index: 1; }
  .stat { background: white; padding: 12px 18px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); flex: 1; text-align: center; }
  .stat .n { font-size: 24px; font-weight: bold; color: #e94560; }
  .stat .l { font-size: 11px; color: #999; margin-top: 2px; }
  .filters { margin: 0 0 12px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  select, input { padding: 6px 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; background: white; }
  .btn { background: #e94560; color: white; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .btn:hover { background: #c23152; }
  .list { display: flex; flex-direction: column; gap: 0; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; margin-right: 6px; }
  .tag-eleme { background: #e6f3ff; color: #0066cc; }
  .tag-meituan { background: #fff3e6; color: #cc6600; }
  .tag-上架 { background: #e8f5e9; color: #2e7d32; }
  .tag-下架 { background: #fce4ec; color: #c62828; }
  .tag-改价 { background: #fff3e0; color: #e65100; }
  .tag-改名 { background: #e3f2fd; color: #1565c0; }
  .tag-改规格 { background: #fff3e0; color: #e65100; }
  .tag-创建活动 { background: #f3e5f5; color: #6a1b9a; }
  .tag-修改活动 { background: #f3e5f5; color: #6a1b9a; }
  .tag-关闭活动 { background: #fce4ec; color: #b71c1c; }
  .tag-新建菜品 { background: #e8f5e9; color: #1b5e20; }
  .tag-删除菜品 { background: #fce4ec; color: #b71c1c; }
  .tag-修改菜品 { background: #e3f2fd; color: #1565c0; }
  .tag-回复评价 { background: #e0f7fa; color: #00695c; }
  .tag-创建满减, .tag-修改满减 { background: #fff3e0; color: #e65100; }
  .tag-关闭满减 { background: #fce4ec; color: #b71c1c; }
  .tag-设置神券, .tag-修改神券, .tag-设置折扣, .tag-修改折扣 { background: #f3e5f5; color: #6a1b9a; }
  .tag-关闭神券, .tag-关闭折扣 { background: #fce4ec; color: #b71c1c; }
  .tag-开启推广, .tag-调整推广 { background: #e8eaf6; color: #283593; }
  .tag-关闭推广 { background: #fce4ec; color: #b71c1c; }
  .tag-修改配送费 { background: #fff3e0; color: #e65100; }
  .tag-改图片 { background: #e3f2fd; color: #1565c0; }
  .tag-菜品排序 { background: #f0f0f0; color: #666; }
  .tag-新建套餐, .tag-修改套餐 { background: #e8f5e9; color: #1b5e20; }
  .tag-删除套餐 { background: #fce4ec; color: #b71c1c; }
  .tag-报名拼好饭 { background: #fff3e0; color: #e65100; }
  .tag-设置超抢手 { background: #fff3e0; color: #e65100; }
  .tag-default { background: #f0f0f0; color: #666; }
  .shop-group { background: white; border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
  .shop-header { font-size: 15px; font-weight: 700; color: #222; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
  .date-label { font-size: 12px; color: #999; font-weight: 600; margin: 10px 0 4px; padding-bottom: 3px; border-bottom: 1px solid #f0f0f0; }
  .date-count { font-weight: 400; color: #ccc; }
  .op-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
  .op-time { font-size: 11px; color: #aaa; min-width: 38px; }
  .op-summary { font-size: 13px; color: #222; font-weight: 500; flex: 1; }
  .op-track { display: flex; gap: 4px; margin-left: auto; }
  .track-badge { font-size: 9px; padding: 1px 5px; border-radius: 3px; cursor: default; white-space: nowrap; }
  .track-pending { background: #fff3e0; color: #e65100; }
  .track-done { background: #e8f5e9; color: #2e7d32; cursor: pointer; }
  .track-disabled { background: #f5f5f5; color: #bbb; }
  .track-due { background: #fce4ec; color: #c62828; font-weight: 600; }
  .btn-off { background: none; border: 1px solid #ddd; color: #999; padding: 1px 5px; border-radius: 3px; font-size: 9px; cursor: pointer; }
  .btn-off:hover { background: #fce4ec; color: #c62828; border-color: #c62828; }
  .track-card { background: white; border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
  .track-card .hdr { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
  .track-card .meta { font-size: 11px; color: #888; margin-bottom: 4px; }
  .track-card .compare { display: flex; gap: 12px; font-size: 12px; margin-top: 6px; }
  .track-card .compare .before { color: #999; }
  .track-card .compare .after { color: #2e7d32; font-weight: 600; }
  .track-card .compare .worse { color: #c62828; font-weight: 600; }
  .empty { text-align: center; color: #bbb; padding: 30px; font-size: 13px; }
  .shop-card { background: white; border-radius: 10px; padding: 14px 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); margin-bottom: 8px; }
  .shop-card .name { font-size: 15px; font-weight: 600; color: #222; }
  .shop-card .info { font-size: 12px; color: #888; margin-top: 4px; }
  .food-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px; }
  .food-item { background: white; border-radius: 8px; padding: 10px 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; justify-content: space-between; align-items: center; }
  .food-item .fname { font-size: 13px; color: #333; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .food-item .fprice { font-size: 13px; font-weight: 600; color: #e94560; margin-left: 8px; white-space: nowrap; }
  .food-item .fstatus { font-size: 10px; margin-left: 6px; }
  .food-item .fstatus.on { color: #2e7d32; }
  .food-item .fstatus.off { color: #c62828; }
  .cat-label { font-size: 11px; color: #999; margin: 10px 0 4px; font-weight: 600; }
  .tabs { display: flex; gap: 0; margin-bottom: 16px; border-bottom: 2px solid #eee; }
  .tab { padding: 8px 16px; font-size: 13px; color: #888; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px; }
  .tab.active { color: #e94560; border-bottom-color: #e94560; font-weight: 600; }
</style>
</head><body>
<div class="header">
  <h1>Ops Logger</h1>
  <div class="sub">v2.4.0 &mdash; auto effect tracking</div>
</div>
<div class="stats" id="stats"></div>
<div class="content">
  <div class="tabs">
    <div class="tab active" onclick="switchTab('logs')">操作记录</div>
    <div class="tab" onclick="switchTab('tracking')">效果跟踪 <span id="trackBadge" style="background:#e94560;color:white;padding:1px 6px;border-radius:8px;font-size:10px;display:none">0</span></div>
    <div class="tab" onclick="switchTab('cache')">菜品缓存</div>
  </div>
  <div id="tab-logs">
    <div class="filters">
      <select id="fOperator"><option value="">全部运营</option></select>
      <select id="fAction"><option value="">全部操作</option></select>
      <input id="fSearch" placeholder="搜索..." />
      <button class="btn" onclick="load()">刷新</button>
    </div>
    <div class="list" id="list"></div>
  </div>
  <div id="tab-tracking" style="display:none">
    <div id="trackingSummary"></div>
    <div id="trackingContent"></div>
  </div>
  <div id="tab-cache" style="display:none">
    <div id="cacheContent"></div>
  </div>
</div>
<script>
function esc(s) { return (s||'').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  const pad = n => String(n).padStart(2, '0');
  return (d.getMonth()+1) + '/' + d.getDate() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

const TAG_TYPES = ['上架','下架','改价','改名','改规格','改图片','菜品排序',
  '创建活动','修改活动','关闭活动','创建满减','修改满减','关闭满减',
  '设置神券','修改神券','关闭神券','设置折扣','修改折扣','关闭折扣',
  '开启推广','调整推广','关闭推广','修改配送费',
  '新建菜品','删除菜品','修改菜品','新建套餐','修改套餐','删除套餐',
  '报名拼好饭','设置超抢手','回复评价','修改店铺信息'];
function tagClass(t) {
  return TAG_TYPES.includes(t) ? 'tag-' + t : 'tag-default';
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-logs').style.display = name === 'logs' ? '' : 'none';
  document.getElementById('tab-tracking').style.display = name === 'tracking' ? '' : 'none';
  document.getElementById('tab-cache').style.display = name === 'cache' ? '' : 'none';
  event.target.closest('.tab') ? event.target.closest('.tab').classList.add('active') : event.target.classList.add('active');
  if (name === 'cache') loadCache();
  if (name === 'tracking') loadTracking();
}

async function loadCache() {
  const el = document.getElementById('cacheContent');
  try {
    const [foodRes, summaryRes] = await Promise.all([
      fetch('/api/food_cache'),
      fetch('/api/cache_summary')
    ]);
    const foods = await foodRes.json();
    const summary = await summaryRes.json();

    let html = '';

    // Shop info
    if (summary.shops && summary.shops.length > 0) {
      for (const s of summary.shops) {
        html += '<div class="shop-card"><div class="name">' + esc(s.shop_name) + '</div>' +
          '<div class="info"><span class="tag tag-eleme">' + esc(s.platform) + '</span> ID: ' + esc(s.shop_id) + ' &mdash; updated ' + fmtTime(s.updated_at) + '</div></div>';
      }
    }

    html += '<div class="section-title">food cache <span class="badge">' + summary.food_count + '</span></div>';

    // Group by category (parse specs JSON to get category)
    const byCat = {};
    for (const f of foods) {
      let cat = '';
      try { const d = JSON.parse(f.specs || '{}'); cat = d.category || ''; } catch(e) {}
      if (!cat) cat = 'uncategorized';
      if (!byCat[cat]) byCat[cat] = [];
      // Dedup: only show items where item_key starts with 300 (globalId) to avoid duplicates
      if (f.item_key && f.item_key.startsWith('300')) {
        byCat[cat].push(f);
      }
    }

    // If no 300-prefix items, show all
    const total300 = Object.values(byCat).reduce((s,a) => s + a.length, 0);
    if (total300 === 0) {
      for (const f of foods) {
        let cat = '';
        try { const d = JSON.parse(f.specs || '{}'); cat = d.category || ''; } catch(e) {}
        if (!cat) cat = 'uncategorized';
        if (!byCat[cat]) byCat[cat] = [];
        byCat[cat].push(f);
      }
    }

    for (const [cat, items] of Object.entries(byCat)) {
      html += '<div class="cat-label">' + esc(cat) + ' (' + items.length + ')</div><div class="food-grid">';
      for (const f of items) {
        let status = '', price = f.price;
        try {
          const d = JSON.parse(f.specs || '{}');
          status = d.status || '';
          if (d.specs && d.specs[0] && d.specs[0].price) price = d.specs[0].price;
        } catch(e) {}
        const isOn = status === '上架';
        html += '<div class="food-item">' +
          '<span class="fname">' + esc(f.name) + '</span>' +
          '<span class="fprice">&yen;' + (price||0) + '</span>' +
          '<span class="fstatus ' + (isOn ? 'on' : 'off') + '">' + (isOn ? 'ON' : 'OFF') + '</span>' +
        '</div>';
      }
      html += '</div>';
    }

    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = '<div class="empty">load failed: ' + e.message + '</div>';
  }
}

function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  const now = new Date();
  const m = d.getMonth()+1, day = d.getDate();
  if (d.toDateString() === now.toDateString()) return '今天';
  const y = new Date(now); y.setDate(y.getDate()-1);
  if (d.toDateString() === y.toDateString()) return '昨天';
  return m + '月' + day + '日';
}

function fmtHM(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}

function dateKey(ts) {
  if (!ts) return '';
  return new Date(ts).toISOString().slice(0,10);
}

var _trackingByLogId = {};  // log_id -> [{check_type, status, check_date, id, metrics_before, metrics_after}]

async function loadTrackingIndex() {
  try {
    const [trackRes, summaryRes] = await Promise.all([
      fetch('/api/tracking?status='),
      fetch('/api/tracking/summary')
    ]);
    const tracks = await trackRes.json();
    const summary = await summaryRes.json();
    _trackingByLogId = {};
    for (const t of tracks) {
      if (!_trackingByLogId[t.log_id]) _trackingByLogId[t.log_id] = [];
      _trackingByLogId[t.log_id].push(t);
    }
    const badge = document.getElementById('trackBadge');
    if (summary.due > 0) {
      badge.textContent = summary.due;
      badge.style.display = '';
    } else {
      badge.style.display = 'none';
    }
  } catch(e) {}
}

function trackBadgesHtml(logId) {
  const tracks = _trackingByLogId[logId];
  if (!tracks || tracks.length === 0) return '';
  let html = '<span class="op-track">';
  for (const t of tracks) {
    const label = t.check_type === '3day' ? 'D3' : 'D7';
    let cls = 'track-' + t.status;
    const today = new Date().toISOString().slice(0,10);
    if (t.status === 'pending' && t.check_date <= today) cls = 'track-due';
    if (t.status === 'done') {
      html += '<span class="track-badge ' + cls + '" title="点击查看对比" onclick="showTrackDetail(' + t.id + ')">' + label + ' ✓</span>';
    } else if (t.status === 'disabled') {
      html += '<span class="track-badge ' + cls + '">' + label + ' ×</span>';
    } else {
      html += '<span class="track-badge ' + cls + '">' + label + ' ' + t.check_date.slice(5) + '</span>';
    }
  }
  html += '<button class="btn-off" onclick="disableLog(' + tracks[0].log_id + ')">关</button>';
  html += '</span>';
  return html;
}

async function disableLog(logId) {
  await fetch('/api/tracking/disable_log/' + logId, {method: 'POST'});
  await loadTrackingIndex();
  load();
}

function showTrackDetail(tid) {
  // Find the tracking record
  for (const tracks of Object.values(_trackingByLogId)) {
    for (const t of tracks) {
      if (t.id === tid && t.metrics_before && t.metrics_after) {
        let before, after;
        try { before = JSON.parse(t.metrics_before); } catch(e) { before = {}; }
        try { after = JSON.parse(t.metrics_after); } catch(e) { after = {}; }
        let msg = t.check_type + ' 数据对比:\\n';
        // Compare item-level metrics
        for (const [k, v] of Object.entries(before)) {
          if (k === '_shop') continue;
          const a = after[k] || {};
          if (v.name) msg += v.name + ': ';
          if (v.monthlySales !== undefined && a.monthlySales !== undefined) {
            const diff = a.monthlySales - v.monthlySales;
            msg += '月售 ' + v.monthlySales + ' → ' + a.monthlySales + ' (' + (diff >= 0 ? '+' : '') + diff + ')\\n';
          }
          if (v.price !== undefined && a.price !== undefined && v.price !== a.price) {
            msg += '价格 ¥' + v.price + ' → ¥' + a.price + '\\n';
          }
        }
        alert(msg || '暂无对比数据');
        return;
      }
    }
  }
}

async function load() {
  await loadTrackingIndex();
  const op = document.getElementById('fOperator').value;
  const actFilter = document.getElementById('fAction').value;
  const search = document.getElementById('fSearch').value.toLowerCase();
  const url = '/api/logs?limit=500' + (op ? '&operator=' + op : '');
  const [logsRes, summaryRes] = await Promise.all([fetch(url), fetch('/api/cache_summary')]);
  const logs = await logsRes.json();
  const cacheSummary = await summaryRes.json();

  const operators = [...new Set(logs.map(l => l.operator).filter(Boolean))];
  const actions = [...new Set(logs.map(l => l.action_type).filter(Boolean))];
  const today = new Date().toISOString().slice(0,10);
  const todayCount = logs.filter(l => l.timestamp && l.timestamp.startsWith(today)).length;

  const trackCount = Object.keys(_trackingByLogId).length;
  const pendingTracks = Object.values(_trackingByLogId).flat().filter(t => t.status === 'pending').length;
  document.getElementById('stats').innerHTML =
    '<div class="stat"><div class="n">' + logs.length + '</div><div class="l">总操作</div></div>' +
    '<div class="stat"><div class="n">' + todayCount + '</div><div class="l">今天</div></div>' +
    '<div class="stat"><div class="n">' + pendingTracks + '</div><div class="l">待跟踪</div></div>' +
    '<div class="stat"><div class="n">' + (cacheSummary.shop_count||0) + '</div><div class="l">门店</div></div>';

  const selOp = document.getElementById('fOperator');
  const curOp = selOp.value;
  selOp.innerHTML = '<option value="">全部运营</option>';
  operators.forEach(o => { selOp.innerHTML += '<option value="'+esc(o)+'"'+(o===curOp?' selected':'')+'>'+esc(o)+'</option>'; });

  const selAct = document.getElementById('fAction');
  const curAct = selAct.value;
  selAct.innerHTML = '<option value="">全部操作</option>';
  actions.forEach(a => { selAct.innerHTML += '<option value="'+esc(a)+'"'+(a===curAct?' selected':'')+'>'+esc(a)+'</option>'; });

  let filtered = logs;
  if (actFilter) filtered = filtered.filter(l => l.action_type === actFilter);
  if (search) {
    filtered = filtered.filter(l =>
      (l.change_summary||'').toLowerCase().includes(search) ||
      (l.item_name||'').toLowerCase().includes(search) ||
      (l.shop_name||'').toLowerCase().includes(search) ||
      (l.operator||'').toLowerCase().includes(search)
    );
  }

  if (filtered.length === 0) {
    document.getElementById('list').innerHTML = '<div class="empty">暂无操作记录</div>';
    return;
  }

  // Group: shop+platform → date → logs
  const grouped = {};
  for (const l of filtered) {
    const pname = l.platform === 'eleme' ? '饿了么' : l.platform === 'meituan' ? '美团' : l.platform || '';
    const shopKey = (l.shop_name || l.shop_id || '未知门店') + '|' + pname;
    const dk = dateKey(l.timestamp);
    if (!grouped[shopKey]) grouped[shopKey] = {};
    if (!grouped[shopKey][dk]) grouped[shopKey][dk] = [];
    grouped[shopKey][dk].push(l);
  }

  let html = '';
  for (const [shopKey, dates] of Object.entries(grouped)) {
    const [shopName, platform] = shopKey.split('|');
    const ptag = platform === '饿了么' ? 'tag-eleme' : platform === '美团' ? 'tag-meituan' : '';
    html += '<div class="shop-group">' +
      '<div class="shop-header">' + esc(shopName) +
        (platform ? ' <span class="tag ' + ptag + '">' + platform + '</span>' : '') +
      '</div>';

    const sortedDates = Object.keys(dates).sort().reverse();
    for (const dk of sortedDates) {
      const dayLogs = dates[dk];
      html += '<div class="date-label">' + fmtDate(dayLogs[0].timestamp) + ' <span class="date-count">' + dayLogs.length + '条</span></div>';
      for (const l of dayLogs) {
        const sm = l.change_summary || l.action_detail || l.action_type || l.api_method;
        html += '<div class="op-row">' +
          '<span class="op-time">' + fmtHM(l.timestamp) + '</span>' +
          '<span class="tag ' + tagClass(l.action_type) + '">' + esc(l.action_type || '操作') + '</span>' +
          '<span class="op-summary">' + esc(sm) + '</span>' +
          trackBadgesHtml(l.id) +
        '</div>';
      }
    }
    html += '</div>';
  }

  document.getElementById('list').innerHTML = html;
}
async function loadTracking() {
  const [summaryRes, dueRes, doneRes] = await Promise.all([
    fetch('/api/tracking/summary'),
    fetch('/api/tracking/due'),
    fetch('/api/tracking?status=done')
  ]);
  const summary = await summaryRes.json();
  const due = await dueRes.json();
  const done = await doneRes.json();

  let html = '<div style="display:flex;gap:10px;margin-bottom:14px">';
  html += '<div class="stat" style="flex:1"><div class="n">' + summary.pending + '</div><div class="l">待检查</div></div>';
  html += '<div class="stat" style="flex:1"><div class="n" style="color:#c62828">' + summary.due + '</div><div class="l">今日到期</div></div>';
  html += '<div class="stat" style="flex:1"><div class="n" style="color:#2e7d32">' + summary.done + '</div><div class="l">已完成</div></div>';
  html += '<div class="stat" style="flex:1"><div class="n" style="color:#999">' + summary.disabled + '</div><div class="l">已关闭</div></div>';
  html += '</div>';
  document.getElementById('trackingSummary').innerHTML = html;

  let content = '';

  // Due items
  if (due.length > 0) {
    content += '<div style="font-size:13px;font-weight:600;color:#c62828;margin-bottom:8px">到期待检查 (' + due.length + ')</div>';
    for (const d of due) {
      content += '<div class="track-card">' +
        '<div class="hdr"><span class="tag ' + tagClass(d.log_action_type || d.action_type) + '">' + esc(d.log_action_type || d.action_type) + '</span> ' +
        esc(d.change_summary || '') + '</div>' +
        '<div class="meta">' + esc(d.shop_name||'') + ' · ' + d.check_type + ' · 到期 ' + d.check_date + '</div>' +
      '</div>';
    }
  }

  // Upcoming
  if (summary.upcoming && summary.upcoming.length > 0) {
    content += '<div style="font-size:13px;font-weight:600;color:#e65100;margin:12px 0 8px">即将到期</div>';
    for (const u of summary.upcoming) {
      content += '<div class="track-card">' +
        '<div class="hdr"><span class="tag ' + tagClass(u.action_type) + '">' + esc(u.action_type) + '</span> ' +
        esc(u.change_summary || '') + '</div>' +
        '<div class="meta">' + esc(u.shop_name||'') + ' · ' + u.check_type + ' · ' + u.check_date + '</div>' +
      '</div>';
    }
  }

  // Done items (recent)
  if (done.length > 0) {
    content += '<div style="font-size:13px;font-weight:600;color:#2e7d32;margin:12px 0 8px">已完成 (最近)</div>';
    for (const d of done.slice(0, 20)) {
      let compareHtml = '';
      try {
        const before = JSON.parse(d.metrics_before || '{}');
        const after = JSON.parse(d.metrics_after || '{}');
        for (const [k, v] of Object.entries(before)) {
          if (k === '_shop') continue;
          const a = after[k] || {};
          if (v.monthlySales !== undefined && a.monthlySales !== undefined) {
            const diff = a.monthlySales - v.monthlySales;
            const cls = diff >= 0 ? 'after' : 'worse';
            compareHtml += '<div class="compare"><span class="before">' + esc(v.name||k) + ' 月售: ' + v.monthlySales + '</span> → <span class="' + cls + '">' + a.monthlySales + ' (' + (diff>=0?'+':'') + diff + ')</span></div>';
          }
        }
      } catch(e) {}

      content += '<div class="track-card">' +
        '<div class="hdr"><span class="tag ' + tagClass(d.action_type) + '">' + esc(d.action_type) + '</span> ' + d.check_type + '</div>' +
        '<div class="meta">checked ' + (d.checked_at||'').slice(0,10) + '</div>' +
        compareHtml +
      '</div>';
    }
  }

  if (!content) content = '<div class="empty">暂无跟踪记录。操作后台会自动创建T+3和T+7的效果跟踪。</div>';
  document.getElementById('trackingContent').innerHTML = content;
}

load();
setInterval(load, 15000);
</script>
</body></html>"""

@app.route("/")
def dashboard():
    return render_template_string(PAGE_HTML)

_GITEE_RAW = "https://gitee.com/sethgeshiheng/store-monitor/raw/feature/watch-mode/ops-logger"
_remote_version_cache = {"version": None, "ts": 0}

@app.route("/api/extension/version")
def extension_version():
    """从Gitee读最新版本号（缓存5分钟），确保运营拿到的是线上最新版"""
    import time as _tv
    now = _tv.time()
    if _remote_version_cache["version"] and (now - _remote_version_cache["ts"]) < 300:
        return jsonify({"version": _remote_version_cache["version"]})
    # 从Gitee读manifest.json
    try:
        session = http_requests.Session()
        session.trust_env = False
        resp = session.get(f"{_GITEE_RAW}/extension/manifest.json", timeout=5)
        if resp.ok:
            v = resp.json().get("version", "0")
            _remote_version_cache["version"] = v
            _remote_version_cache["ts"] = now
            return jsonify({"version": v})
    except Exception as e:
        print(f"[version] Gitee查询失败: {e}")
    # 降级：读本地
    base = os.path.dirname(__file__)
    try:
        with open(os.path.join(base, "extension", "manifest.json")) as f:
            v = json.load(f).get("version", "0")
        return jsonify({"version": v})
    except:
        return jsonify({"version": "0"})

@app.route("/api/extension/download")
def extension_download():
    """重定向到Gitee最新zip下载。不降级到本地打包（避免发出老版本）"""
    from flask import redirect
    # 先用缓存的版本号（避免重复请求Gitee）
    ver = _remote_version_cache.get("version")
    if ver:
        return redirect(f"{_GITEE_RAW}/ops-logger-v{ver}.zip")
    # 没缓存就实时查
    try:
        session = http_requests.Session()
        session.trust_env = False
        resp = session.get(f"{_GITEE_RAW}/extension/manifest.json", timeout=5)
        if resp.ok:
            ver = resp.json().get("version", "0")
            _remote_version_cache["version"] = ver
            import time as _tv
            _remote_version_cache["ts"] = _tv.time()
            return redirect(f"{_GITEE_RAW}/ops-logger-v{ver}.zip")
    except Exception as e:
        print(f"[download] Gitee查询失败: {e}")
    return jsonify({"error": "无法获取最新版本，请稍后重试"}), 503

@app.route("/download/<path:filename>")
def download_file(filename):
    from flask import send_from_directory
    return send_from_directory(os.path.dirname(__file__), filename)

@app.route("/health")
def health():
    """增强版健康检查：返回各组件状态"""
    import subprocess as _hc_sp

    # 检查headless Chrome
    headless_ok = False
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:9333/json/version")
        req.add_header("Host", "localhost")
        with urllib.request.urlopen(req, timeout=2) as r:
            headless_ok = r.status == 200
    except Exception:
        pass

    # 最近巡检结果
    last_patrol = None
    last_patrol_status = None
    try:
        pr = _load_patrol_result()
        if pr:
            last_patrol = pr.get("ts")
            last_patrol_status = "ok" if pr.get("issues") is not None else "unknown"
    except Exception:
        pass

    # 最近错误
    last_error = None
    err_file = os.path.join(WORKSPACE, "ops-logger", "patrol_errors.json")
    try:
        if os.path.exists(err_file):
            with open(err_file) as f:
                errs = json.load(f)
            if errs:
                last_error = errs[-1]
    except Exception:
        pass

    return jsonify({
        "status": "ok",
        "time": cn_now().isoformat(),
        "headless_chrome": headless_ok,
        "last_patrol": last_patrol,
        "last_patrol_status": last_patrol_status,
        "last_error": last_error,
        "patrol_state": _patrol_state.get("state", "idle"),
    })


@app.route("/api/errors")
def api_errors():
    """返回最近的巡检错误日志"""
    limit = request.args.get("limit", 50, type=int)
    err_file = os.path.join(WORKSPACE, "ops-logger", "patrol_errors.json")
    try:
        if os.path.exists(err_file):
            with open(err_file) as f:
                errs = json.load(f)
            return jsonify(errs[-limit:])
    except Exception:
        pass
    return jsonify([])

# ========== Patrol APIs (日报 + 预警) ==========
# 读 patrol_result.json（run_all_fast.py巡检结束后写入）

PATROL_RESULT = os.path.join(os.path.dirname(__file__), "patrol_result.json")

def _load_patrol_result():
    """读取最近一次巡检结果"""
    if not os.path.exists(PATROL_RESULT):
        return None
    try:
        with open(PATROL_RESULT, encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

@app.route("/api/daily")
def daily_report():
    """日报API — 巡检中返回增量进度，否则读patrol_result.json"""
    # 巡检中：从内存中的增量进度返回
    with _patrol_lock:
        is_running = _patrol_state["state"] == "running"
        progress = dict(_patrol_progress) if is_running else None
    if is_running and progress and progress.get("done", 0) > 0:
        data = {
            "ts": progress["ts"],
            "brands": progress["done"],
            "duration": 0,
            "issues": progress["issues"],
            "all_stores": progress["all_stores"],
            "brand_stores": progress["brand_stores"],
            "_running": True,
            "_done": progress["done"],
            "_total": progress["total"],
        }
    else:
        data = _load_patrol_result()
        # 检查结果是否属于当前运营（防止切换运营后看到旧数据）
        if data:
            result_op = data.get("operator", "")
            current_op = load_config().get("operator", "")
            if result_op and current_op and result_op != current_op:
                data = None
    if not data:
        return jsonify({"ts": None, "stores": []})

    # 只取HH:MM部分（去掉日期前缀）
    ts_raw = data.get("ts", "")
    ts = ts_raw.split(" ")[-1] if ts_raw and " " in ts_raw else ts_raw
    issues = data.get("issues", {})

    stores = []
    for store_name, items in issues.items():
        store = {"store": store_name, "platforms": []}
        # 按平台分组
        by_platform = {}
        for item in items:
            p = item.get("platform", "")
            if p not in by_platform:
                by_platform[p] = {"platform": p, "bad_review_count": 0, "expiring_count": 0,
                                  "promo_balance": None, "promo_daily_spend": None,
                                  "has_auth_issue": False, "bad_reviews": [], "activities": [],
                                  "notice_count": 0, "notices": []}
            pd = by_platform[p]
            t = item.get("type", "")
            if t == "bad_review":
                pd["bad_review_count"] = len(item.get("details", []))
                for d in item.get("details", []):
                    if isinstance(d, dict):
                        pd["bad_reviews"].append({"stars": d.get("stars", ""), "comment": d.get("comment", ""), "date": d.get("time", "")})
            elif t == "expiring":
                pd["expiring_count"] = len(item.get("details", []))
                for d in item.get("details", []):
                    if isinstance(d, dict):
                        pd["activities"].append({"name": d.get("name", ""), "days_left": d.get("days", 0)})
            elif t == "promo":
                msg = item.get("msg", "")
                # 解析 "推广余额不足：123元/日消费45元"
                import re as _re
                m = _re.search(r"(\d+\.?\d*)元.*?(\d+\.?\d*)元", msg)
                if m:
                    pd["promo_balance"] = float(m.group(1))
                    pd["promo_daily_spend"] = float(m.group(2))
            elif t == "auth":
                pd["has_auth_issue"] = True
            elif t == "notice":
                details = item.get("details", [])
                pd["notice_count"] = len(details)
                for d in details[:5]:
                    if isinstance(d, dict):
                        pd["notices"].append({"title": d.get("title", ""), "content": d.get("content", "")[:60], "time": d.get("time", "")})
            elif t == "error":
                pd.setdefault("errors", [])
                pd["errors"].append(item.get("msg", ""))
        store["platforms"] = list(by_platform.values())
        stores.append(store)

    # 把没问题的店也加进来（从all_stores里补）
    all_stores = data.get("all_stores", {})
    existing = {s["store"] for s in stores}
    for store_name, platforms in all_stores.items():
        if store_name not in existing:
            store = {"store": store_name, "platforms": []}
            for p in platforms:
                store["platforms"].append({"platform": p, "bad_review_count": 0, "expiring_count": 0,
                                           "promo_balance": None, "promo_daily_spend": None,
                                           "has_auth_issue": False, "bad_reviews": [], "activities": [],
                                           "notice_count": 0, "notices": []})
            stores.append(store)

    # 按品牌分组
    brand_stores_map = data.get("brand_stores", {})
    store_map = {s["store"]: s for s in stores}
    brands_grouped = []
    assigned = set()
    for brand_name, store_names in brand_stores_map.items():
        brand_obj = {"brand": brand_name, "stores": []}
        for sn in store_names:
            if sn in store_map:
                brand_obj["stores"].append(store_map[sn])
                assigned.add(sn)
        if brand_obj["stores"]:
            brands_grouped.append(brand_obj)
    # 没有归到品牌的店
    orphans = [s for s in stores if s["store"] not in assigned]
    if orphans:
        brands_grouped.append({"brand": "其他", "stores": orphans})

    resp = {"ts": ts, "stores": stores, "brands_grouped": brands_grouped,
            "brands": data.get("brands", 0), "duration": data.get("duration", 0)}
    # 巡检中时附带进度信息
    if data.get("_running"):
        resp["_running"] = True
        resp["_done"] = data.get("_done", 0)
        resp["_total"] = data.get("_total", 0)
    return jsonify(resp)


@app.route("/api/alerts")
def alerts():
    """预警API — 从patrol_result.json + 操作追踪生成预警"""
    result = []

    # 1. 从巡检结果找预警
    data = _load_patrol_result()
    if data:
        ts = data.get("ts", "")
        for store_name, items in data.get("issues", {}).items():
            for item in items:
                t = item.get("type", "")
                platform = item.get("platform", "")
                if t == "bad_review":
                    details = item.get("details", [])
                    # 每条差评单独一条预警，用差评原始时间
                    for d in details[:5]:
                        if isinstance(d, dict):
                            event_time = d.get("time", "")
                            result.append({"type": "bad_review", "level": "red", "store": store_name,
                                           "platform": platform,
                                           "msg": f'{d.get("stars","")}星差评',
                                           "detail": (d.get("comment",""))[:50],
                                           "event_time": event_time, "patrol_ts": ts})
                elif t == "expiring":
                    for d in item.get("details", []):
                        if isinstance(d, dict):
                            days = d.get("days", 99)
                            level = "red" if days <= 1 else "yellow"
                            result.append({"type": "expiring", "level": level, "store": store_name,
                                           "platform": platform, "msg": f'{d.get("name","")} {days}天后到期', "detail": "",
                                           "event_time": "", "patrol_ts": ts})
                elif t == "promo":
                    result.append({"type": "promo", "level": "yellow", "store": store_name,
                                   "platform": platform, "msg": item.get("msg", ""), "detail": "",
                                   "event_time": "", "patrol_ts": ts})
                elif t == "auth":
                    result.append({"type": "auth", "level": "red", "store": store_name,
                                   "platform": platform, "msg": "授权异常", "detail": "",
                                   "event_time": "", "patrol_ts": ts})
                elif t == "error":
                    result.append({"type": "error", "level": "yellow", "store": store_name,
                                   "platform": platform, "msg": item.get("msg", ""), "detail": "",
                                   "event_time": "", "patrol_ts": ts})
                elif t == "notice":
                    details = item.get("details", [])
                    important = [d for d in details if isinstance(d, dict) and "配送范围" not in d.get("title", "")]
                    # 每条通知单独一条预警，用通知原始时间
                    for d in important[:5]:
                        event_time = d.get("time", "")
                        result.append({"type": "notice", "level": "blue", "store": store_name,
                                       "platform": platform, "msg": d.get("title", "")[:30], "detail": d.get("content", "")[:50],
                                       "event_time": event_time, "patrol_ts": ts})

    # 2. 从操作追踪找到期TODO
    ops_conn = get_db()
    today = cn_now().date().isoformat()
    due_tracks = ops_conn.execute("""
        SELECT ct.id, ct.action_type, ct.check_type, ct.check_date, ct.shop_id, ct.platform,
               l.change_summary, l.shop_name, l.timestamp as op_ts
        FROM change_tracking ct
        LEFT JOIN logs l ON ct.log_id = l.id
        WHERE ct.status = 'pending' AND ct.check_date <= ?
        ORDER BY ct.check_date
    """, (today,)).fetchall()
    for t in due_tracks:
        result.append({
            "type": "tracking_due",
            "level": "blue",
            "store": t["shop_name"] or t["shop_id"] or "",
            "platform": t["platform"] or "",
            "msg": f'{t["action_type"]} {t["check_type"]}到期',
            "detail": t["change_summary"] or "",
            "event_time": t["op_ts"] or "",
            "patrol_ts": "",
        })
    ops_conn.close()

    # 按事件时间倒序（最新的在前），同时间按level排
    level_order = {"red": 0, "yellow": 1, "blue": 2}
    result.sort(key=lambda x: (-(x.get("event_time") or x.get("patrol_ts") or "0").replace("-","").replace(":","").replace(" ","").ljust(14,"0")[:14].isdigit(),
                                x.get("event_time") or x.get("patrol_ts") or "0"), reverse=True)
    # 简化：先按event_time倒序
    result.sort(key=lambda x: x.get("event_time") or x.get("patrol_ts") or "", reverse=True)

    return jsonify(result)


@app.route("/api/store-cookies")
def store_cookies():
    """返回指定店铺的cookie快照，供扩展点击预警时切店"""
    store = request.args.get("store", "")
    platform = request.args.get("platform", "")
    if not store:
        return jsonify({"error": "missing store"}), 400
    snap_file = os.path.join(WORKSPACE, "ops-logger", "_cookie_snapshots.json")
    if not os.path.exists(snap_file):
        return jsonify({"error": "no snapshots"}), 404
    try:
        with open(snap_file) as f:
            snaps = json.load(f)
    except:
        return jsonify({"error": "bad snapshot file"}), 500
    # 匹配店铺：精确匹配 > 包含匹配
    matched = None
    for s in snaps:
        if s.get("store") == store and (not platform or s.get("platform") == platform):
            matched = s
            break
    if not matched:
        for s in snaps:
            if store in (s.get("store") or "") and (not platform or s.get("platform") == platform):
                matched = s
                break
    if not matched:
        return jsonify({"error": "store not found"}), 404
    # 只返回浏览器需要的cookie（过滤掉httpOnly等敏感标记由扩展自己处理）
    return jsonify({
        "store": matched.get("store"),
        "platform": matched.get("platform"),
        "cookies": matched.get("cookies", [])
    })


@app.route("/api/tracking/feedback", methods=["POST"])
def tracking_feedback():
    """运营对追踪结果的反馈: 有效/无效/再观察"""
    data = request.get_json()
    tracking_id = data.get("id")
    feedback = data.get("feedback")  # "effective" / "ineffective" / "observe"
    if not tracking_id or not feedback:
        return jsonify({"error": "missing id or feedback"}), 400

    conn = get_db()
    conn.execute(
        "UPDATE change_tracking SET status=?, checked_at=? WHERE id=?",
        (feedback, cn_now().isoformat(), tracking_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

def _auto_collect_due():
    """Background thread: every hour, check for due tracking tasks and collect data."""
    import threading, time, subprocess
    def _loop():
        while True:
            time.sleep(3600)  # 1 hour
            try:
                today = cn_now().date().isoformat()
                conn = get_db()
                due = conn.execute(
                    "SELECT COUNT(*) as c FROM change_tracking WHERE status='pending' AND check_date<=?",
                    (today,)
                ).fetchone()["c"]
                conn.close()
                if due > 0:
                    print(f"[auto-collect] {due} due tasks, running collect_tracking.py...")
                    subprocess.run(
                        [PYTHON, "collect_tracking.py"],
                        cwd=os.path.dirname(os.path.abspath(__file__)),
                        timeout=120
                    )
            except Exception as e:
                print(f"[auto-collect] error: {e}")
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


def _auto_backup():
    """Backup ops_logs.db daily, keep last 7 backups."""
    import threading, time, shutil
    BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    def _do_backup():
        today = cn_now().strftime("%Y%m%d")
        dst = os.path.join(BACKUP_DIR, f"ops_logs_{today}.db")
        if os.path.exists(dst):
            return  # already backed up today
        try:
            src = sqlite3.connect(DB_PATH)
            bak = sqlite3.connect(dst)
            src.backup(bak)
            bak.close()
            src.close()
            print(f"[backup] saved {dst}")
        except Exception as e:
            try:
                shutil.copy2(DB_PATH, dst)
                print(f"[backup] file copy saved {dst}")
            except Exception as e2:
                print(f"[backup] error: {e2}")
        # cleanup: keep last 7
        try:
            files = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith("ops_logs_") and f.endswith(".db")])
            for old in files[:-7]:
                os.remove(os.path.join(BACKUP_DIR, old))
        except:
            pass
    def _loop():
        _do_backup()  # backup on startup
        while True:
            time.sleep(86400)  # 24h
            _do_backup()
    t = threading.Thread(target=_loop, daemon=True)
    t.start()

## ========== Operator Stores (PA sync) ==========

@app.route("/api/operator/stores")
def api_operator_stores():
    """查运营名下的品牌和店铺（从PA数据库实时查）"""
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "need name param"}), 400
    try:
        import pymysql
        pa = pymysql.connect(
            host="rm-uf6e0001sq5g9foel.mysql.rds.aliyuncs.com",
            port=3306, user="pa_ai_read",
            password="HV)b2ZNxd_)(SLtBmLg--2rV",
            database="inca-saas07",
            charset="utf8mb4", connect_timeout=10
        )
        with pa.cursor() as cur:
            cur.execute("""
                SELECT s.name AS brand_name, s.id AS subscriber_id,
                       ts.name AS shop_name, ts.id AS shop_id, ts.platform
                FROM subscribers s
                JOIN contracts c ON c.subscriber_id = s.id
                    AND c.start_at <= NOW() AND c.end_at >= NOW()
                JOIN takeaway_shops ts ON ts.subscriber_id = s.id
                WHERE s.operator = %s
                ORDER BY s.name, ts.name
            """, (name,))
            rows = cur.fetchall()
        pa.close()
    except Exception as e:
        return jsonify({"error": str(e), "hint": "VPN可能没连"}), 500

    if not rows:
        # 模糊搜索看看有没有近似名字
        try:
            pa2 = pymysql.connect(
                host="rm-uf6e0001sq5g9foel.mysql.rds.aliyuncs.com",
                port=3306, user="pa_ai_read",
                password="HV)b2ZNxd_)(SLtBmLg--2rV",
                database="inca-saas07",
                charset="utf8mb4", connect_timeout=10
            )
            with pa2.cursor() as cur2:
                cur2.execute("SELECT DISTINCT operator FROM subscribers WHERE operator LIKE %s LIMIT 10", (f"%{name}%",))
                similar = [r[0] for r in cur2.fetchall()]
            pa2.close()
            return jsonify({"operator": name, "brands": [], "total_shops": 0, "similar": similar})
        except:
            pass
        return jsonify({"operator": name, "brands": [], "total_shops": 0})

    brands = {}
    for brand_name, sub_id, shop_name, shop_id, platform in rows:
        if brand_name not in brands:
            brands[brand_name] = {"subscriber_id": sub_id, "shops": []}
        brands[brand_name]["shops"].append({
            "shop_name": shop_name, "shop_id": shop_id, "platform": platform
        })

    brand_list = []
    for bname, bdata in brands.items():
        brand_list.append({
            "brand_name": bname,
            "subscriber_id": bdata["subscriber_id"],
            "shops": bdata["shops"]
        })

    return jsonify({
        "operator": name,
        "brands": brand_list,
        "total_brands": len(brand_list),
        "total_shops": len(rows)
    })

@app.route("/api/operator/list")
def api_operator_list():
    """列出所有有在约合同的运营"""
    try:
        import pymysql
        pa = pymysql.connect(
            host="rm-uf6e0001sq5g9foel.mysql.rds.aliyuncs.com",
            port=3306, user="pa_ai_read",
            password="HV)b2ZNxd_)(SLtBmLg--2rV",
            database="inca-saas07",
            charset="utf8mb4", connect_timeout=10
        )
        with pa.cursor() as cur:
            cur.execute("""
                SELECT s.operator, COUNT(DISTINCT s.id) as brand_count, COUNT(ts.id) as shop_count
                FROM subscribers s
                JOIN contracts c ON c.subscriber_id = s.id
                    AND c.start_at <= NOW() AND c.end_at >= NOW()
                JOIN takeaway_shops ts ON ts.subscriber_id = s.id
                WHERE s.operator IS NOT NULL AND s.operator != ''
                GROUP BY s.operator
                ORDER BY s.operator
            """)
            rows = [{"name": r[0], "brands": r[1], "shops": r[2]} for r in cur.fetchall()]
        pa.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========== Agent Status + Patrol (v4.0 直执行) ==========

WORKSPACE = os.path.dirname(os.path.dirname(__file__))  # ops-logger/../ = store-monitor/
_patrol_state = {"state": "idle", "message": "", "pid": None, "started_at": None}
_patrol_lock = threading.Lock()
_task_queue = []  # 最多1个排队任务: [{"brands": [...], "label": "...", "operator": "...", ...}]
_patrol_progress = {"issues": {}, "all_stores": {}, "brand_stores": {}, "done": 0, "total": 0, "ts": ""}  # 增量巡检进度
_PATROL_MAX_SEC = 600  # 单次巡检最长10分钟，超时判定死亡
_last_patrol_ts = None   # 最近一次巡检完成时间
_last_alert_ts = None    # 最近一次预警完成时间


def _check_patrol_alive():
    """检查当前巡检是否还活着，卡死的自动清理。返回True=确实在跑"""
    import time as _t
    with _patrol_lock:
        if _patrol_state["state"] != "running":
            return False
        pid = _patrol_state.get("pid")
        started = _patrol_state.get("started_at")
    # pid为空但state=running：进程还没启动就挂了，或pid没赋上
    # 给30秒宽限期等pid赋值，超过30秒还没pid就判定为死
    if not pid:
        if started and (_t.time() - started) > 30:
            with _patrol_lock:
                _patrol_state["state"] = "error"
                _patrol_state["message"] = "巡检进程未启动（无pid）"
                _patrol_state["pid"] = None
                _patrol_state["started_at"] = None
            print("[patrol] state=running但pid为空超30秒，自动清理")
            return False
        return True  # 还在宽限期，等一等
    # 检查进程是否存在
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        with _patrol_lock:
            _patrol_state["state"] = "error"
            _patrol_state["message"] = "巡检进程异常退出"
            _patrol_state["pid"] = None
            _patrol_state["started_at"] = None
        _cleanup_headless()
        print("[patrol] 进程已死，自动清理")
        return False
    # 检查是否超时
    if started and (_t.time() - started) > _PATROL_MAX_SEC:
        try:
            os.kill(pid, 9)
        except Exception:
            pass
        _cleanup_headless()
        with _patrol_lock:
            _patrol_state["state"] = "error"
            _patrol_state["message"] = f"巡检超时({_PATROL_MAX_SEC}秒)，已自动终止"
            _patrol_state["pid"] = None
            _patrol_state["started_at"] = None
        print(f"[patrol] 超时{_PATROL_MAX_SEC}s，强制终止")
        return False
    return True


def _drain_patrol_queue():
    """从队列取任务跑，由_run_patrol_task完成后调用"""
    with _patrol_lock:
        if not _task_queue:
            return
        if _patrol_state["state"] == "running":
            return  # 还在跑，不取
        task = _task_queue.pop(0)
    print(f"[patrol] 队列取出: {task['label']}（剩余{len(_task_queue)}个）")
    _start_patrol_task(task["brands"], task["operator"], task["label"], script=task.get("script"), extra_args=task.get("extra_args"))


def _start_patrol_task(brands, operator, label="巡检", script=None, extra_args=None):
    """启动一个巡检任务（内部统一入口）"""
    def _run():
        _run_patrol_task(brands, operator, label, script=script, extra_args=extra_args)
        _drain_patrol_queue()
    threading.Thread(target=_run, daemon=True).start()


def _run_patrol_task(brands, operator, label="巡检", script=None, extra_args=None):
    """实际执行巡检的函数"""
    import time as _t
    with _patrol_lock:
        _patrol_state["state"] = "running"
        _patrol_state["message"] = f"{label} {', '.join(brands[:3])}..."
        _patrol_state["log"] = ""
        _patrol_state["pid"] = None
        _patrol_state["started_at"] = _t.time()
        # 清空增量进度
        _patrol_progress["issues"] = {}
        _patrol_progress["all_stores"] = {}
        _patrol_progress["brand_stores"] = {}
        _patrol_progress["done"] = 0
        _patrol_progress["total"] = len(brands)
        _patrol_progress["ts"] = cn_now().strftime("%Y-%m-%d %H:%M")

    if script is None:
        script = os.path.join(WORKSPACE, "run_all_fast.py")
    cmd = [PYTHON, script, "--headless"]
    # --operator 只有 run_all_fast.py 支持
    if "run_all_fast" in script:
        cmd += ["--operator", operator]
    cmd += (extra_args or []) + brands
    timeout_sec = len(brands) * 60 + 120
    print(f"[patrol] 启动: {label}, operator={operator}, brands={brands}, timeout={timeout_sec}s")
    try:
        proc = subprocess.Popen(cmd, cwd=WORKSPACE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        with _patrol_lock:
            _patrol_state["pid"] = proc.pid
        output_lines = []
        for line in proc.stdout:
            text = line.decode("utf-8", errors="replace").rstrip()
            output_lines.append(text)
            print(f"[patrol] {text}")
            with _patrol_lock:
                _patrol_state["message"] = text[:100] or _patrol_state["message"]
                _patrol_state["log"] = "\n".join(output_lines[-50:])
        proc.wait(timeout=timeout_sec)
        with _patrol_lock:
            if proc.returncode == 0:
                _patrol_state["state"] = "done"
                _patrol_state["message"] = f"{label}完成"
                # 记录最近完成时间
                global _last_patrol_ts, _last_alert_ts
                _now_str = cn_now().strftime("%H:%M")
                if "预警" in label:
                    _last_alert_ts = _now_str
                else:
                    _last_patrol_ts = _now_str
                # 首次手动巡检成功后，自动开启定时巡检+预警
                try:
                    _cfg = load_config()
                    if not _cfg.get("patrol_enabled"):
                        _cfg["patrol_enabled"] = True
                        _cfg["alert_enabled"] = True
                        if not _cfg.get("patrol_time"):
                            _cfg["patrol_time"] = "10:00"
                        if not _cfg.get("alert_interval"):
                            _cfg["alert_interval"] = 10
                        if operator and not _cfg.get("operator"):
                            _cfg["operator"] = operator
                        save_config(_cfg)
                        print(f"[patrol] 首次巡检成功，已自动开启定时巡检+预警")
                except Exception as _e:
                    print(f"[patrol] 自动开启失败: {_e}")
            else:
                _cleanup_headless()
                last_step = _get_last_debug_step()
                _patrol_state["state"] = "error"
                _patrol_state["message"] = f"{label}异常: {last_step}" if last_step else f"{label}异常(code={proc.returncode})"
            _patrol_state["pid"] = None
            _patrol_state["started_at"] = None
        print(f"[patrol] {label}结束: code={proc.returncode}")
        _report_logs("patrol")
        if proc.returncode != 0:
            _report_logs("error")
    except subprocess.TimeoutExpired:
        proc.kill()
        _cleanup_headless()
        last_step = _get_last_debug_step()
        with _patrol_lock:
            _patrol_state["state"] = "error"
            _patrol_state["message"] = f"{label}超时({timeout_sec}秒)，卡在: {last_step}"
            _patrol_state["pid"] = None
            _patrol_state["started_at"] = None
        print(f"[patrol] {label}超时({timeout_sec}s)")
        _report_logs("error")
    except Exception as e:
        _cleanup_headless()
        with _patrol_lock:
            _patrol_state["state"] = "error"
            _patrol_state["message"] = str(e)[:100]
            _patrol_state["pid"] = None
            _patrol_state["started_at"] = None
        print(f"[patrol] {label}异常: {e}")
        _report_logs("error")


def _enqueue_patrol(brands, operator, label="巡检", script=None, extra_args=None):
    """统一入口：空闲直接跑，在跑就排队（最多排1个，多了替换）"""
    # 先检查当前巡检是否还活着
    if _patrol_state["state"] == "running":
        _check_patrol_alive()

    with _patrol_lock:
        if _patrol_state["state"] == "running":
            # 已有排队任务就替换（只保留最新的）
            task = {"brands": brands, "operator": operator, "label": label, "script": script, "extra_args": extra_args}
            if _task_queue:
                old = _task_queue[0]
                print(f"[patrol] 替换排队任务: {old['label']} -> {label}")
                _task_queue[0] = task
            else:
                _task_queue.append(task)
                print(f"[patrol] {label}排队等待（当前在跑）")
            return "queued"
    # 空闲，直接跑
    _start_patrol_task(brands, operator, label, script=script, extra_args=extra_args)
    return "started"


def _cleanup_headless():
    """巡检失败/超时后清理headless Chrome进程"""
    try:
        sys.path.insert(0, WORKSPACE)
        from browser import kill_headless
        kill_headless()
        print("[patrol] 已清理headless Chrome")
    except Exception as e:
        print(f"[patrol] 清理headless失败: {e}")


def _get_last_debug_step():
    """读patrol_debug.json的最后一条日志，用于错误提示"""
    try:
        debug_file = os.path.join(os.path.dirname(__file__), "patrol_debug.json")
        if not os.path.exists(debug_file):
            return ""
        with open(debug_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        logs = data.get("log", [])
        if not logs:
            return ""
        last = logs[-1]
        return f"[{last.get('phase','')}] {last.get('msg','')}"
    except Exception:
        return ""

@app.route("/api/agent/status")
def api_agent_status():
    """检查agent就绪状态 + 巡检进程状态"""
    has_run_fast = os.path.exists(os.path.join(WORKSPACE, "run_all_fast.py"))
    with _patrol_lock:
        patrol = dict(_patrol_state)
    # 检查进程是否还活着
    if patrol["state"] == "running" and patrol.get("pid"):
        try:
            os.kill(patrol["pid"], 0)
        except (OSError, ProcessLookupError):
            with _patrol_lock:
                _patrol_state["state"] = "done"
                _patrol_state["message"] = "巡检完成"
                _patrol_state["pid"] = None
            patrol = dict(_patrol_state)
    # 不把log塞进轮询响应，太大
    patrol_clean = {k: v for k, v in patrol.items() if k != "log"}
    # 巡检中时附带最后一步debug信息
    if patrol_clean.get("state") == "running":
        patrol_clean["last_step"] = _get_last_debug_step()
    # 出错时也附带最后一步
    if patrol_clean.get("state") == "error":
        patrol_clean["last_step"] = _get_last_debug_step()
    # 检查headless profile是否存在（粗判登录态）
    headless_profile = os.path.join("/tmp", "chrome-headless-patrol")
    has_profile = os.path.exists(headless_profile)
    # 巡检完成时附带概览信息
    if patrol_clean.get("state") == "done":
        pr = _load_patrol_result()
        if pr:
            n_brands = pr.get("brands", 0)
            n_issues = sum(len(v) for v in pr.get("issues", {}).values())
            n_auth = sum(1 for items in pr.get("issues", {}).values() for i in items if i.get("type") == "auth")
            parts = [f"{n_brands}个品牌"]
            if n_issues > 0:
                parts.append(f"{n_issues}个问题")
            if n_auth > 0:
                parts.append(f"{n_auth}个未授权")
            if n_issues == 0:
                parts.append("全部正常")
            patrol_clean["summary"] = "、".join(parts)
    # 定时巡检状态
    cfg = load_config()
    scheduled = cfg.get("patrol_time") if cfg.get("patrol_enabled") else None
    queue_size = len(_task_queue)
    # 初始化巡检时间：从patrol_result.json读
    patrol_ts = _last_patrol_ts
    if not patrol_ts:
        pr = _load_patrol_result()
        if pr and pr.get("ts"):
            _raw = pr["ts"]
            patrol_ts = _raw.split(" ")[-1] if _raw and " " in _raw else _raw
    return jsonify({"has_run_fast": has_run_fast, "patrol": patrol_clean, "headless_ready": has_profile,
                     "scheduled": scheduled, "queue": queue_size,
                     "last_patrol": patrol_ts, "last_alert": _last_alert_ts})


@app.route("/api/setup/status")
def api_setup_status():
    """冷启动checklist状态"""
    checks = {}

    # 1. Chrome debug端口是否可用
    chrome_ok = False
    try:
        r = subprocess.run(["curl", "--noproxy", "localhost", "-s", "--max-time", "2",
                           "http://localhost:9222/json/version"],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            chrome_ok = True
    except Exception:
        pass
    checks["chrome_debug"] = chrome_ok

    # 2. Goku插件是否已登录（有品牌数据）
    goku_ok = False
    goku_msg = ""
    if chrome_ok:
        try:
            # 用playwright检查太重，直接看config里有没有operator+上次巡检结果
            cfg = load_config()
            pr = _load_patrol_result()
            if pr and pr.get("brands", 0) > 0:
                goku_ok = True
                goku_msg = f"{pr['brands']}个品牌"
            elif cfg.get("operator"):
                goku_msg = "已设置运营名，未巡检"
        except Exception:
            pass
    checks["goku_login"] = goku_ok
    checks["goku_msg"] = goku_msg

    # 3. 运营名是否已设置
    cfg = load_config()
    operator = cfg.get("operator", "")
    checks["operator"] = operator
    checks["operator_set"] = bool(operator)

    # 4. 开发者模式（headless需要）
    dev_mode = False
    src_pref = os.path.expanduser("~/chrome-debug/Default/Secure Preferences")
    if os.path.exists(src_pref):
        try:
            with open(src_pref) as f:
                sp = json.load(f)
            dev_mode = sp.get("extensions", {}).get("ui", {}).get("developer_mode", False)
        except Exception:
            pass
    checks["developer_mode"] = dev_mode

    # 整体就绪
    checks["ready"] = chrome_ok and checks["operator_set"] and dev_mode

    return jsonify(checks)


@app.route("/api/headless/refresh", methods=["POST"])
def api_headless_refresh():
    """刷新headless登录态（从Chrome profile同步cookies）"""
    try:
        sys.path.insert(0, WORKSPACE)
        from browser import _sync_headless_profile, kill_headless
        kill_headless()
        _sync_headless_profile()
        return jsonify({"ok": True, "message": "登录态已同步"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/patrol/log")
def api_patrol_log():
    """查看巡检实时输出"""
    with _patrol_lock:
        return jsonify({
            "state": _patrol_state["state"],
            "message": _patrol_state["message"],
            "log": _patrol_state.get("log", ""),
        })


@app.route("/api/patrol/debug")
def api_patrol_debug():
    """查看巡检详细debug日志（patrol_debug.json）"""
    debug_file = os.path.join(os.path.dirname(__file__), "patrol_debug.json")
    if not os.path.exists(debug_file):
        return jsonify({"updated": None, "count": 0, "errors": 0, "log": []})
    try:
        with open(debug_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/patrol/brands", methods=["GET"])
def api_patrol_brands_get():
    """获取已配置的巡检品牌"""
    cfg = load_config()
    return jsonify({"brands": cfg.get("patrol_brands", [])})


@app.route("/api/patrol/brands", methods=["POST"])
def api_patrol_brands_set():
    """保存巡检品牌列表"""
    data = request.get_json(silent=True) or {}
    brands = data.get("brands", [])
    cfg = load_config()
    cfg["patrol_brands"] = brands
    save_config(cfg)
    return jsonify({"ok": True, "brands": brands})


def _get_operator_brands(operator):
    """从operators.json查运营名下的品牌列表"""
    ops_json = os.path.join(os.path.dirname(__file__), "operators.json")
    if not os.path.exists(ops_json):
        return []
    try:
        with open(ops_json) as f:
            data = json.load(f)
        brands_dict = data.get(operator, {})
        return list(brands_dict.keys()) if brands_dict else []
    except Exception as e:
        print(f"[patrol] 读operators.json失败: {e}")
        return []


@app.route("/api/goku/check")
def api_goku_check():
    """检查悟空插件登录状态"""
    result = _check_goku_login()
    return jsonify(result)


@app.route("/api/patrol/start", methods=["POST"])
def api_patrol_start():
    """启动巡检（根据运营名自动查品牌，直接subprocess调run_all_fast.py）"""
    data = request.get_json(silent=True) or {}
    operator = data.get("operator", "")
    brands = data.get("brands", [])

    # 巡检前先同步最新运营-店铺关系（确保新门店不遗漏）
    if operator and not brands:
        try:
            from sync_operators import sync
            sync(operator)
            print(f"[patrol] 已同步{operator}最新门店")
        except Exception as e:
            print(f"[patrol] 同步门店失败（用本地缓存）: {e}")
        brands = _get_operator_brands(operator)
        print(f"[patrol] 运营={operator}, 品牌={brands}")

    if not brands:
        return jsonify({"error": "no_brands", "message": f"没找到{operator}的品牌"}), 400

    script = os.path.join(WORKSPACE, "run_all_fast.py")
    if not os.path.exists(script):
        return jsonify({"ok": False, "message": "巡检脚本不存在"}), 500

    # 确保Chrome debug端口可用（无头模式需要它来同步登录态）
    if not _ensure_debug_chrome():
        _report_logs("error")
        return jsonify({"ok": False, "message": "Chrome debug端口启动失败，请确认Chrome已安装"}), 500

    # 预检goku登录状态（通过debug Chrome快速验证）
    goku_check = _check_goku_login()
    if not goku_check["ok"]:
        return jsonify({"ok": False, "message": goku_check["message"]}), 400

    result = _enqueue_patrol(brands, operator, "手动巡检")
    if result == "queued":
        return jsonify({"ok": True, "message": f"巡检排队中，当前任务完成后自动开始"})
    return jsonify({"ok": True, "message": f"巡检已启动: {', '.join(brands)}"})


@app.route("/api/patrol/progress", methods=["POST"])
def api_patrol_progress():
    """接收run_all_fast.py每个品牌完成后的增量推送"""
    data = request.get_json(silent=True) or {}
    with _patrol_lock:
        _patrol_progress["ts"] = cn_now().strftime("%Y-%m-%d %H:%M")
        _patrol_progress["done"] = data.get("done", 0)
        _patrol_progress["total"] = data.get("total", 0)
        # 合并issues
        for store, items in data.get("issues", {}).items():
            _patrol_progress["issues"][store] = items
        # 合并all_stores
        for store, plats in data.get("all_stores", {}).items():
            _patrol_progress["all_stores"][store] = plats
        # 合并brand_stores
        for brand, stores in data.get("brand_stores", {}).items():
            _patrol_progress["brand_stores"][brand] = stores
    return jsonify({"ok": True})


@app.route("/api/patrol/stop", methods=["POST"])
def api_patrol_stop():
    """手动终止卡住的巡检"""
    with _patrol_lock:
        pid = _patrol_state.get("pid")
        if _patrol_state["state"] != "running" or not pid:
            return jsonify({"ok": False, "message": "没有运行中的巡检"})
    try:
        import signal
        os.kill(pid, signal.SIGTERM)
        _cleanup_headless()
        with _patrol_lock:
            _patrol_state["state"] = "error"
            _patrol_state["message"] = "巡检已手动终止"
            _patrol_state["pid"] = None
            _patrol_state["started_at"] = None
            _task_queue.clear()  # 停止时清空队列
        return jsonify({"ok": True, "message": "巡检已终止，队列已清空"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ========== Settings ==========

@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    cfg = load_config()
    return jsonify({
        "patrol_enabled": cfg.get("patrol_enabled", False),
        "alert_enabled": cfg.get("alert_enabled", False),
        "patrol_time": cfg.get("patrol_time", "10:00"),
        "alert_interval": cfg.get("alert_interval", 10),
        "operator": cfg.get("operator", ""),
    })


@app.route("/api/settings", methods=["POST"])
def api_settings_set():
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    old_operator = cfg.get("operator", "")
    for key in ("patrol_enabled", "alert_enabled", "patrol_time", "alert_interval", "operator"):
        if key in data:
            cfg[key] = data[key]
    save_config(cfg)
    # 换人时清掉旧巡检数据，避免新运营看到上一个人的日报
    new_operator = data.get("operator", "")
    if new_operator and new_operator != old_operator:
        for f in ("patrol_result.json", "patrol_errors.json", "patrol_debug.json"):
            p = os.path.join(os.path.dirname(__file__), f)
            if os.path.exists(p):
                os.remove(p)
    return jsonify({"ok": True})


@app.route("/api/config")
def api_config():
    """Extension background.js配置（忽略哪些API等）"""
    cfg = load_config()
    return jsonify({
        "ignore_api_methods": cfg.get("ignore_api_methods", DEFAULT_CONFIG["ignore_api_methods"]),
        "ignore_api_prefixes": cfg.get("ignore_api_prefixes", DEFAULT_CONFIG["ignore_api_prefixes"]),
        "ignore_urls": cfg.get("ignore_urls", DEFAULT_CONFIG["ignore_urls"]),
    })


# ========== DeepSeek Agent Chat ==========

DEEPSEEK_API_KEY = "sk-e9a15a3b186f49308076422d2685f7b0"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

def _load_brain_knowledge():
    """加载BRAIN.md运营认知，注入system prompt"""
    brain_path = os.path.join(os.path.dirname(__file__), "..", "agent-config", "BRAIN.md")
    if os.path.exists(brain_path):
        try:
            with open(brain_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return ""

AGENT_SYSTEM_PROMPT = """你是小q，外卖运营团队的AI同事。你由DeepSeek驱动，不是Claude、不是ChatGPT、不是任何其他AI。如果被问到你是什么AI，回答"我是小q，团队的运营同事"即可，不要提任何底层模型。

## 你的职能
1. **答疑交流** — 基于运营认知和店铺数据，回答运营的疑问、一起讨论运营策略
2. **诊断助手** — 运营问起某个品牌/店铺，你查诊断报告发给他看，帮他理解问题
3. **Review诊断** — 和运营一起过诊断结果，一个店一个店聊：
   - 诊断报告里哪些对、哪些错（数据抓错/判断失误）
   - TODO哪些采纳、哪些不做（商家不配合/逻辑不对/优先级低）
   - 讨论出新的TODO方案
   - 确认的TODO存进CRM，跟进执行状态
4. **反馈收集** — 运营遇到任何问题都帮忙记录：
   - **产品bug**（product_bug）: 插件不好用、巡检跑不了、数据显示不对
   - **诊断bug**（diagnosis_bug）: 诊断报告内容有误、建议不合理、数据不准
   - **建议**（suggestion）: 想要什么功能、哪里可以改进
5. **会议纪要** — 查会议记录发给运营

## Review怎么聊（最核心的能力）

目标不是"给运营看报告"，而是通过逐项讨论，搞清楚三件事：
1. **诊断哪里对、哪里错** → 错的地方改进我们的认知（BRAIN）
2. **TODO哪些该做、哪些不该做、为什么** → 确认后存CRM推进
3. **讨论中发现的新洞察** → 补充到认知里

### Phase 1：逐章过诊断（一起看一个东西，聊各自的理解）

运营提到某个店 → 调crm_query_diagnosis拿到章节目录 → 从第一章开始。
每章用crm_query_diagnosis_section取内容。

**呈现方式：报告原文 + 你的理解 + 想讨论的点**

就像两个同事一起看同一份材料，你先说你看完的理解，再问对方怎么看：

示范：
> 先看产品端。报告原文是这样的：
>
> （贴出关键数据：品类=美蛙鱼头锅类，客单79.33元，商圈55.48元...）
>
> 我的理解：这家店定位挺清晰的，高客单聚餐店，不是快餐。但有个地方我觉得有意思——60到100这个区间几乎是空的，报告说可能是套餐没做好导致的"中间塌陷"。如果真是这样，双人套餐定价在79-89可能正好能填上。
>
> 不过我不确定的是：这个价格带空洞到底是套餐的问题，还是这家店本来就两极分化——要么一个人点个小份，要么一桌人点大餐？你在实际跟店的时候，客人一般是怎么点的？

要点：
1. **先给报告原文/关键数据**——运营能看到原始信息
2. **再说你的理解**——你怎么解读这些数据，像同事分享判断
3. **最后抛出你不确定的点**——不是"对吗？"而是"我觉得可能是XX，但也可能是YY，你怎么看？"

运营接话后，自然地聊——可能同意、可能补充、可能纠正。
聊完一章自然过渡下一章。运营说"不对"的地方，记录反馈（crm_record_feedback）。

### Phase 2：过TODO（一起定计划）

诊断聊完了 → 自然过渡到TODO。

方式：把TODO用大白话说出来，带上"为什么建议这样做"，问运营看法。
- 好的示范："第一条建议是查一下有没有设新客立减，现在新客下单率只有5.96%，商圈平均12%，差一倍。新客立减能直接降低首单门槛。你这边有在用新客立减吗？"
- 坏的示范："TODO-1：查明并修复新客下单率。你觉得能做吗？"

运营的回应自然会是：
- "做了/没做/做过但效果不好" → 你追问细节，更新状态
- "老板不愿意" → 不硬推，聊替代方案
- "这个我觉得不是这样" → 最有价值——记录为诊断错误
- 讨论中冒出新想法 → "这个挺好的，要加到计划里吗？"

确认的TODO调crm_save_todo存（必须带action_type，如"改满减"/"改菜品"/"改价格"等，用于自动匹配执行）。
运营说"做了/不做了/老板不同意"时调crm_mark_todo_done更新状态。

### Phase 3：聊完收尾

自然地总结，不要搞成表格汇报：
- "今天这家店聊下来，主要就是XX和YY两个方向，TODO定了X条。有个地方诊断判断错了——xxx，我记下来了回头改。下次你做了满减调整跟我说一声，我帮你看看效果。"

背后默默做的事（不用告诉运营）：
- 诊断错误 → crm_record_feedback已记录
- 确认的TODO → crm_save_todo已存（带action_type）
- 新发现/新认知 → crm_record_feedback(category=suggestion)记录

### Phase 4：后续跟进

运营再来聊这家店时：
- 先查CRM里的TODO，自然地问："上次说的满减调整弄了吗？"
- 不要搞成汇报："请汇报TODO执行情况"（这是领导不是同事）

### 沟通铁律
- **像同事讨论，不像上级审查**
- 没争议的一笔带过，有疑问的重点聊
- 运营说的"不对"最有价值——追问清楚，认真记录
- 一次聊一个点，运营接话了再往下走
- 不替运营做决定，商家不配合不硬推

## 说话风格（极其重要）

像微信聊天，像真人同事打字，不像AI输出。

绝对禁止：
- 不用**加粗**、不用*斜体*、不用##标题、不用- 列表、不用表格、不用代码块
- 不用"①②③"、不用"**关键发现**："这种格式化标题
- 不用"让我为您分析"、"以下是我的理解"这种AI腔
- 不用emoji（除非运营先用了）

正确的方式：
- 就是打字，一段一段说，像微信发消息
- 数据直接写在句子里："客单79块，商圈平均55，高出不少"
- 想强调就用口语："这个挺关键的"、"这块我觉得有问题"
- 分段靠换行，不靠格式符号

好的示范：
"先看产品端。这家店品类很清晰，美蛙鱼头锅类，客单79块比商圈55高出不少。竞对主要是龙虾王那种高客单聚餐店，不是跟快餐抢。

不过有个地方我觉得有意思，60到100这个价格区间几乎没单，就12.5%。按理说两个人吃美蛙鱼头，花个七八十很正常，但这个区间空了。我觉得可能是套餐没做好，没有引导两个人点一份合适的组合。你觉得呢？是这个原因还是有别的？"

## 反馈处理
运营说了任何问题（"不好用"、"不对"、"有bug"、"能不能加"等），主动归类并记录：
- 先用自己的话复述确认："你是说xxx对吧？"
- 确认后调crm_record_feedback记录，选对category
- 告诉运营："记下了，会反馈给管理员"

## 当前运营
{operator}

## 你的运营认知
{brain}

## 工具使用
根据运营的问题选择合适的工具。优先用CRM工具查诊断和会议纪要。
运营闲聊或请教运营问题时，结合你的运营认知直接回答，不需要调工具。

## 重要：诊断报告必须原文转发（最高优先级规则）
1. 运营问诊断报告时，**必须先调crm_query_diagnosis工具**，绝对不能自己编
2. 工具返回的report_content就是原文，**原样复制粘贴给运营，一个数字都不改**
3. 你可以在报告前面加一句引导语，但报告内容本身不能改写、不能补充、不能换措辞
4. **绝对禁止**：自己编造评分、月售、客单价、满减档位等数据。编造数据会严重误导运营决策
5. 如果工具没查到报告，就说"没找到这个品牌的诊断报告"，不要自己凑一份"""

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_alerts",
            "description": "查询当前预警信息（差评、推广余额不足、评分下降等）",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_daily_report",
            "description": "查询最新巡检日报",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_logs",
            "description": "查询运营操作日志",
            "parameters": {
                "type": "object",
                "properties": {
                    "operator": {"type": "string", "description": "运营人员姓名，可选"},
                    "shop_name": {"type": "string", "description": "店铺名称关键词，可选"},
                    "action_type": {"type": "string", "description": "操作类型如menu_update/promotion等，可选"},
                    "limit": {"type": "integer", "description": "返回条数，默认20", "default": 20}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_tracking",
            "description": "查询改动效果追踪（运营改了菜单/活动后的效果跟进）",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "状态：pending/collected/all", "default": "pending"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_food_cache",
            "description": "查询店铺菜单缓存（菜品名称、价格、月售等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "shop_name": {"type": "string", "description": "店铺名称关键词"},
                    "food_name": {"type": "string", "description": "菜品名称关键词，可选"}
                },
                "required": ["shop_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_shop_list",
            "description": "查询所有运营的完整店铺列表（含品牌、平台）。运营问'我有哪些店'、'服务几家店'时调用",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crm_query_diagnosis",
            "description": "查询品牌/店铺的诊断报告。运营问起某个品牌的诊断、问题、建议时调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_name": {"type": "string", "description": "品牌名或店铺名关键词"},
                    "operator": {"type": "string", "description": "运营姓名，可选，不填查所有"}
                },
                "required": ["store_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crm_query_meeting",
            "description": "查询会议纪要。运营问起开会内容、会议记录时调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_name": {"type": "string", "description": "品牌名关键词，可选"},
                    "keyword": {"type": "string", "description": "搜索关键词，可选"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crm_list_stores",
            "description": "查询CRM中所有品牌列表（含运营、阶段、诊断时间）。运营问'我有哪些店'或'最近诊断了哪些'时调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "operator": {"type": "string", "description": "运营姓名，可选"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crm_save_todo",
            "description": "保存讨论确认的TODO到CRM。和运营讨论达成共识后调用——运营认可要做某件事时，把它存为结构化TODO",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_name": {"type": "string", "description": "品牌名"},
                    "content": {"type": "string", "description": "TODO内容，具体到操作（如'满减第二档改成45减8'）"},
                    "action_type": {"type": "string", "enum": ["改满减", "改菜品", "改价格", "改推广", "改活动", "改店铺信息", "改菜单结构", "回复评价", "其他"], "description": "操作类型，用于和ops-log自动匹配"},
                    "reason": {"type": "string", "description": "为什么要做（简短原因）"},
                    "expected_impact": {"type": "string", "description": "预期效果（如'客单价提升5元'）"}
                },
                "required": ["store_name", "content", "action_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crm_mark_todo_done",
            "description": "标记TODO状态。运营说'做了'/'不做了'/'老板不同意'时调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_name": {"type": "string", "description": "品牌名"},
                    "todo_content": {"type": "string", "description": "TODO内容关键词，模糊匹配"},
                    "new_status": {"type": "string", "enum": ["已执行", "不做了", "商家不同意", "待讨论", "已完成"], "description": "新状态"},
                    "note": {"type": "string", "description": "备注（运营说了什么原因）"}
                },
                "required": ["store_name", "todo_content", "new_status"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crm_record_feedback",
            "description": "记录运营反馈。产品bug(插件/巡检不好用)、诊断bug(报告内容有误)、建议(想要什么功能)都用这个",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["product_bug", "diagnosis_bug", "suggestion", "other"], "description": "反馈分类: product_bug=产品使用问题, diagnosis_bug=诊断报告问题, suggestion=建议, other=其他"},
                    "store_name": {"type": "string", "description": "相关品牌名，没有就填空"},
                    "content": {"type": "string", "description": "反馈内容，尽量详细"}
                },
                "required": ["category", "content"]
            }
        }
    }
]

def _exec_tool(name, args):
    """Execute a tool call and return result string."""
    conn = get_db()
    try:
        if name == "query_alerts":
            rows = conn.execute("""
                SELECT shop_id, shop_name, platform, action_type, action_detail, change_summary, received_at
                FROM logs WHERE action_type IN ('bad_review','promotion_alert','score_drop')
                AND received_at > datetime('now','-3 days','localtime')
                ORDER BY received_at DESC LIMIT 20
            """).fetchall()
            if not rows:
                # Also check daily patrol alerts
                patrol_db = os.path.join(os.path.dirname(__file__), "..", "patrol_snapshots.db")
                if os.path.exists(patrol_db):
                    pc = sqlite3.connect(patrol_db)
                    pc.row_factory = sqlite3.Row
                    pr = pc.execute("""
                        SELECT store, platform, issue_type, detail, severity
                        FROM issues WHERE date >= date('now','-1 day','localtime')
                        ORDER BY severity DESC LIMIT 20
                    """).fetchall()
                    pc.close()
                    if pr:
                        return json.dumps([dict(r) for r in pr], ensure_ascii=False)
                return "最近3天没有预警"
            return json.dumps([dict(r) for r in rows], ensure_ascii=False)

        elif name == "query_daily_report":
            patrol_db = os.path.join(os.path.dirname(__file__), "..", "patrol_snapshots.db")
            if os.path.exists(patrol_db):
                pc = sqlite3.connect(patrol_db)
                pc.row_factory = sqlite3.Row
                pr = pc.execute("""
                    SELECT store, platform, issue_type, detail, severity, date
                    FROM issues WHERE date >= date('now','-1 day','localtime')
                    ORDER BY store, platform
                """).fetchall()
                pc.close()
                if pr:
                    return json.dumps([dict(r) for r in pr], ensure_ascii=False)
            # Fallback: recent logs summary
            rows = conn.execute("""
                SELECT shop_name, action_type, COUNT(*) as cnt
                FROM logs WHERE received_at > datetime('now','-1 day','localtime')
                AND action_type IS NOT NULL AND action_type != ''
                GROUP BY shop_name, action_type ORDER BY cnt DESC LIMIT 20
            """).fetchall()
            if rows:
                return json.dumps([dict(r) for r in rows], ensure_ascii=False)
            return "今天还没有巡检数据"

        elif name == "query_logs":
            where = ["1=1"]
            params = []
            if args.get("operator"):
                where.append("operator LIKE ?")
                params.append(f"%{args['operator']}%")
            if args.get("shop_name"):
                where.append("shop_name LIKE ?")
                params.append(f"%{args['shop_name']}%")
            if args.get("action_type"):
                where.append("action_type LIKE ?")
                params.append(f"%{args['action_type']}%")
            limit = min(args.get("limit", 20), 50)
            rows = conn.execute(f"""
                SELECT operator, shop_name, platform, action_type, action_detail,
                       change_summary, item_name, received_at
                FROM logs WHERE {' AND '.join(where)}
                ORDER BY received_at DESC LIMIT ?
            """, params + [limit]).fetchall()
            if not rows:
                return "没有找到匹配的操作日志"
            return json.dumps([dict(r) for r in rows], ensure_ascii=False)

        elif name == "query_tracking":
            status = args.get("status", "pending")
            if status == "all":
                rows = conn.execute("""
                    SELECT shop_id, platform, action_type, check_type, check_date, status, metrics_before, metrics_after
                    FROM change_tracking ORDER BY created_at DESC LIMIT 20
                """).fetchall()
            else:
                rows = conn.execute("""
                    SELECT shop_id, platform, action_type, check_type, check_date, status, metrics_before, metrics_after
                    FROM change_tracking WHERE status = ? ORDER BY created_at DESC LIMIT 20
                """, [status]).fetchall()
            if not rows:
                return "没有待追踪的改动"
            return json.dumps([dict(r) for r in rows], ensure_ascii=False)

        elif name == "query_food_cache":
            shop_name = args.get("shop_name", "")
            food_name = args.get("food_name", "")
            # First find shop_id from shop_cache
            shops = conn.execute("SELECT shop_id, shop_name FROM shop_cache WHERE shop_name LIKE ?",
                                 [f"%{shop_name}%"]).fetchall()
            if not shops:
                return f"没有找到包含'{shop_name}'的店铺"
            shop_ids = [s["shop_id"] for s in shops]
            placeholders = ",".join(["?"] * len(shop_ids))
            q = f"""SELECT fs.name, fs.price, fs.monthly_sales, fs.category_name, fs.status,
                           sc.shop_name, fs.shop_id
                    FROM food_snapshot fs
                    JOIN shop_cache sc ON fs.shop_id = sc.shop_id
                    WHERE fs.shop_id IN ({placeholders})"""
            p = list(shop_ids)
            if food_name:
                q += " AND fs.name LIKE ?"
                p.append(f"%{food_name}%")
            q += " ORDER BY fs.monthly_sales DESC LIMIT 30"
            rows = conn.execute(q, p).fetchall()
            if not rows:
                # Try food_cache table
                q2 = f"SELECT name, price, shop_id FROM food_cache WHERE shop_id IN ({placeholders})"
                p2 = list(shop_ids)
                if food_name:
                    q2 += " AND name LIKE ?"
                    p2.append(f"%{food_name}%")
                q2 += " LIMIT 30"
                rows = conn.execute(q2, p2).fetchall()
            if not rows:
                return f"找到店铺但没有菜品缓存数据"
            return json.dumps([dict(r) for r in rows], ensure_ascii=False)

        elif name == "query_shop_list":
            # 优先从operators.json读完整列表（品牌→门店→平台）
            ops_json_path = os.path.join(os.path.dirname(__file__), "operators.json")
            try:
                with open(ops_json_path, "r", encoding="utf-8") as f:
                    ops_data = json.load(f)
                result = []
                for op_name, brands in ops_data.items():
                    for bname, stores in brands.items():
                        for st in stores:
                            platforms = [p["p"] for p in st.get("platforms", [])]
                            result.append({"operator": op_name, "brand": bname, "store": st["store"], "ish_id": st.get("ish_id"), "platforms": platforms})
                if result:
                    return json.dumps(result, ensure_ascii=False)
            except Exception:
                pass
            # fallback到shop_cache
            rows = conn.execute("SELECT shop_id, shop_name, platform FROM shop_cache ORDER BY shop_name").fetchall()
            if not rows:
                return "还没有缓存任何店铺"
            return json.dumps([dict(r) for r in rows], ensure_ascii=False)

        # ===== CRM Tools =====
        elif name == "crm_query_diagnosis":
            return _crm_query_diagnosis(args)
        elif name == "crm_query_meeting":
            return _crm_query_meeting(args)
        elif name == "crm_list_stores":
            return _crm_list_stores(args)
        elif name == "crm_save_todo":
            return _crm_save_todo(args)
        elif name == "crm_mark_todo_done":
            return _crm_mark_todo_done(args)
        elif name == "crm_record_feedback":
            return _crm_record_feedback(args)

        else:
            return f"未知工具: {name}"
    except Exception as e:
        return f"查询出错: {str(e)}"
    finally:
        conn.close()

# ========== 日志上报（远程→管理员） ==========

def _backfill_log_names():
    """回填logs表中空的shop_name和item_name（从food_cache/shop_cache补全）"""
    try:
        conn = get_db()
        # 回填shop_name
        conn.execute("""
            UPDATE logs SET shop_name = (
                SELECT shop_name FROM shop_cache WHERE shop_cache.shop_id = logs.shop_id
            ) WHERE (shop_name = '' OR shop_name IS NULL)
              AND shop_id <> ''
              AND EXISTS (SELECT 1 FROM shop_cache WHERE shop_cache.shop_id = logs.shop_id)
        """)
        # 回填item_name（单个item_id，不含逗号的）
        conn.execute("""
            UPDATE logs SET item_name = (
                SELECT name FROM food_cache WHERE food_cache.item_key = logs.item_id
            ) WHERE (item_name = '' OR item_name IS NULL)
              AND item_id <> '' AND item_id NOT LIKE '%,%'
              AND EXISTS (SELECT 1 FROM food_cache WHERE food_cache.item_key = logs.item_id)
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[backfill] 回填失败: {e}")


def _report_logs(log_type="error"):
    """将本地日志上报给管理员server（非阻塞）"""
    def _do_report():
        url = _discover_crm_remote()
        if not url:
            return
        try:
            operator = load_config().get("operator", "unknown")
            hostname = socket.gethostname() if hasattr(socket, 'gethostname') else "unknown"

            entries = []
            if log_type == "error":
                # 带上当前patrol状态（包含失败原因）
                with _patrol_lock:
                    patrol_msg = _patrol_state.get("message", "")
                    patrol_state = _patrol_state.get("state", "")
                entries.append({
                    "ts": cn_now().strftime("%Y-%m-%d %H:%M:%S"),
                    "state": patrol_state,
                    "message": patrol_msg,
                    "last_step": _get_last_debug_step() or "",
                })
                # 也带上patrol_errors.json（如果有）
                err_file = os.path.join(os.path.dirname(__file__), "patrol_errors.json")
                if os.path.exists(err_file):
                    with open(err_file) as f:
                        entries.extend(json.load(f))
            elif log_type == "patrol":
                result_file = os.path.join(os.path.dirname(__file__), "patrol_result.json")
                if os.path.exists(result_file):
                    with open(result_file) as f:
                        result = json.load(f)
                    # 只上报摘要和issues
                    entries = [{
                        "ts": result.get("ts", ""),
                        "brands": result.get("brands", 0),
                        "duration": result.get("duration", 0),
                        "issues": result.get("issues", {}),
                    }]
            elif log_type == "health":
                entries = [{
                    "ts": cn_now().strftime("%Y-%m-%d %H:%M:%S"),
                    "state": _patrol_state.get("state", "idle"),
                    "message": _patrol_state.get("message", ""),
                }]
            elif log_type == "ops":
                # 上报未同步的操作日志（积压补发）
                conn = get_db()
                rows = conn.execute("""
                    SELECT id, operator, timestamp, api_method, platform,
                           shop_id, shop_name, item_id, item_name,
                           action_type, action_detail, before_snapshot,
                           change_summary, received_at
                    FROM logs WHERE reported = 0
                    ORDER BY id ASC LIMIT 100
                """).fetchall()
                if rows:
                    entries = [dict(r) for r in rows]
                    # 标记为已上报
                    ids = [r["id"] for r in rows]
                    conn.execute(f"UPDATE logs SET reported=1 WHERE id IN ({','.join('?' * len(ids))})", ids)
                    conn.commit()
                conn.close()

            elif log_type == "chat":
                # 上报未同步的聊天记录
                chat_dir = os.path.join(os.path.dirname(__file__), "chat_logs")
                reported_file = os.path.join(chat_dir, "_reported.json")
                reported = {}
                if os.path.exists(reported_file):
                    try:
                        with open(reported_file) as f:
                            reported = json.load(f)
                    except:
                        reported = {}

                if os.path.isdir(chat_dir):
                    for fname in sorted(os.listdir(chat_dir)):
                        if not fname.endswith(".jsonl") or fname.startswith("_"):
                            continue
                        fpath = os.path.join(chat_dir, fname)
                        file_size = os.path.getsize(fpath)
                        last_reported_size = reported.get(fname, 0)
                        if file_size <= last_reported_size:
                            continue
                        with open(fpath, "r", encoding="utf-8") as f:
                            f.seek(last_reported_size)
                            new_lines = f.readlines()
                        if new_lines:
                            for line in new_lines:
                                try:
                                    entries.append(json.loads(line.strip()))
                                except:
                                    pass
                            reported[fname] = file_size

                    if entries:
                        with open(reported_file, "w", encoding="utf-8") as f:
                            json.dump(reported, f)

            if not entries:
                return

            session = http_requests.Session()
            session.trust_env = False
            session.post(f"{url}/api/logs/report",
                        json={"operator": operator, "hostname": hostname,
                              "type": log_type, "entries": entries},
                        timeout=10)
        except Exception as e:
            print(f"[log-report] 上报失败: {e}")

    threading.Thread(target=_do_report, daemon=True).start()


CRM_DB = os.path.join(os.path.expanduser("~"), "Downloads", "diagnosis-queue", "crm.db")
# 公网CRM API地址，本地没有crm.db时走远程（自动从OSS发现）
CRM_REMOTE_URL = os.environ.get("CRM_REMOTE_URL", "")

def _discover_crm_remote():
    """从OSS读取管理员tunnel URL，缓存10分钟"""
    import time as _time
    global CRM_REMOTE_URL, _crm_url_ts
    now = _time.time()
    if CRM_REMOTE_URL and hasattr(_discover_crm_remote, '_ts') and now - _discover_crm_remote._ts < 600:
        return CRM_REMOTE_URL
    try:
        session = http_requests.Session()
        session.trust_env = False
        resp = session.get("https://meihu-video.oss-cn-hangzhou.aliyuncs.com/tools/ops-logger-server.json", timeout=5)
        if resp.ok:
            url = resp.json().get("url", "")
            if url:
                CRM_REMOTE_URL = url
                _discover_crm_remote._ts = now
                print(f"[crm] 发现管理员服务: {url}")
    except Exception as e:
        print(f"[crm] 发现管理员服务失败: {e}")
    return CRM_REMOTE_URL

def _crm_db():
    if not os.path.exists(CRM_DB):
        return None
    conn = sqlite3.connect(CRM_DB)
    conn.row_factory = sqlite3.Row
    return conn

def _crm_remote_call(tool_name, args):
    """本地没有crm.db时，调用管理员公网CRM API"""
    url = _discover_crm_remote()
    if not url:
        return "CRM服务暂时连不上，稍后再试"
    try:
        session = http_requests.Session()
        session.trust_env = False
        resp = session.post(f"{url}/api/crm/tool",
                           json={"tool": tool_name, "args": args}, timeout=15)
        if resp.ok:
            return resp.json().get("result", "查询失败")
        return f"CRM服务不可用({resp.status_code})"
    except Exception as e:
        return f"CRM连接失败: {str(e)[:50]}"

# ========== 远程日志上报 ==========

REMOTE_LOGS_DIR = os.path.join(os.path.dirname(__file__), "remote_logs")

@app.route("/api/logs/report", methods=["POST"])
def api_logs_report():
    """接收远程server上报的日志"""
    data = request.json or {}
    operator = data.get("operator", "unknown")
    hostname = data.get("hostname", "unknown")
    log_type = data.get("type", "error")  # error / patrol / health
    entries = data.get("entries", [])
    if not entries:
        return jsonify({"ok": True, "msg": "empty"})

    os.makedirs(REMOTE_LOGS_DIR, exist_ok=True)
    today = cn_now().strftime("%Y-%m-%d")
    filepath = os.path.join(REMOTE_LOGS_DIR, f"{operator}_{today}.jsonl")
    with open(filepath, "a", encoding="utf-8") as f:
        for entry in entries:
            entry["_operator"] = operator
            entry["_hostname"] = hostname
            entry["_type"] = log_type
            entry["_received"] = cn_now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ops类型的日志同时写入本地DB，方便统一查询
    if log_type == "ops" and entries:
        try:
            conn = get_db()
            for entry in entries:
                conn.execute(
                    """INSERT OR IGNORE INTO logs
                       (operator, timestamp, api_method, url, platform,
                        shop_id, shop_name, item_id, item_name,
                        action_type, action_detail, before_snapshot,
                        change_summary, received_at, reported)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (entry.get("operator", operator),
                     entry.get("timestamp", ""),
                     entry.get("api_method", ""),
                     entry.get("url", ""),
                     entry.get("platform", ""),
                     entry.get("shop_id", ""),
                     entry.get("shop_name", ""),
                     entry.get("item_id", ""),
                     entry.get("item_name", ""),
                     entry.get("action_type", ""),
                     entry.get("action_detail", ""),
                     entry.get("before_snapshot", ""),
                     entry.get("change_summary", ""),
                     entry.get("received_at", cn_now().strftime("%Y-%m-%d %H:%M:%S")))
                )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[remote-log] 写入DB失败: {e}")

    print(f"[remote-log] 收到 {operator}@{hostname} 的 {len(entries)} 条 {log_type} 日志")
    return jsonify({"ok": True, "received": len(entries)})


# ========== 远程指令（管理员→运营机器） ==========
_remote_commands = {}  # {operator: [{"cmd": "stop/restart", "ts": "...", "consumed": False}]}

@app.route("/api/commands/push", methods=["POST"])
def api_commands_push():
    """管理员下发指令给运营机器"""
    data = request.json or {}
    operator = data.get("operator", "")
    cmd = data.get("cmd", "")  # stop / restart
    if not operator or cmd not in ("stop", "restart"):
        return jsonify({"ok": False, "message": "需要operator和cmd(stop/restart)"}), 400
    if operator not in _remote_commands:
        _remote_commands[operator] = []
    _remote_commands[operator].append({
        "cmd": cmd,
        "ts": cn_now().strftime("%Y-%m-%d %H:%M:%S"),
        "consumed": False
    })
    print(f"[cmd] 下发指令: {operator} → {cmd}")
    return jsonify({"ok": True, "message": f"已下发 {cmd} 给 {operator}"})

@app.route("/api/commands/pull")
def api_commands_pull():
    """运营机器拉取待执行指令"""
    operator = request.args.get("operator", "")
    if not operator or operator not in _remote_commands:
        return jsonify({"commands": []})
    pending = [c for c in _remote_commands[operator] if not c["consumed"]]
    for c in pending:
        c["consumed"] = True
    # 清理已消费的旧指令
    _remote_commands[operator] = [c for c in _remote_commands[operator] if not c["consumed"]]
    return jsonify({"commands": [{"cmd": c["cmd"], "ts": c["ts"]} for c in pending]})


@app.route("/api/logs/query")
def api_logs_query():
    """查询远程上报的日志"""
    operator = request.args.get("operator", "")
    date = request.args.get("date", cn_now().strftime("%Y-%m-%d"))
    log_type = request.args.get("type", "")
    limit = request.args.get("limit", 100, type=int)

    if not os.path.exists(REMOTE_LOGS_DIR):
        return jsonify([])

    results = []
    for fname in sorted(os.listdir(REMOTE_LOGS_DIR), reverse=True):
        if not fname.endswith(".jsonl"):
            continue
        if operator and operator not in fname:
            continue
        if date and date not in fname:
            continue
        fpath = os.path.join(REMOTE_LOGS_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if log_type and entry.get("_type") != log_type:
                        continue
                    results.append(entry)
                except:
                    pass
    results = results[-limit:]
    return jsonify(results)


# ========== CRM公网API ==========

@app.route("/api/crm/tool", methods=["POST"])
def api_crm_tool():
    """公网CRM工具端点 — 供远程server调用"""
    data = request.json or {}
    tool = data.get("tool", "")
    args = data.get("args", {})
    handlers = {
        "crm_query_diagnosis": _crm_query_diagnosis_local,
        "crm_query_meeting": _crm_query_meeting_local,
        "crm_list_stores": _crm_list_stores_local,
        "crm_save_todo": _crm_save_todo_local,
        "crm_mark_todo_done": _crm_mark_todo_done_local,
        "crm_record_feedback": _crm_record_feedback_local,
    }
    fn = handlers.get(tool)
    if not fn:
        return jsonify({"result": f"未知CRM工具: {tool}"}), 400
    return jsonify({"result": fn(args)})

def _crm_query_diagnosis(args):
    """查诊断报告 — 本地优先，无则走远程"""
    if os.path.exists(CRM_DB):
        return _crm_query_diagnosis_local(args)
    return _crm_remote_call("crm_query_diagnosis", args)

def _crm_query_diagnosis_local(args):
    """查诊断报告（本地）— 返回最新报告的关键部分，控制长度"""
    conn = _crm_db()
    if not conn:
        return "CRM数据库不存在"
    store_name = args.get("store_name", "")
    operator = args.get("operator", "")
    # 先找store
    q = "SELECT id, store_name, branch, operator_name, stage, diagnosed_at FROM stores WHERE store_name LIKE ?"
    p = [f"%{store_name}%"]
    if operator:
        q += " AND operator_name LIKE ?"
        p.append(f"%{operator}%")
    stores = conn.execute(q, p).fetchall()
    if not stores:
        conn.close()
        return f"没有找到包含'{store_name}'的品牌"
    results = []
    for s in stores[:3]:  # 最多3个品牌
        docs = conn.execute(
            "SELECT doc_type, title, content, created_at FROM documents WHERE store_id=? AND doc_type='report' ORDER BY created_at DESC LIMIT 1",
            (s["id"],)).fetchall()
        store_info = {"brand": s["store_name"], "branch": s["branch"], "operator": s["operator_name"],
                      "stage": s["stage"], "diagnosed_at": s["diagnosed_at"]}
        if docs:
            content = docs[0]["content"]
            # 提取关键部分，控制返回长度（DeepSeek处理超长tool output会编造）
            key_content = _extract_report_key_sections(content)
            store_info["report_title"] = docs[0]["title"]
            store_info["report_date"] = docs[0]["created_at"]
            store_info["report_content"] = key_content
            store_info["_notice"] = "以下是官方诊断报告原文，必须原样转发给运营，一个字不改"
        results.append(store_info)
    conn.close()
    return json.dumps(results, ensure_ascii=False)


def _extract_report_key_sections(content):
    """从诊断报告md中提取关键部分：诊断总结+TODO+做对了的，控制在4000字内"""
    import re
    sections = []
    # 尝试提取第二次诊断（复诊）部分
    m = re.search(r'(## 第\d+次诊断.*)', content, re.DOTALL)
    if m:
        sections.append(m.group(1)[:4000])
    else:
        # 提取诊断总结
        m = re.search(r'(## 三、诊断总结.*?)(?=\n## 四、|$)', content, re.DOTALL)
        if m:
            sections.append(m.group(1)[:2000])
        # 提取TODO
        m = re.search(r'(## 四、TODO.*?)(?=\n## 五、|$)', content, re.DOTALL)
        if m:
            sections.append(m.group(1)[:2000])
        # 如果都没找到，取最后40%的内容（通常是总结部分）
        if not sections:
            cut = max(0, len(content) - 4000)
            sections.append(content[cut:])
    return "\n".join(sections)

def _crm_query_meeting(args):
    """查会议纪要 — 本地优先，无则走远程"""
    if os.path.exists(CRM_DB):
        return _crm_query_meeting_local(args)
    return _crm_remote_call("crm_query_meeting", args)

def _crm_query_meeting_local(args):
    """查会议纪要（本地）"""
    conn = _crm_db()
    if not conn:
        return "CRM数据库不存在"
    store_name = args.get("store_name", "")
    keyword = args.get("keyword", "")
    if store_name:
        rows = conn.execute("""
            SELECT d.title, d.content, d.created_at, s.store_name, s.branch
            FROM documents d JOIN stores s ON d.store_id = s.id
            WHERE d.doc_type IN ('meeting','review') AND s.store_name LIKE ?
            ORDER BY d.created_at DESC LIMIT 10
        """, (f"%{store_name}%",)).fetchall()
    elif keyword:
        rows = conn.execute("""
            SELECT d.title, d.content, d.created_at, s.store_name, s.branch
            FROM documents d JOIN stores s ON d.store_id = s.id
            WHERE d.doc_type IN ('meeting','review') AND (d.content LIKE ? OR d.title LIKE ?)
            ORDER BY d.created_at DESC LIMIT 10
        """, (f"%{keyword}%", f"%{keyword}%")).fetchall()
    else:
        rows = conn.execute("""
            SELECT d.title, d.content, d.created_at, s.store_name, s.branch
            FROM documents d JOIN stores s ON d.store_id = s.id
            WHERE d.doc_type IN ('meeting','review')
            ORDER BY d.created_at DESC LIMIT 10
        """).fetchall()
    conn.close()
    if not rows:
        return "没有找到会议纪要"
    return json.dumps([dict(r) for r in rows], ensure_ascii=False)

def _crm_list_stores(args):
    """列出CRM品牌 — 本地优先，无则走远程"""
    if os.path.exists(CRM_DB):
        return _crm_list_stores_local(args)
    return _crm_remote_call("crm_list_stores", args)

def _crm_list_stores_local(args):
    """列出CRM品牌（本地）"""
    conn = _crm_db()
    if not conn:
        return "CRM数据库不存在"
    operator = args.get("operator", "")
    if operator:
        rows = conn.execute(
            "SELECT store_name, branch, operator_name, stage, diagnosed_at FROM stores WHERE operator_name LIKE ? ORDER BY diagnosed_at DESC",
            (f"%{operator}%",)).fetchall()
    else:
        rows = conn.execute(
            "SELECT store_name, branch, operator_name, stage, diagnosed_at FROM stores ORDER BY diagnosed_at DESC").fetchall()
    conn.close()
    if not rows:
        return "CRM中没有品牌记录"
    return json.dumps([dict(r) for r in rows], ensure_ascii=False)

def _crm_save_todo(args):
    """保存TODO — 本地优先，无则走远程"""
    if os.path.exists(CRM_DB):
        return _crm_save_todo_local(args)
    return _crm_remote_call("crm_save_todo", args)

def _crm_save_todo_local(args):
    """讨论确认的TODO写入CRM todos表"""
    conn = _crm_db()
    if not conn:
        return "CRM数据库不存在"
    store_name = args.get("store_name", "")
    content = args.get("content", "")
    action_type = args.get("action_type", "其他")
    reason = args.get("reason", "")
    expected_impact = args.get("expected_impact", "")

    # 找store_id
    store = conn.execute("SELECT id FROM stores WHERE store_name LIKE ? LIMIT 1", (f"%{store_name}%",)).fetchone()
    if not store:
        conn.close()
        return f"CRM中没有找到品牌'{store_name}'，TODO未保存"
    store_id = store["id"]

    # 算seq：当前最大seq + 1
    row = conn.execute("SELECT MAX(seq) as max_seq FROM todos WHERE store_id=?", (store_id,)).fetchone()
    seq = (row["max_seq"] or 0) + 1

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO todos (store_id, seq, content, funnel_stage, reason, expected_impact, type, status, context, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (store_id, seq, content, action_type, reason, expected_impact, "todo", "待做", f"[讨论确认] {now}", now))
    conn.execute("INSERT INTO events (store_id, event_type, content) VALUES (?, 'todo_created', ?)",
                 (store_id, f"TODO#{seq}: {content}"))
    conn.commit()
    conn.close()
    return f"已保存TODO#{seq}: {content}"

def _crm_mark_todo_done(args):
    """更新TODO状态 — 本地优先，无则走远程"""
    if os.path.exists(CRM_DB):
        return _crm_mark_todo_done_local(args)
    return _crm_remote_call("crm_mark_todo_done", args)

def _crm_mark_todo_done_local(args):
    """更新TODO状态（本地）"""
    conn = _crm_db()
    if not conn:
        return "CRM数据库不存在"
    store_name = args.get("store_name", "")
    todo_content = args.get("todo_content", "")
    new_status = args.get("new_status", "已执行")
    note = args.get("note", "")

    store = conn.execute("SELECT id FROM stores WHERE store_name LIKE ? LIMIT 1", (f"%{store_name}%",)).fetchone()
    if not store:
        conn.close()
        return f"CRM中没有找到品牌'{store_name}'"
    store_id = store["id"]

    # 模糊匹配TODO内容
    todo = conn.execute("SELECT id, seq, content, status FROM todos WHERE store_id=? AND content LIKE ? LIMIT 1",
                        (store_id, f"%{todo_content}%")).fetchone()
    if not todo:
        conn.close()
        return f"没有找到匹配的TODO: {todo_content}"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    feedback_text = f"[{now}] {new_status}" + (f" — {note}" if note else "")
    old_feedback = todo["status"] or ""

    conn.execute("UPDATE todos SET status=?, feedback=COALESCE(feedback,'')||?, updated_at=? WHERE id=?",
                 (new_status, f"\n{feedback_text}" if old_feedback else feedback_text, now, todo["id"]))
    conn.execute("INSERT INTO events (store_id, event_type, content) VALUES (?, 'todo_update', ?)",
                 (store_id, f"TODO#{todo['seq']} → {new_status}" + (f": {note}" if note else "")))
    conn.commit()
    conn.close()
    return f"已更新TODO#{todo['seq']}: {todo['content'][:30]} → {new_status}"

def _crm_record_feedback(args):
    """记录反馈 — 本地优先，无则走远程"""
    if os.path.exists(CRM_DB):
        return _crm_record_feedback_local(args)
    return _crm_remote_call("crm_record_feedback", args)

def _crm_record_feedback_local(args):
    """记录反馈（本地），支持分类"""
    conn = _crm_db()
    if not conn:
        return "CRM数据库不存在"
    store_name = args.get("store_name", "")
    content = args.get("content", "")
    category = args.get("category", "other")

    # 找store_id（可选，product_bug/suggestion可能没有关联品牌）
    store_id = None
    if store_name:
        store = conn.execute("SELECT id FROM stores WHERE store_name LIKE ? LIMIT 1", (f"%{store_name}%",)).fetchone()
        if store:
            store_id = store["id"]

    # event_type带分类前缀: feedback_product_bug / feedback_diagnosis_bug / feedback_suggestion
    event_type = f"feedback_{category}" if category else "feedback"
    tagged_content = f"[{category}] {content}"

    conn.execute("INSERT INTO events (store_id, event_type, content) VALUES (?, ?, ?)",
                 (store_id, event_type, tagged_content))
    conn.commit()
    conn.close()

    # 同时上报到远程（管理员实时可查）
    _report_feedback_remote(category, store_name, content)

    return f"已记录反馈: {content[:50]}"


def _report_feedback_remote(category, store_name, content):
    """反馈实时上报给管理员"""
    try:
        url = _discover_crm_remote()
        if not url:
            return
        operator = load_config().get("operator", "unknown")
        session = http_requests.Session()
        session.trust_env = False
        session.post(f"{url}/api/logs/report",
                     json={"operator": operator, "hostname": socket.gethostname(),
                           "type": "feedback",
                           "entries": [{"category": category, "store": store_name,
                                        "content": content,
                                        "ts": cn_now().strftime("%Y-%m-%d %H:%M:%S")}]},
                     timeout=10)
    except Exception:
        pass

def _call_deepseek(messages, tools=None):
    """Call DeepSeek API (绕过系统代理)."""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 8000,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    session = http_requests.Session()
    session.trust_env = False  # 绕过系统代理
    session.proxies = {"http": None, "https": None}  # 显式禁用代理
    resp = session.post(
        DEEPSEEK_API_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=60
    )
    resp.raise_for_status()
    return resp.json()

@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Agent chat endpoint — DeepSeek with tool calling."""
    data = request.json or {}
    user_msg = data.get("message", "").strip()
    operator = data.get("operator", "")
    history = data.get("history", [])

    if not user_msg:
        return jsonify({"reply": "说点啥？", "tools_used": []}), 200

    # Build messages
    brain = _load_brain_knowledge()
    # 注入运营的完整店铺列表
    operator_stores_info = ""
    if operator:
        ops_json_path = os.path.join(os.path.dirname(__file__), "operators.json")
        try:
            with open(ops_json_path, "r", encoding="utf-8") as f:
                ops_data = json.load(f)
            if operator in ops_data:
                brands = ops_data[operator]
                total_stores = sum(len(stores) for stores in brands.values())
                lines = [f"\n## {operator}的店铺列表（共{total_stores}家店、{len(brands)}个品牌/合同）"]
                lines.append("数据口径：品牌=合同，一个品牌下有多家门店，一家门店有1-2个平台（美团/饿了么）")
                for bname, stores in brands.items():
                    store_descs = []
                    for st in stores:
                        plats = '/'.join('美团' if p['p']=='meituan' else '饿了么' for p in st.get('platforms', []))
                        store_descs.append(f"{st['store']}({plats})")
                    lines.append(f"- {bname}（{len(stores)}家店）：{', '.join(store_descs)}")
                operator_stores_info = "\n".join(lines)
        except Exception:
            pass
    system = AGENT_SYSTEM_PROMPT.replace("{operator}", (operator or "未知") + operator_stores_info).replace("{brain}", brain)

    messages = [{"role": "system", "content": system}]
    # Add recent history (skip the last user msg, we'll add it fresh)
    for h in history[:-1] if len(history) > 1 else []:
        if h.get("role") in ("user", "assistant"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_msg})

    tools_used = []

    try:
        # First call - may request tool use
        result = _call_deepseek(messages, AGENT_TOOLS)
        choice = result["choices"][0]
        msg = choice["message"]

        # Tool calling loop (max 3 rounds)
        rounds = 0
        while msg.get("tool_calls") and rounds < 3:
            rounds += 1
            messages.append(msg)

            for tc in msg["tool_calls"]:
                fn_name = tc["function"]["name"]
                fn_args = json.loads(tc["function"].get("arguments", "{}"))
                tools_used.append(fn_name)
                print(f"[chat] tool: {fn_name}({fn_args})")

                tool_result = _exec_tool(fn_name, fn_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result
                })

            # Call again with tool results
            result = _call_deepseek(messages, AGENT_TOOLS)
            choice = result["choices"][0]
            msg = choice["message"]

        reply = msg.get("content", "").strip()
        if not reply:
            reply = "查完了，但没啥特别的。"

        return jsonify({"reply": reply, "tools_used": tools_used})

    except http_requests.exceptions.Timeout:
        return jsonify({"reply": "DeepSeek响应超时，稍后再试", "tools_used": []}), 200
    except http_requests.exceptions.RequestException as e:
        print(f"[chat] DeepSeek API error: {e}")
        return jsonify({"reply": f"AI服务出错了: {str(e)[:100]}", "tools_used": []}), 200
    except Exception as e:
        print(f"[chat] error: {e}")
        return jsonify({"reply": f"出错了: {str(e)[:100]}", "tools_used": []}), 200


@app.route("/api/chat/save", methods=["POST"])
def api_chat_save():
    """保存聊天记录，供后续提炼分析"""
    data = request.json or {}
    operator = data.get("operator", "unknown")
    messages = data.get("messages", [])
    if not messages:
        return jsonify({"ok": True})

    chat_dir = os.path.join(os.path.dirname(__file__), "chat_logs")
    os.makedirs(chat_dir, exist_ok=True)

    # 按运营+日期存一个jsonl文件
    from datetime import datetime
    today = cn_now().strftime("%Y-%m-%d")
    filepath = os.path.join(chat_dir, f"{operator}_{today}.jsonl")

    with open(filepath, "a", encoding="utf-8") as f:
        for m in messages:
            line = json.dumps({"operator": operator, "role": m.get("role"), "content": m.get("content"), "ts": m.get("ts", "")}, ensure_ascii=False)
            f.write(line + "\n")

    print(f"[chat] saved {len(messages)} messages for {operator}")
    return jsonify({"ok": True})


@app.route("/api/chat/pending", methods=["GET", "POST"])
def api_chat_pending():
    """小q主动发消息 — GET返回未读消息，POST手动创建"""
    if request.method == "POST":
        data = request.json or {}
        operator = data.get("operator", "")
        content = data.get("content", "")
        if not operator or not content:
            return jsonify({"ok": False}), 400
        conn = get_db()
        conn.execute("INSERT INTO pending_messages (operator, trigger_type, trigger_key, content) VALUES (?,?,?,?)",
                     (operator, "manual", "manual", content))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    # GET
    operator = request.args.get("operator", "")
    peek = request.args.get("peek", "")  # peek=1只看数量不消费
    if not operator:
        return jsonify({"messages": [], "count": 0})

    conn = get_db()
    rows = conn.execute(
        "SELECT id, trigger_type, content, created_at FROM pending_messages WHERE operator=? AND read_at IS NULL ORDER BY id",
        (operator,)
    ).fetchall()

    if peek:
        conn.close()
        return jsonify({"messages": [], "count": len(rows)})

    messages = []
    ids = []
    for r in rows:
        messages.append({
            "id": r["id"],
            "role": "assistant",
            "content": r["content"],
            "ts": r["created_at"],
            "trigger": r["trigger_type"]
        })
        ids.append(r["id"])

    # 标记已读
    if ids:
        now = cn_now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(f"UPDATE pending_messages SET read_at=? WHERE id IN ({','.join('?' * len(ids))})", [now] + ids)
        conn.commit()
    conn.close()

    return jsonify({"messages": messages, "count": len(messages)})


def _generate_pending_content(operator, trigger_type, context):
    """调DeepSeek生成小q主动发的消息内容，像同事发微信一样自然。"""
    prompt = f"""你是小q，{operator}的运营同事。你发现了一件事要主动找{operator}聊，像微信发消息一样自然地说出来。

事件类型: {trigger_type}
具体内容: {context}

要求：
- 像微信发消息，短，直接，不用格式符号
- 不要"您好"、"请问"这种客套
- 自然地引出话题，让对方愿意接话
- 一两句话就够"""

    try:
        result = _call_deepseek([
            {"role": "system", "content": "你是小q，用微信聊天的方式说话。短句，直接，不啰嗦。"},
            {"role": "user", "content": prompt}
        ])
        reply = result["choices"][0]["message"].get("content", "").strip()
        if reply:
            return reply
    except Exception as e:
        print(f"[pending] DeepSeek生成失败: {e}")

    return None  # 生成失败就不发


# ========== TODO-OpsLog 自动匹配 ==========

# TODO的action_type → ops-log的action_type映射
TODO_OPSLOG_MATCH = {
    "改满减": ["创建活动", "修改活动", "关闭活动"],
    "改菜品": ["修改菜品", "新建菜品", "删除菜品", "改名", "改图片"],
    "改价格": ["改价", "改规格"],
    "改推广": ["修改活动", "创建活动"],
    "改活动": ["创建活动", "修改活动", "关闭活动"],
    "改店铺信息": ["修改店铺信息"],
    "改菜单结构": ["菜品排序", "新建菜品", "删除菜品", "上架", "下架"],
    "回复评价": ["回复评价"],
}

def _match_todos_with_opslog():
    """定期检查：CRM里的待做TODO是否已被ops-log匹配到执行。"""
    crm = _crm_db()
    if not crm:
        return
    try:
        # 查所有"待做"状态的TODO（有action_type的）
        todos = crm.execute("""
            SELECT t.id, t.seq, t.content, t.funnel_stage as action_type, t.status, t.updated_at,
                   s.store_name, s.branch
            FROM todos t JOIN stores s ON t.store_id = s.id
            WHERE t.status IN ('待做', '📋 待做')
              AND t.funnel_stage IS NOT NULL AND t.funnel_stage != ''
        """).fetchall()
        if not todos:
            crm.close()
            return

        conn = get_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for todo in todos:
            todo_action = todo["action_type"]
            store_name = todo["store_name"] or ""
            todo_updated = todo["updated_at"] or "2020-01-01"

            # 查ops-log里匹配的操作类型
            opslog_types = TODO_OPSLOG_MATCH.get(todo_action, [])
            if not opslog_types:
                continue

            placeholders = ",".join("?" * len(opslog_types))
            # 在TODO创建之后、店名匹配的ops-log里找
            matched = conn.execute(f"""
                SELECT id, action_type, change_summary, shop_name, received_at
                FROM logs
                WHERE action_type IN ({placeholders})
                  AND shop_name LIKE ?
                  AND received_at > ?
                ORDER BY received_at DESC LIMIT 1
            """, opslog_types + [f"%{store_name}%", todo_updated]).fetchone()

            if matched:
                summary = matched["change_summary"] or matched["action_type"]
                feedback = f"\n[自动匹配] {matched['received_at']} ops-log检测到执行: {summary}"
                crm.execute("UPDATE todos SET status='✅ 已执行', feedback=COALESCE(feedback,'')||?, updated_at=? WHERE id=?",
                            (feedback, now, todo["id"]))
                crm.execute("INSERT INTO events (store_id, event_type, content) VALUES ((SELECT store_id FROM todos WHERE id=?), 'todo_auto_matched', ?)",
                            (todo["id"], f"TODO#{todo['seq']}自动匹配ops-log: {summary}"))
                print(f"[todo-match] TODO#{todo['seq']} '{todo['content'][:20]}' ← ops-log: {summary}")

        crm.commit()
        crm.close()
        conn.close()
    except Exception as e:
        print(f"[todo-match] 匹配失败: {e}")
        import traceback; traceback.print_exc()

def _generate_pending_messages():
    """检查各数据源，调DeepSeek生成小q要主动说的话。在scheduler里定期调。"""
    cfg = load_config()
    operator = cfg.get("operator", "")
    if not operator:
        return

    conn = get_db()
    now = cn_now()

    # --- 触发器1: 新诊断报告（从CRM review_batches查，本地或远程）---
    try:
        recent_reports = []
        crm = _crm_db()
        if crm:
            # 只查最新一周，避免推太多历史消息
            latest_week = crm.execute(
                "SELECT MAX(week_date) FROM review_batches WHERE diagnosed_at IS NOT NULL"
            ).fetchone()
            lw = latest_week[0] if latest_week else None
            if lw:
                recent_reports = crm.execute("""
                    SELECT id, brand_name, diagnosis_summary, diagnosed_at
                    FROM review_batches
                    WHERE diagnosed_at IS NOT NULL
                      AND week_date = ?
                      AND operator_name = ?
                    ORDER BY diagnosed_at DESC
                """, (lw, operator)).fetchall()
            crm.close()
        else:
            # 远程: 调CRM API
            url = _discover_crm_remote()
            if url:
                try:
                    session = http_requests.Session()
                    session.trust_env = False
                    resp = session.get(f"{url}/api/review_batch/recent_diagnosed",
                                      params={"operator": operator}, timeout=10)
                    if resp.ok:
                        recent_reports = resp.json()
                except Exception as _re:
                    print(f"[pending] CRM远程查诊断失败: {_re}")

        for rpt in recent_reports:
            rpt_id = rpt["id"] if isinstance(rpt, dict) else rpt[0]
            brand = (rpt["brand_name"] if isinstance(rpt, dict) else rpt[1]) or "未知品牌"
            summary = (rpt.get("diagnosis_summary", "") if isinstance(rpt, dict) else (rpt[2] or ""))
            trigger_key = f"diagnosis_{rpt_id}"
            exists = conn.execute("SELECT 1 FROM pending_messages WHERE operator=? AND trigger_key=?",
                                  (operator, trigger_key)).fetchone()
            if not exists:
                context = f"{brand}的诊断报告刚出来"
                if summary:
                    context += f"，核心发现：{summary[:100]}"
                context += f"。需要找{operator}一起过一下诊断结果和下一步TODO"
                content = _generate_pending_content(operator, "新诊断报告", context)
                if content:
                    conn.execute("INSERT INTO pending_messages (operator, trigger_type, trigger_key, content) VALUES (?,?,?,?)",
                                 (operator, "new_diagnosis", trigger_key, content))
                    print(f"[pending] 新诊断消息: {operator} ← {brand}")
    except Exception as e:
        print(f"[pending] 检查诊断报告失败: {e}")

    # --- 触发器2: CRM TODO待办提醒 ---
    try:
        crm = _crm_db()
        if crm:
            todo_items = crm.execute("""
                SELECT t.id, t.content, t.funnel_stage, s.store_name
                FROM todos t LEFT JOIN stores s ON t.store_id = s.id
                WHERE t.status = '待做' AND s.operator_name = ?
                LIMIT 10
            """, (operator,)).fetchall()
            crm.close()

            if todo_items:
                trigger_key = f"crm_todo_{now.date().isoformat()}"
                exists = conn.execute("SELECT 1 FROM pending_messages WHERE operator=? AND trigger_key=?",
                                      (operator, trigger_key)).fetchone()
                if not exists:
                    details = []
                    for item in todo_items:
                        store = item["store_name"] or "某家店"
                        content_txt = item["content"] or "待办"
                        details.append(f"{store}：{content_txt}")
                    context = f"CRM里有{len(todo_items)}个待办还没做：{'；'.join(details[:3])}"
                    if len(todo_items) > 3:
                        context += f"……还有{len(todo_items)-3}个"
                    content = _generate_pending_content(operator, "CRM待办提醒", context)
                    if content:
                        conn.execute("INSERT INTO pending_messages (operator, trigger_type, trigger_key, content) VALUES (?,?,?,?)",
                                     (operator, "crm_todo", trigger_key, content))
                        print(f"[pending] CRM TODO消息: {operator} ← {len(todo_items)}项待办")
    except Exception as e:
        print(f"[pending] 检查CRM TODO失败: {e}")

    conn.commit()
    conn.close()


def _ensure_debug_chrome():
    """确保Chrome带debug端口在跑。没有就清零重来：杀debug Chrome → 拷贝登录态 → 重启"""
    try:
        r = subprocess.run(
            ["curl", "--noproxy", "localhost", "-s", "http://localhost:9222/json/version"],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and r.stdout.strip():
            print("[chrome] Chrome debug端口已就绪")
            return True
    except Exception:
        pass

    # === 清零重来 ===
    print("[chrome] debug端口不可用，清零重启...")
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome_path):
        print("[chrome] 找不到Chrome")
        return False

    debug_profile = os.path.expanduser("~/chrome-debug")
    default_profile = os.path.expanduser("~/Library/Application Support/Google/Chrome")

    # 1. 杀掉debug Chrome（只杀debug实例，不影响运营日常Chrome）
    try:
        subprocess.run(["pkill", "-f", "user-data-dir.*chrome-debug"], capture_output=True, timeout=5)
        import time as _t; _t.sleep(2)
    except Exception:
        pass

    # 2. 删除旧debug profile（清零）
    import shutil
    if os.path.exists(debug_profile):
        try:
            shutil.rmtree(debug_profile)
            print("[chrome] 旧debug profile已清除")
        except Exception as e:
            print(f"[chrome] 清除旧profile失败: {e}")

    # 3. 从默认Chrome profile拷贝登录态
    os.makedirs(os.path.join(debug_profile, "Default"), exist_ok=True)
    default_dir = os.path.join(default_profile, "Default")
    if os.path.isdir(default_dir):
        # 拷贝关键文件：Cookies(登录态) + Login Data + Local Storage(扩展数据)
        for item in ["Cookies", "Cookies-journal", "Login Data", "Login Data-journal",
                      "Web Data", "Web Data-journal", "Preferences", "Secure Preferences"]:
            src = os.path.join(default_dir, item)
            if os.path.exists(src):
                try:
                    shutil.copy2(src, os.path.join(debug_profile, "Default", item))
                except Exception:
                    pass
        # 拷贝Local Storage（含扩展状态）
        local_storage = os.path.join(default_dir, "Local Storage")
        if os.path.isdir(local_storage):
            try:
                shutil.copytree(local_storage, os.path.join(debug_profile, "Default", "Local Storage"))
            except Exception:
                pass
        # 拷贝Extension State
        for ext_dir_name in ["Extension State", "Extension Rules", "IndexedDB"]:
            ext_src = os.path.join(default_dir, ext_dir_name)
            if os.path.isdir(ext_src):
                try:
                    shutil.copytree(ext_src, os.path.join(debug_profile, "Default", ext_dir_name))
                except Exception:
                    pass
        # 拷贝Local State（顶层，非Default下）
        local_state = os.path.join(default_profile, "Local State")
        if os.path.exists(local_state):
            try:
                shutil.copy2(local_state, os.path.join(debug_profile, "Local State"))
            except Exception:
                pass
        print("[chrome] 登录态已从默认profile拷贝")
    else:
        print("[chrome] 未找到默认Chrome profile，debug Chrome需要手动登录")

    # 4. 构建扩展加载路径
    my_dir = os.path.dirname(os.path.abspath(__file__))
    ext_dir = os.path.join(my_dir, "extension")
    goku_dir = os.path.join(os.path.dirname(my_dir), "goku")
    load_ext_parts = []
    if os.path.isdir(ext_dir):
        load_ext_parts.append(ext_dir)
    if os.path.isdir(goku_dir):
        load_ext_parts.append(goku_dir)
    load_ext = ",".join(load_ext_parts)

    # 5. 记住当前前台app，启动后切回去
    front_app = ""
    try:
        r = subprocess.run(["osascript", "-e",
            'tell application "System Events" to get name of first process whose frontmost is true'],
            capture_output=True, text=True, timeout=3)
        front_app = r.stdout.strip()
    except Exception:
        pass

    # 6. 启动debug Chrome（独立profile，不影响运营日常Chrome）
    cmd = [chrome_path,
           "--remote-debugging-port=9222",
           "--no-first-run",
           "--no-default-browser-check",
           "--proxy-server=direct://",
           f"--user-data-dir={debug_profile}"]
    if load_ext:
        cmd.append(f"--load-extension={load_ext}")

    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[chrome] debug Chrome已启动 (profile: {debug_profile}, 扩展: {load_ext})")

    import time as _t; _t.sleep(3)

    # 切回原来的前台app
    if front_app:
        try:
            subprocess.run(["osascript", "-e", f'tell application "{front_app}" to activate'],
                          capture_output=True, timeout=3)
        except Exception:
            pass

    # 7. 验证
    try:
        r = subprocess.run(
            ["curl", "--noproxy", "localhost", "-s", "http://localhost:9222/json/version"],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and r.stdout.strip():
            print("[chrome] debug端口验证通过")
            return True
    except Exception:
        pass
    print("[chrome] 启动后debug端口仍不可用")
    return False


def _check_goku_login():
    """通过debug Chrome检查goku插件登录状态，返回 {"ok": bool, "message": str}"""
    try:
        check_script = os.path.join(WORKSPACE, "browser.py")
        result = subprocess.run(
            [PYTHON, "-c", f"""
import asyncio, sys
sys.path.insert(0, '{WORKSPACE}')
from browser import check_headless_login
from playwright.async_api import async_playwright

async def check():
    pw = await async_playwright().start()
    try:
        b = await pw.chromium.connect_over_cdp("http://localhost:9222")
        ctx = b.contexts[0] if b.contexts else await b.new_context()
        ok, msg = await check_headless_login(ctx)
        print("OK:" + msg if ok else "FAIL:" + msg)
    except Exception as e:
        print("FAIL:Chrome连接失败: " + str(e))
    finally:
        await pw.stop()

asyncio.run(check())
"""],
            capture_output=True, text=True, timeout=30, cwd=WORKSPACE
        )
        output = result.stdout.strip().split("\n")[-1] if result.stdout.strip() else ""
        if output.startswith("OK:"):
            return {"ok": True, "message": output[3:]}
        elif output.startswith("FAIL:"):
            msg = output[5:]
            # 简化消息给popup显示
            if "登录后使用" in msg:
                return {"ok": False, "message": "悟空插件未登录，请在Chrome中登录悟空后再巡检"}
            elif "登录过期" in msg:
                return {"ok": False, "message": "悟空登录过期，请在Chrome中重新登录悟空"}
            elif "打不开" in msg or "找不到" in msg:
                return {"ok": False, "message": "悟空插件打不开，请确认Chrome中已安装悟空插件"}
            elif "加载" in msg:
                return {"ok": False, "message": "悟空品牌列表没加载出来，请稍后重试"}
            return {"ok": False, "message": msg[:100]}
        else:
            stderr = result.stderr.strip()[-200:] if result.stderr else ""
            return {"ok": False, "message": f"悟空检查异常: {output[:50]} {stderr[:50]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "悟空检查超时，请确认Chrome正在运行"}
    except Exception as e:
        return {"ok": False, "message": f"悟空检查失败: {str(e)[:80]}"}


def _schedule_patrol():
    """定时巡检+预警调度器，读config决定是否执行"""
    import time as _time

    def _scheduler():
        last_patrol_date = None
        last_alert_time = None  # 上次预警巡检的时间戳
        while True:
            try:
                cfg = load_config()
                now = cn_now()
                today = now.strftime("%Y-%m-%d")
                operator = cfg.get("operator", "")

                # === 定时巡检：每天到指定时间跑一次全量 ===
                if cfg.get("patrol_enabled") and cfg.get("patrol_time") and operator:
                    patrol_time = cfg["patrol_time"]  # "10:00"
                    try:
                        hh, mm = patrol_time.split(":")
                        target = now.replace(hour=int(hh), minute=int(mm), second=0)
                    except ValueError:
                        target = now.replace(hour=10, minute=0, second=0)
                    # 在目标时间的±2分钟窗口内，且今天没跑过
                    if abs((now - target).total_seconds()) < 120 and last_patrol_date != today:
                        # 巡检前先同步最新门店
                        try:
                            from sync_operators import sync as _sync_op_single
                            _sync_op_single(operator)
                            print(f"[schedule] 已同步{operator}最新门店")
                        except Exception as _se:
                            print(f"[schedule] 同步门店失败（用本地缓存）: {_se}")
                        brands = _get_operator_brands(operator)
                        if brands:
                            last_patrol_date = today
                            print(f"[schedule] 定时巡检 {patrol_time} 运营={operator} 品牌={len(brands)}")
                            _enqueue_patrol(brands, operator, "定时巡检")

                # === 定时预警：每N分钟跑一次快速巡检（watch-once） ===
                if cfg.get("alert_enabled") and operator:
                    interval = int(cfg.get("alert_interval", 10))
                    if interval < 5:
                        interval = 5  # 最短5分钟
                    should_run = False
                    if last_alert_time is None:
                        # 首次启动后等5分钟再跑预警，让巡检先跑
                        last_alert_time = now
                    elif (now - last_alert_time).total_seconds() >= interval * 60:
                        should_run = True

                    if should_run:
                        brands = _get_operator_brands(operator)
                        if brands:
                            last_alert_time = now
                            print(f"[schedule] 定时预警(cookie) 间隔{interval}分钟 运营={operator}")
                            # 优先用cookie切店预警（快），无快照时降级为watch-once
                            snap_file = os.path.join(WORKSPACE, "ops-logger", "_cookie_snapshots.json")
                            if os.path.exists(snap_file):
                                alert_script = os.path.join(WORKSPACE, "run_alert_cookie.py")
                                _enqueue_patrol(brands, operator, "定时预警", script=alert_script, extra_args=[])
                            else:
                                alert_script = os.path.join(WORKSPACE, "run_fast.py")
                                _enqueue_patrol(brands, operator, "定时预警", script=alert_script, extra_args=["--watch-once"])

                # === 拉取远程指令（管理员下发的stop/restart） ===
                if operator:
                    try:
                        remote_url = _discover_crm_remote()
                        if remote_url:
                            _s = http_requests.Session()
                            _s.trust_env = False
                            resp = _s.get(f"{remote_url}/api/commands/pull?operator={operator}", timeout=5)
                            if resp.ok:
                                cmds = resp.json().get("commands", [])
                                for c in cmds:
                                    print(f"[cmd] 收到指令: {c['cmd']} (来自管理员 {c['ts']})")
                                    if c["cmd"] == "stop":
                                        # 停止当前巡检
                                        with _patrol_lock:
                                            pid = _patrol_state.get("pid")
                                            if _patrol_state["state"] == "running" and pid:
                                                try:
                                                    import signal
                                                    os.kill(pid, signal.SIGTERM)
                                                    print(f"[cmd] 已停止巡检进程 {pid}")
                                                except Exception:
                                                    pass
                                                _patrol_state["state"] = "idle"
                                                _patrol_state["message"] = "管理员远程停止"
                                                _patrol_state["pid"] = None
                                        _cleanup_headless()
                                    elif c["cmd"] == "restart":
                                        # 重启server自身
                                        print("[cmd] 收到restart指令，正在重启...")
                                        _cleanup_headless()
                                        os.execv(sys.executable, [sys.executable] + sys.argv)
                    except Exception as _ce:
                        pass  # 拉指令失败不影响正常调度

                # === 每天6点同步operators.json（从PA拉最新运营-店铺关系） ===
                if now.hour == 6 and now.minute < 2 and getattr(_scheduler, '_last_sync_date', None) != today:
                    _scheduler._last_sync_date = today
                    try:
                        from sync_operators import sync as _sync_op
                        print("[schedule] 开始每日同步operators.json...")
                        _sync_op()
                        print("[schedule] operators.json同步完成")
                    except Exception as _se:
                        print(f"[schedule] operators.json同步失败: {_se}")

                # === 每5分钟上报操作日志（积压补发）+ 回填空店名/菜名 ===
                if not hasattr(_scheduler, '_last_ops_report'):
                    _scheduler._last_ops_report = now
                if (now - _scheduler._last_ops_report).total_seconds() >= 300:
                    _scheduler._last_ops_report = now
                    _report_logs("ops")
                    _report_logs("chat")
                    _backfill_log_names()

                # === 每30分钟检查一次，生成小q主动消息 ===
                if not hasattr(_scheduler, '_last_pending_check'):
                    _scheduler._last_pending_check = now
                if (now - _scheduler._last_pending_check).total_seconds() >= 1800:
                    _scheduler._last_pending_check = now
                    try:
                        _match_todos_with_opslog()
                    except Exception as _me:
                        print(f"[schedule] TODO匹配失败: {_me}")
                    try:
                        _generate_pending_messages()
                    except Exception as _pe:
                        print(f"[schedule] 生成主动消息失败: {_pe}")

            except Exception as e:
                print(f"[schedule] 调度器异常: {e}")

            _time.sleep(60)  # 每分钟检查一次

    t = threading.Thread(target=_scheduler, daemon=True)
    t.start()
    print("[schedule] 定时调度器已启动")


if __name__ == "__main__":
    # 启动前确保端口可用，防止死循环
    import signal
    _port = 5500
    _pids = subprocess.run(["lsof", "-i", f":{_port}", "-t"], capture_output=True, text=True).stdout.strip()
    if _pids:
        for _p in _pids.split("\n"):
            try:
                os.kill(int(_p), signal.SIGKILL)
            except:
                pass
        import time; time.sleep(1)

    init_db()
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
    _auto_backup()
    _auto_collect_due()
    _ensure_debug_chrome()
    _schedule_patrol()
    app.run(host="0.0.0.0", port=5500, debug=False)
