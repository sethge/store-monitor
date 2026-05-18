#!/usr/bin/env python3
"""
从PA数据库同步运营-店铺关系到本地SQLite
用法: python3 sync_operators.py
"""
import sqlite3, os, sys

DB_PATH = os.path.join(os.path.dirname(__file__), "ops_logs.db")
PA_HOST = "rm-uf6e0001sq5g9foel.mysql.rds.aliyuncs.com"
PA_USER = "pa_ai_read"
PA_PASS = "HV)b2ZNxd_)(SLtBmLg--2rV"
PA_DB = "inca-saas07"

def sync():
    try:
        import pymysql
    except ImportError:
        print("pymysql not installed, run: pip3 install pymysql")
        sys.exit(1)

    # Connect PA
    print("Connecting to PA database...")
    conn_pa = pymysql.connect(
        host=PA_HOST, port=3306, user=PA_USER, password=PA_PASS,
        database=PA_DB, connect_timeout=10, read_timeout=30, charset="utf8mb4"
    )
    cur = conn_pa.cursor()
    cur.execute("""
        SELECT DISTINCT u.name, s.name, s.id, ts.name, ts.id, ts.platform
        FROM subscribers s
        JOIN users u ON s.operator = u.name AND u.deleted_at IS NULL
        JOIN contracts c ON c.subscriber_id = s.id AND c.start_at <= NOW() AND c.end_at >= NOW()
        LEFT JOIN takeaway_shops ts ON ts.subscriber_id = s.id AND ts.deleted_at IS NULL
        ORDER BY u.name, s.name, ts.platform, ts.name
    """)
    rows = cur.fetchall()
    conn_pa.close()
    print(f"PA: {len(rows)} rows")

    # Write to local SQLite
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operator_stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT, brand_name TEXT, subscriber_id INTEGER,
            shop_name TEXT, shop_id INTEGER, platform TEXT,
            synced_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("DELETE FROM operator_stores")
    conn.executemany(
        "INSERT INTO operator_stores (operator, brand_name, subscriber_id, shop_name, shop_id, platform) VALUES (?,?,?,?,?,?)",
        rows
    )
    conn.commit()

    # Summary
    ops = conn.execute("SELECT operator, COUNT(DISTINCT brand_name), COUNT(DISTINCT shop_id) FROM operator_stores GROUP BY operator").fetchall()
    print(f"\nSynced: {len(ops)} operators")
    for op, brands, shops in ops:
        print(f"  {op}: {brands} brands, {shops} shops")
    conn.close()

if __name__ == "__main__":
    sync()
