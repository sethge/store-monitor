#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
巡检数据快照 — SQLite 存储层

每次巡检后自动存数据，积累历史趋势。
查询时能回答：这家店上周差评几条？推广余额在涨还是降？评分什么走势？

表结构：
  patrol_snapshots  — 每次巡检的汇总（一行 = 一个店+一个平台）
  bad_reviews       — 差评明细
  notices           — 通知明细
  activities        — 活动到期明细
"""
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "patrol.db"


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_tables(conn)
    return conn


def _init_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS patrol_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,                  -- 巡检时间 YYYY-MM-DD HH:MM
        store TEXT NOT NULL,               -- 店铺显示名
        platform TEXT NOT NULL,            -- 美团/饿了么
        bad_review_count INTEGER DEFAULT 0,
        notice_count INTEGER DEFAULT 0,
        expiring_count INTEGER DEFAULT 0,
        promo_balance REAL,                -- 推广余额（元），NULL=未采集
        promo_daily_spend REAL,            -- 日均消费（元）
        has_auth_issue INTEGER DEFAULT 0,
        has_verify_issue INTEGER DEFAULT 0,
        raw_json TEXT                      -- 完整原始数据备份
    );

    CREATE TABLE IF NOT EXISTS bad_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER NOT NULL,
        stars INTEGER,
        review_date TEXT,
        comment TEXT,
        foods TEXT,                        -- JSON array
        FOREIGN KEY (snapshot_id) REFERENCES patrol_snapshots(id)
    );

    CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER NOT NULL,
        title TEXT,
        content TEXT,
        category TEXT,
        notice_time TEXT,
        FOREIGN KEY (snapshot_id) REFERENCES patrol_snapshots(id)
    );

    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER NOT NULL,
        name TEXT,
        days_left INTEGER,
        FOREIGN KEY (snapshot_id) REFERENCES patrol_snapshots(id)
    );

    CREATE INDEX IF NOT EXISTS idx_snap_store_ts ON patrol_snapshots(store, ts);
    CREATE INDEX IF NOT EXISTS idx_snap_ts ON patrol_snapshots(ts);
    """)
    conn.commit()


