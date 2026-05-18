"""
Ops Logger Server v2.0 - 接收运营操作日志 + 结构化解析 + 改前值追踪
端口: 5500
"""
import json, sqlite3, os, re, sys
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string

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
    """Get tracking records with log details. ?status=pending|done|disabled&log_id=X"""
    conn = get_db()
    status = request.args.get("status", "")
    log_id = request.args.get("log_id", "")
    base_sql = """SELECT ct.*, l.shop_name, l.change_summary, l.item_name, l.action_type as log_action_type
                  FROM change_tracking ct LEFT JOIN logs l ON ct.log_id = l.id"""
    if log_id:
        rows = conn.execute(base_sql + " WHERE ct.log_id=? ORDER BY ct.check_date", (log_id,)).fetchall()
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
# 读上层 patrol_db.py 的数据，不修改原agent代码

PATROL_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "patrol.db")

def _patrol_conn():
    """连接巡检数据库（只读），表不存在返回None"""
    if not os.path.exists(PATROL_DB):
        return None
    try:
        conn = sqlite3.connect(PATROL_DB)
        conn.row_factory = sqlite3.Row
        # 检查表是否存在
        t = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='patrol_snapshots'").fetchone()
        if not t:
            conn.close()
            return None
        return conn
    except Exception:
        return None

@app.route("/api/daily")
def daily_report():
    """日报API — 返回最近一次巡检的结果，按店铺分组"""
    conn = _patrol_conn()
    if not conn:
        return jsonify({"error": "no_patrol_db", "stores": []})

    # 找最近一次巡检的时间戳
    row = conn.execute("SELECT MAX(ts) as latest FROM patrol_snapshots").fetchone()
    if not row or not row["latest"]:
        conn.close()
        return jsonify({"ts": None, "stores": []})

    latest_ts = row["latest"]
    # 取该时间戳的所有快照
    snaps = conn.execute("""
        SELECT id, ts, store, platform, bad_review_count, notice_count,
               expiring_count, promo_balance, promo_daily_spend,
               has_auth_issue, has_verify_issue
        FROM patrol_snapshots WHERE ts = ?
        ORDER BY store, platform
    """, (latest_ts,)).fetchall()

    stores = {}
    for s in snaps:
        store = s["store"]
        if store not in stores:
            stores[store] = {"store": store, "platforms": []}

        platform_data = {
            "platform": s["platform"],
            "bad_review_count": s["bad_review_count"],
            "notice_count": s["notice_count"],
            "expiring_count": s["expiring_count"],
            "promo_balance": s["promo_balance"],
            "promo_daily_spend": s["promo_daily_spend"],
            "has_auth_issue": s["has_auth_issue"],
            "has_verify_issue": s["has_verify_issue"],
            "bad_reviews": [],
            "activities": [],
        }

        # 差评明细
        reviews = conn.execute(
            "SELECT stars, review_date, comment, foods FROM bad_reviews WHERE snapshot_id=?",
            (s["id"],)
        ).fetchall()
        for r in reviews:
            platform_data["bad_reviews"].append({
                "stars": r["stars"],
                "date": r["review_date"],
                "comment": r["comment"],
                "foods": r["foods"],
            })

        # 活动到期
        acts = conn.execute(
            "SELECT name, days_left FROM activities WHERE snapshot_id=?",
            (s["id"],)
        ).fetchall()
        for a in acts:
            platform_data["activities"].append({
                "name": a["name"],
                "days_left": a["days_left"],
            })

        stores[store]["platforms"].append(platform_data)

    conn.close()
    return jsonify({"ts": latest_ts, "stores": list(stores.values())})


@app.route("/api/alerts")
def alerts():
    """预警API — 返回需要关注的问题列表"""
    result = []

    # 1. 从巡检数据找预警
    conn = _patrol_conn()
    if conn:
        # 最近一次巡检
        row = conn.execute("SELECT MAX(ts) as latest FROM patrol_snapshots").fetchone()
        if row and row["latest"]:
            latest_ts = row["latest"]
            snaps = conn.execute("""
                SELECT id, ts, store, platform, bad_review_count, notice_count,
                       expiring_count, promo_balance, promo_daily_spend,
                       has_auth_issue, has_verify_issue
                FROM patrol_snapshots WHERE ts = ?
            """, (latest_ts,)).fetchall()

            for s in snaps:
                # 差评预警
                if s["bad_review_count"] > 0:
                    reviews = conn.execute(
                        "SELECT stars, comment FROM bad_reviews WHERE snapshot_id=? ORDER BY stars",
                        (s["id"],)
                    ).fetchall()
                    comments = [f'{r["stars"]}星 "{(r["comment"] or "")[:30]}"' for r in reviews[:3]]
                    result.append({
                        "type": "bad_review",
                        "level": "red",
                        "store": s["store"],
                        "platform": s["platform"],
                        "msg": f'{s["bad_review_count"]}条差评',
                        "detail": "; ".join(comments),
                        "ts": latest_ts,
                    })

                # 活动到期预警
                if s["expiring_count"] > 0:
                    acts = conn.execute(
                        "SELECT name, days_left FROM activities WHERE snapshot_id=? ORDER BY days_left",
                        (s["id"],)
                    ).fetchall()
                    for a in acts:
                        level = "red" if (a["days_left"] or 99) <= 1 else "yellow"
                        result.append({
                            "type": "expiring",
                            "level": level,
                            "store": s["store"],
                            "platform": s["platform"],
                            "msg": f'{a["name"]} {a["days_left"]}天后到期',
                            "detail": "",
                            "ts": latest_ts,
                        })

                # 推广余额预警
                if s["promo_balance"] is not None and s["promo_daily_spend"] and s["promo_daily_spend"] > 0:
                    days_left = s["promo_balance"] / s["promo_daily_spend"]
                    if days_left < 3:
                        level = "red" if days_left < 1 else "yellow"
                        result.append({
                            "type": "promo",
                            "level": level,
                            "store": s["store"],
                            "platform": s["platform"],
                            "msg": f'推广余额¥{s["promo_balance"]:.0f}',
                            "detail": f'日均消费¥{s["promo_daily_spend"]:.0f} 预计{days_left:.1f}天用完',
                            "ts": latest_ts,
                        })

                # 授权/验证问题
                if s["has_auth_issue"]:
                    result.append({
                        "type": "auth",
                        "level": "red",
                        "store": s["store"],
                        "platform": s["platform"],
                        "msg": "授权异常",
                        "detail": "",
                        "ts": latest_ts,
                    })
        conn.close()

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
                        ["/opt/homebrew/bin/python3", "collect_tracking.py"],
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

