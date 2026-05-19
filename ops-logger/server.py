"""
Ops Logger Server v4.0 - 接收运营操作日志 + 结构化解析 + 改前值追踪 + 巡检/预警直执行
端口: 5500
"""
import json, sqlite3, os, re, subprocess, threading, sys
import requests as http_requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string

PYTHON = sys.executable

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

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
            received_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
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
        }
        for col, sql in migrations.items():
            if col not in cols:
                conn.execute(sql)
    except Exception as e:
        print(f"[migration] {e}")
    # food_snapshot table (created by init_snapshot.py, ensure it exists)
    # Change tracking: auto follow-up at T+3 and T+7
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

        # Lookup shop name from cache if not provided
        if shop_id and not shop_name:
            cached_shop = conn.execute("SELECT shop_name FROM shop_cache WHERE shop_id=?", (shop_id,)).fetchone()
            if cached_shop:
                shop_name = cached_shop["shop_name"]

        # Save shop name to cache
        if shop_id and shop_name:
            conn.execute(
                "INSERT OR REPLACE INTO shop_cache (shop_id, shop_name, platform, updated_at) VALUES (?,?,?,?)",
                (shop_id, shop_name, platform, datetime.now().isoformat())
            )

        api_method = log.get("apiMethod", "")

        # Server-side extraction from body as fallback
        if not item_id:
            item_id = extract_item_id_from_body(api_method, body)
        if not item_name:
            item_name = extract_item_name_from_body(api_method, body)

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
                     json.dumps(cache_data, ensure_ascii=False), datetime.now().isoformat())
                )

        conn.execute(
            """INSERT INTO logs (operator, timestamp, api_method, url, body_full, platform,
                shop_id, shop_name, tab_id, item_id, item_name, action_type, action_detail, before_snapshot, change_summary)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (operator, log.get("timestamp", ""), api_method, url[:500], body_str,
             platform, shop_id, shop_name, log.get("tab_id", 0), item_id, item_name,
             action_type, action_detail, before_snapshot, change_summary)
        )
        log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Auto-create T+3 and T+7 tracking for meaningful operations
        _SKIP_TRACKING = {"回复评价", "菜品排序", "修改店铺信息", "排序分类"}
        if action_type and action_type not in _SKIP_TRACKING and shop_id:
            ts = log.get("timestamp", "") or datetime.now().isoformat()
            try:
                base = datetime.fromisoformat(ts.replace("Z", "+00:00")).date() if "T" in ts else datetime.now().date()
            except:
                base = datetime.now().date()
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
    """Get tracking records. ?status=pending|done|disabled&log_id=X"""
    conn = get_db()
    status = request.args.get("status", "")
    log_id = request.args.get("log_id", "")
    if log_id:
        rows = conn.execute("SELECT * FROM change_tracking WHERE log_id=? ORDER BY check_date", (log_id,)).fetchall()
    elif status:
        rows = conn.execute("SELECT * FROM change_tracking WHERE status=? ORDER BY check_date LIMIT 200", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM change_tracking ORDER BY id DESC LIMIT 200").fetchall()
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
    today = datetime.now().date().isoformat()
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
        (json.dumps(data.get("metrics", {}), ensure_ascii=False), datetime.now().isoformat(), tid)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/tracking/summary", methods=["GET"])
def tracking_summary():
    """Dashboard summary: count by status, upcoming checks."""
    conn = get_db()
    today = datetime.now().date().isoformat()

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
        (today, (datetime.now().date() + timedelta(days=7)).isoformat())
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
    now = datetime.now().isoformat()

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

@app.route("/api/extension/version")
def extension_version():
    manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
    try:
        with open(manifest_path) as f:
            m = json.load(f)
        return jsonify({"version": m.get("version", "0")})
    except:
        return jsonify({"version": "0"})

@app.route("/download/<path:filename>")
def download_file(filename):
    from flask import send_from_directory
    return send_from_directory(os.path.dirname(__file__), filename)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

# ========== Patrol APIs (日报 + 预警) ==========
# 读 patrol_result.json（run_all_fast.py巡检结束后写入）

PATROL_RESULT = os.path.join(os.path.expanduser("~/.qclaw/workspace/store-monitor"), "ops-logger", "patrol_result.json")

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
    """日报API — 读patrol_result.json"""
    data = _load_patrol_result()
    if not data:
        return jsonify({"ts": None, "stores": []})

    ts = data.get("ts", "")
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
        store["platforms"] = list(by_platform.values())
        stores.append(store)

    # 没有问题的品牌也要显示（从巡检结果里拿品牌数）
    return jsonify({"ts": ts, "stores": stores, "brands": data.get("brands", 0), "duration": data.get("duration", 0)})


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
                    comments = []
                    for d in details[:3]:
                        if isinstance(d, dict):
                            comments.append(f'{d.get("stars","")}星 "{(d.get("comment",""))[:30]}"')
                    result.append({"type": "bad_review", "level": "red", "store": store_name,
                                   "platform": platform, "msg": item.get("msg", ""), "detail": "; ".join(comments), "ts": ts})
                elif t == "expiring":
                    for d in item.get("details", []):
                        if isinstance(d, dict):
                            days = d.get("days", 99)
                            level = "red" if days <= 1 else "yellow"
                            result.append({"type": "expiring", "level": level, "store": store_name,
                                           "platform": platform, "msg": f'{d.get("name","")} {days}天后到期', "detail": "", "ts": ts})
                elif t == "promo":
                    result.append({"type": "promo", "level": "yellow", "store": store_name,
                                   "platform": platform, "msg": item.get("msg", ""), "detail": "", "ts": ts})
                elif t == "auth":
                    result.append({"type": "auth", "level": "red", "store": store_name,
                                   "platform": platform, "msg": "授权异常", "detail": "", "ts": ts})
                elif t == "error":
                    result.append({"type": "error", "level": "yellow", "store": store_name,
                                   "platform": platform, "msg": item.get("msg", ""), "detail": "", "ts": ts})
                elif t == "notice":
                    details = item.get("details", [])
                    # 只把重要通知（非配送范围类）加入预警
                    important = [d for d in details if isinstance(d, dict) and "配送范围" not in d.get("title", "")]
                    if important:
                        titles = "; ".join(d.get("title", "")[:20] for d in important[:3])
                        result.append({"type": "notice", "level": "blue", "store": store_name,
                                       "platform": platform, "msg": f"{len(important)}条通知", "detail": titles, "ts": ts})

    # 2. 从操作追踪找到期TODO
    ops_conn = get_db()
    today = datetime.now().date().isoformat()
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
            "ts": t["op_ts"] or "",
        })
    ops_conn.close()

    # 按level排序: red > yellow > blue
    level_order = {"red": 0, "yellow": 1, "blue": 2}
    result.sort(key=lambda x: level_order.get(x["level"], 9))

    return jsonify(result)


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
        (feedback, datetime.now().isoformat(), tracking_id)
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
                today = datetime.now().date().isoformat()
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
        today = datetime.now().strftime("%Y%m%d")
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

WORKSPACE = os.path.expanduser("~/.qclaw/workspace/store-monitor")
_patrol_state = {"state": "idle", "message": "", "pid": None}
_patrol_lock = threading.Lock()

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
    return jsonify({"has_run_fast": has_run_fast, "patrol": patrol_clean})


@app.route("/api/patrol/log")
def api_patrol_log():
    """查看巡检实时输出"""
    with _patrol_lock:
        return jsonify({
            "state": _patrol_state["state"],
            "message": _patrol_state["message"],
            "log": _patrol_state.get("log", ""),
        })


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


@app.route("/api/patrol/start", methods=["POST"])
def api_patrol_start():
    """启动巡检（根据运营名自动查品牌，直接subprocess调run_all_fast.py）"""
    data = request.get_json(silent=True) or {}
    operator = data.get("operator", "")
    brands = data.get("brands", [])

    # 如果传了运营名，自动查品牌
    if operator and not brands:
        brands = _get_operator_brands(operator)
        print(f"[patrol] 运营={operator}, 品牌={brands}")

    if not brands:
        return jsonify({"error": "no_brands", "message": f"没找到{operator}的品牌"}), 400

    with _patrol_lock:
        if _patrol_state["state"] == "running":
            return jsonify({"ok": False, "message": "巡检已在运行中"})

    script = os.path.join(WORKSPACE, "run_all_fast.py")
    if not os.path.exists(script):
        return jsonify({"ok": False, "message": "巡检脚本不存在"}), 500

    def _run_patrol():
        with _patrol_lock:
            _patrol_state["state"] = "running"
            _patrol_state["message"] = f"巡检 {', '.join(brands)}..."
            _patrol_state["log"] = ""
        print(f"[patrol] 启动: {brands}, 脚本: {script}")
        try:
            proc = subprocess.Popen(
                [PYTHON, script] + brands,
                cwd=WORKSPACE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            with _patrol_lock:
                _patrol_state["pid"] = proc.pid
            # 实时读输出
            output_lines = []
            for line in proc.stdout:
                text = line.decode("utf-8", errors="replace").rstrip()
                output_lines.append(text)
                print(f"[patrol] {text}")
                with _patrol_lock:
                    _patrol_state["message"] = text[:100] or _patrol_state["message"]
                    # 保留最后50行
                    _patrol_state["log"] = "\n".join(output_lines[-50:])
            proc.wait(timeout=600)
            with _patrol_lock:
                if proc.returncode == 0:
                    _patrol_state["state"] = "done"
                    _patrol_state["message"] = "巡检完成"
                else:
                    _patrol_state["state"] = "error"
                    _patrol_state["message"] = f"巡检异常(code={proc.returncode})"
                _patrol_state["pid"] = None
            print(f"[patrol] 结束: code={proc.returncode}")
        except subprocess.TimeoutExpired:
            proc.kill()
            with _patrol_lock:
                _patrol_state["state"] = "error"
                _patrol_state["message"] = "巡检超时(10分钟)"
                _patrol_state["pid"] = None
            print("[patrol] 超时")
        except Exception as e:
            with _patrol_lock:
                _patrol_state["state"] = "error"
                _patrol_state["message"] = str(e)[:100]
                _patrol_state["pid"] = None
            print(f"[patrol] 异常: {e}")

    t = threading.Thread(target=_run_patrol, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": f"巡检已启动: {', '.join(brands)}"})


# ========== Settings ==========

@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    cfg = load_config()
    return jsonify({
        "patrol_enabled": cfg.get("patrol_enabled", True),
        "alert_enabled": cfg.get("alert_enabled", True),
        "patrol_time": cfg.get("patrol_time", "10:00"),
        "alert_interval": cfg.get("alert_interval", 30),
    })


@app.route("/api/settings", methods=["POST"])
def api_settings_set():
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    for key in ("patrol_enabled", "alert_enabled", "patrol_time", "alert_interval"):
        if key in data:
            cfg[key] = data[key]
    save_config(cfg)
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

AGENT_SYSTEM_PROMPT = """你是小q，外卖运营团队的AI助手。你跑在服务端，能查数据库、看日志、分析预警。
说话风格：像微信聊天，短句直接，不啰嗦，不说技术术语。
你有以下工具可以调用，根据用户问题选择合适的工具。"""

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
            "description": "查询已缓存的店铺列表",
            "parameters": {"type": "object", "properties": {}, "required": []}
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
            rows = conn.execute("SELECT shop_id, shop_name, platform FROM shop_cache ORDER BY shop_name").fetchall()
            if not rows:
                return "还没有缓存任何店铺"
            return json.dumps([dict(r) for r in rows], ensure_ascii=False)

        else:
            return f"未知工具: {name}"
    except Exception as e:
        return f"查询出错: {str(e)}"
    finally:
        conn.close()

def _call_deepseek(messages, tools=None):
    """Call DeepSeek API."""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2000,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    resp = http_requests.post(
        DEEPSEEK_API_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=30
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
    system = AGENT_SYSTEM_PROMPT
    if operator:
        system += f"\n当前运营: {operator}"

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


if __name__ == "__main__":
    init_db()
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
    _auto_backup()
    _auto_collect_due()
    app.run(host="0.0.0.0", port=5500, debug=False)
