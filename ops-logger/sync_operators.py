"""
sync_operators.py - 从PA数据库拉运营-品牌-店铺关系，存入本地SQLite + operators.json
用法: python3 sync_operators.py [运营名字]
  不传名字 = 同步全部运营
  传名字 = 只查这个人的品牌和店铺
"""
import sys, os, json, sqlite3
import pymysql

PA_HOST = "rm-uf6e0001sq5g9foel.mysql.rds.aliyuncs.com"
PA_PORT = 3306
PA_USER = "pa_ai_read"
PA_PASS = "HV)b2ZNxd_)(SLtBmLg--2rV"
PA_DB = "inca-saas07"

DB_PATH = os.path.join(os.path.dirname(__file__), "ops_logs.db")

SQL_BASE = """
SELECT
    s.operator,
    s.name AS brand_name,
    s.id AS subscriber_id,
    ts.name AS shop_name,
    ts.id AS shop_id,
    ts.platform
FROM subscribers s
JOIN contracts c ON c.subscriber_id = s.id
    AND c.start_at <= NOW() AND c.end_at >= NOW()
JOIN takeaway_shops ts ON ts.subscriber_id = s.id
WHERE s.operator IS NOT NULL AND s.operator != ''
"""

def get_pa_conn():
    return pymysql.connect(
        host=PA_HOST, port=PA_PORT, user=PA_USER,
        password=PA_PASS, database=PA_DB,
        charset="utf8mb4", connect_timeout=10
    )

def init_local_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operator_stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT,
            brand_name TEXT,
            subscriber_id INTEGER,
            shop_name TEXT,
            shop_id INTEGER,
            platform TEXT,
            synced_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()

def sync(operator_name=None):
    # 查PA
    sql = SQL_BASE
    params = ()
    if operator_name:
        sql += " AND s.operator = %s"
        params = (operator_name,)
    sql += " ORDER BY s.operator, s.name, ts.name"

    pa = get_pa_conn()
    try:
        with pa.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        pa.close()

    if not rows:
        print(f"没查到数据" + (f"（运营: {operator_name}）" if operator_name else ""))
        return []

    # 写本地
    local = sqlite3.connect(DB_PATH)
    init_local_table(local)

    if operator_name:
        local.execute("DELETE FROM operator_stores WHERE operator=?", (operator_name,))
    else:
        local.execute("DELETE FROM operator_stores")

    for r in rows:
        local.execute(
            "INSERT INTO operator_stores (operator, brand_name, subscriber_id, shop_name, shop_id, platform) VALUES (?,?,?,?,?,?)",
            r
        )
    local.commit()

    # 汇总打印
    brands = {}
    for op, brand, sid, shop, shop_id, plat in rows:
        key = (op, brand)
        if key not in brands:
            brands[key] = []
        brands[key].append((shop, plat, shop_id))

    operators = {}
    for (op, brand), shops in brands.items():
        if op not in operators:
            operators[op] = {}
        operators[op][brand] = shops

    for op, brand_dict in sorted(operators.items()):
        total_shops = sum(len(v) for v in brand_dict.values())
        print(f"\n{'='*50}")
        print(f"  {op}  |  {len(brand_dict)}个品牌  |  {total_shops}家店")
        print(f"{'='*50}")
        for brand, shops in sorted(brand_dict.items()):
            print(f"\n  {brand} ({len(shops)}家)")
            for shop, plat, _ in shops:
                print(f"    - {shop}  [{plat}]")

    local.close()
    print(f"\n--- 同步完成: {len(rows)}条记录 ---")

    # 生成 operators.json（仅全量同步时生成）
    if not operator_name:
        _generate_json(operators)

    return rows


def _generate_json(operators_dict):
    """把operators字典写成popup用的operators.json格式"""
    # 格式: { "运营名": { "品牌名": [{"shop": "店名", "id": shop_id, "p": "meituan/eleme"}, ...] } }
    result = {}
    for op, brand_dict in sorted(operators_dict.items()):
        result[op] = {}
        for brand, shops in sorted(brand_dict.items()):
            result[op][brand] = [
                {"shop": shop, "id": shop_id, "p": plat}
                for shop, plat, shop_id in shops
            ]

    base_dir = os.path.dirname(__file__)
    for subdir in [".", "extension"]:
        path = os.path.join(base_dir, subdir, "operators.json")
        if os.path.isdir(os.path.join(base_dir, subdir)):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
            print(f"[sync] 已更新 {path}")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else None
    if name:
        print(f"查询运营: {name}")
    else:
        print("同步全部运营...")
    sync(name)