# ========== Agent Integration ==========

import subprocess as _sp
import threading

_PATROL_PROC = None  # running patrol subprocess
_PATROL_STATUS = {"state": "idle", "started_at": None, "brands": [], "message": ""}
_PATROL_LOCK = threading.Lock()
AGENT_DIR = os.path.dirname(os.path.dirname(__file__))  # store-monitor root


def _run_patrol_thread(brands):
    """Run run_fast.py in background thread, update status."""
    global _PATROL_PROC
    try:
        with _PATROL_LOCK:
            _PATROL_STATUS["state"] = "running"
            _PATROL_STATUS["message"] = f"巡检中: {', '.join(brands)}"
        cmd = [sys.executable, os.path.join(AGENT_DIR, "run_fast.py")] + brands
        proc = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.STDOUT, cwd=AGENT_DIR, text=True)
        _PATROL_PROC = proc
        output_lines = []
        for line in proc.stdout:
            output_lines.append(line.rstrip())
            if len(output_lines) > 50:
                output_lines = output_lines[-50:]
            with _PATROL_LOCK:
                _PATROL_STATUS["message"] = output_lines[-1] if output_lines else ""
        proc.wait()
        with _PATROL_LOCK:
            if proc.returncode == 0:
                _PATROL_STATUS["state"] = "done"
                _PATROL_STATUS["message"] = "巡检完成"
            else:
                _PATROL_STATUS["state"] = "error"
                _PATROL_STATUS["message"] = f"巡检异常 (code {proc.returncode})"
    except Exception as e:
        with _PATROL_LOCK:
            _PATROL_STATUS["state"] = "error"
            _PATROL_STATUS["message"] = str(e)
    finally:
        _PATROL_PROC = None


@app.route("/api/settings", methods=["GET"])
def get_settings():
    cfg = load_config()
    return jsonify(cfg.get("settings", {
        "patrol_enabled": True,
        "alert_enabled": True,
        "patrol_time": "10:00",
        "alert_interval": 30,
    }))


@app.route("/api/settings", methods=["POST"])
def save_settings():
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    cfg["settings"] = data
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/patrol/brands", methods=["GET"])
def get_patrol_brands():
    """Get saved brand list for patrol."""
    cfg = load_config()
    return jsonify({"brands": cfg.get("patrol_brands", [])})


@app.route("/api/patrol/brands", methods=["POST"])
def save_patrol_brands():
    """Save brand list for patrol."""
    data = request.get_json(silent=True) or {}
    brands = data.get("brands", [])
    cfg = load_config()
    cfg["patrol_brands"] = brands
    save_config(cfg)
    return jsonify({"ok": True, "brands": brands})


@app.route("/api/patrol/start", methods=["POST"])
def start_patrol():
    """Start a patrol run. Body: {"brands": ["品牌1", "品牌2"]}"""
    global _PATROL_PROC
    with _PATROL_LOCK:
        if _PATROL_STATUS["state"] == "running":
            return jsonify({"ok": False, "error": "patrol_running", "message": "巡检正在进行中"})

    data = request.get_json(silent=True) or {}
    brands = data.get("brands", [])
    # "all" means use saved brands
    if not brands or brands == ["all"]:
        cfg = load_config()
        brands = cfg.get("patrol_brands", [])
    if not brands:
        return jsonify({"ok": False, "error": "no_brands", "message": "请先设置巡检品牌"})

    with _PATROL_LOCK:
        _PATROL_STATUS["state"] = "running"
        _PATROL_STATUS["started_at"] = datetime.now().isoformat()
        _PATROL_STATUS["brands"] = brands
        _PATROL_STATUS["message"] = "启动中..."

    t = threading.Thread(target=_run_patrol_thread, args=(brands,), daemon=True)
    t.start()
    return jsonify({"ok": True, "message": f"巡检已启动: {', '.join(brands)}"})


@app.route("/api/patrol/status")
def patrol_status():
    """Get current patrol status."""
    with _PATROL_LOCK:
        return jsonify(dict(_PATROL_STATUS))


@app.route("/api/agent/status")
def agent_status():
    """Check agent health: browser running? server up? run_fast.py exists?"""
    info = {
        "server": True,
        "has_run_fast": os.path.exists(os.path.join(AGENT_DIR, "run_fast.py")),
        "has_patrol_db": os.path.exists(PATROL_DB),
        "patrol": dict(_PATROL_STATUS),
    }
    # Check if Chrome debug port is listening
    try:
        r = _sp.run(["curl", "--noproxy", "localhost", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                      "http://localhost:9222/json/version"], capture_output=True, text=True, timeout=2)
        info["browser"] = r.stdout.strip() == "200"
    except Exception:
        info["browser"] = False
    return jsonify(info)


if __name__ == "__main__":
    init_db()
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
    _auto_backup()
    _auto_collect_due()
    app.run(host="0.0.0.0", port=5500, debug=False)