def save_snapshot(all_issues):
    """
    巡检完成后调用。all_issues 是 run_once() 的返回值：
    {store_name: [{platform, type, msg, details}, ...]}
    """
    if not all_issues:
        return 0

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = _conn()
    count = 0

    for store, items in all_issues.items():
        # 按平台分组
        by_platform = {}
        for item in items:
            p = item.get("platform", "未知")
            by_platform.setdefault(p, []).append(item)

        for platform, pitems in by_platform.items():
            bad_reviews = []
            notice_list = []
            exp_list = []
            promo_bal = None
            promo_median = None
            has_auth = 0
            has_verify = 0

            for item in pitems:
                t = item.get("type", "")
                if t == "bad_review":
                    bad_reviews.extend(item.get("details", []))
                elif t == "notice":
                    notice_list.extend(item.get("details", []))
                elif t == "expiring":
                    exp_list.extend(item.get("details", []))
                elif t == "promo":
                    # promo details 在 msg 里解析，或直接从 item 拿
                    # run_once 里 promo 的 details 是空的，数据在 msg 里
                    pass
                elif t == "auth":
                    has_auth = 1
                elif t == "verify":
                    has_verify = 1

            # promo 数据从原始 issues 里找（run_fast 存的格式）
            for item in pitems:
                if item.get("type") == "promo":
                    msg = item.get("msg", "")
                    # "推广余额不足：120.0元/日消费80.0元"
                    import re
                    m = re.search(r'(\d+\.?\d*)元/日消费(\d+\.?\d*)元', msg)
                    if m:
                        promo_bal = float(m.group(1))
                        promo_median = float(m.group(2))

            raw = json.dumps(pitems, ensure_ascii=False, default=str)

            cur = conn.execute("""
                INSERT INTO patrol_snapshots
                (ts, store, platform, bad_review_count, notice_count, expiring_count,
                 promo_balance, promo_daily_spend, has_auth_issue, has_verify_issue, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ts, store, platform, len(bad_reviews), len(notice_list),
                  len(exp_list), promo_bal, promo_median, has_auth, has_verify, raw))
            snap_id = cur.lastrowid

            for r in bad_reviews:
                conn.execute("""
                    INSERT INTO bad_reviews (snapshot_id, stars, review_date, comment, foods)
                    VALUES (?, ?, ?, ?, ?)
                """, (snap_id, r.get("stars"), r.get("time"),
                      r.get("comment", ""), json.dumps(r.get("foods", []), ensure_ascii=False)))

            for n in notice_list:
                conn.execute("""
                    INSERT INTO notices (snapshot_id, title, content, category, notice_time)
                    VALUES (?, ?, ?, ?, ?)
                """, (snap_id, n.get("title"), n.get("content"),
                      n.get("category"), n.get("time")))

            for a in exp_list:
                conn.execute("""
                    INSERT INTO activities (snapshot_id, name, days_left)
                    VALUES (?, ?, ?)
                """, (snap_id, a.get("name"), a.get("days")))

            count += 1

    conn.commit()
    conn.close()
    return count


def save_ok_snapshot(store, platform):
    """巡检正常（无问题）时也存一条，记录"这次没事"。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = _conn()
    conn.execute("""
        INSERT INTO patrol_snapshots
        (ts, store, platform, bad_review_count, notice_count, expiring_count)
        VALUES (?, ?, ?, 0, 0, 0)
    """, (ts, store, platform))
    conn.commit()
    conn.close()


# ──────────────────────────────
# 查询：给 agent 用的趋势分析
# ──────────────────────────────

def get_store_trend(store, days=14):
    """
    查某个店最近N天的巡检趋势。
    返回: [{date, platform, bad_review_count, notice_count, promo_balance, ...}]
    """
    conn = _conn()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT ts, platform, bad_review_count, notice_count, expiring_count,
               promo_balance, promo_daily_spend, has_auth_issue, has_verify_issue
        FROM patrol_snapshots
        WHERE store = ? AND ts >= ?
        ORDER BY ts
    """, (store, since)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_reviews(store, days=14):
    """查某个店最近N天的差评明细（去重）"""
    conn = _conn()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT DISTINCT b.stars, b.review_date, b.comment, b.foods
        FROM bad_reviews b
        JOIN patrol_snapshots s ON b.snapshot_id = s.id
        WHERE s.store = ? AND s.ts >= ?
        ORDER BY b.review_date DESC
    """, (store, since)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_stores():
    """返回所有巡检过的店铺名列表"""
    conn = _conn()
    rows = conn.execute("""
        SELECT DISTINCT store FROM patrol_snapshots ORDER BY store
    """).fetchall()
    conn.close()
    return [r["store"] for r in rows]


def get_trend_summary(days=7):
    """
    生成所有店铺的趋势摘要，供 learn.py patterns 命令使用。
    返回: [{store, platform, patrols, avg_bad, trend_bad, avg_promo, trend_promo}]
    trend = "up" / "down" / "stable" / "unknown"
    """
    conn = _conn()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    stores = conn.execute("""
        SELECT DISTINCT store, platform FROM patrol_snapshots
        WHERE ts >= ?
    """, (since,)).fetchall()

    results = []
    for row in stores:
        store, platform = row["store"], row["platform"]
        snaps = conn.execute("""
            SELECT ts, bad_review_count, promo_balance
            FROM patrol_snapshots
            WHERE store = ? AND platform = ? AND ts >= ?
            ORDER BY ts
        """, (store, platform, since)).fetchall()

        if len(snaps) < 2:
            results.append({
                "store": store, "platform": platform,
                "patrols": len(snaps),
                "avg_bad": snaps[0]["bad_review_count"] if snaps else 0,
                "trend_bad": "unknown",
                "last_promo": snaps[-1]["promo_balance"] if snaps and snaps[-1]["promo_balance"] is not None else None,
                "trend_promo": "unknown"
            })
            continue

        bads = [s["bad_review_count"] for s in snaps]
        avg_bad = sum(bads) / len(bads)

        # 趋势：比较前半段 vs 后半段均值
        mid = len(bads) // 2
        first_half = sum(bads[:mid]) / max(mid, 1)
        second_half = sum(bads[mid:]) / max(len(bads) - mid, 1)
        if second_half > first_half + 0.5:
            trend_bad = "up"
        elif second_half < first_half - 0.5:
            trend_bad = "down"
        else:
            trend_bad = "stable"

        promos = [s["promo_balance"] for s in snaps if s["promo_balance"] is not None]
        if len(promos) >= 2:
            if promos[-1] < promos[0] * 0.5:
                trend_promo = "down"
            elif promos[-1] > promos[0] * 1.5:
                trend_promo = "up"
            else:
                trend_promo = "stable"
        else:
            trend_promo = "unknown"

        results.append({
            "store": store, "platform": platform,
            "patrols": len(snaps),
            "avg_bad": round(avg_bad, 1),
            "trend_bad": trend_bad,
            "last_promo": promos[-1] if promos else None,
            "trend_promo": trend_promo
        })

    conn.close()
    return results


def format_trend_report(days=7):
    """生成人话趋势报告，给 agent 汇报用或写入 patterns.md"""
    trends = get_trend_summary(days)
    if not trends:
        return "暂无巡检数据积累。"

    lines = [f"# 巡检趋势（近{days}天）\n"]
    trend_cn = {"up": "↑上升", "down": "↓下降", "stable": "→稳定", "unknown": "数据不足"}

    for t in trends:
        line = f"- **{t['store']}**（{t['platform']}）：巡检{t['patrols']}次"
        line += f"，差评均{t['avg_bad']}条/次（{trend_cn[t['trend_bad']]}）"
        if t["last_promo"] is not None:
            line += f"，推广余额{t['last_promo']}元（{trend_cn[t['trend_promo']]}）"
        lines.append(line)

    # 重点关注
    alerts = []
    for t in trends:
        if t["trend_bad"] == "up":
            alerts.append(f"⚠️ {t['store']}（{t['platform']}）差评持续上升")
        if t["trend_promo"] == "down" and t["last_promo"] is not None and t["last_promo"] < 200:
            alerts.append(f"⚠️ {t['store']}（{t['platform']}）推广余额下降且不足200元")

    if alerts:
        lines.append("\n## 重点关注\n")
        lines.extend(alerts)

    return "\n".join(lines)
