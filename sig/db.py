# -*- coding: utf-8 -*-
"""
SQLite 数据层（data/signals.db）

表结构：
- dram_price(date, product, price, chg_pct, week_high, week_low)  CFM DRAM 现货周价
- tw_revenue(month, code, name, revenue, yoy_pct, mom_pct)        台股月营收（month=YYYY-MM）
- profit_forecast(snap_date, code, year, org_count, mean)         盈利预测快照（积累制）
- crowding(trade_date, amount, ratio20)                           板块成交额与20日均值比
- hot_snap(snap_date, board, term, rank, heat)                    微博热搜每日快照（本系统自采）
- hot_heat(snap_date, heat)                                       热搜热度（由 hot_snap 计算，0 补齐）
- fetch_log(id, ts, source, status, n_rows, message)              每次抓取记录
- settings(key, value)                                            阈值等可调参数
"""
import os
import sqlite3

from . import config


def get_conn(db_path=None):
    path = str(db_path or config.DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dram_price (
            date TEXT NOT NULL,
            product TEXT NOT NULL,
            price REAL, chg_pct REAL, week_high REAL, week_low REAL,
            PRIMARY KEY (date, product)
        );
        CREATE TABLE IF NOT EXISTS tw_revenue (
            month TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT, revenue REAL, yoy_pct REAL, mom_pct REAL,
            PRIMARY KEY (month, code)
        );
        CREATE TABLE IF NOT EXISTS profit_forecast (
            snap_date TEXT NOT NULL,
            code TEXT NOT NULL,
            year TEXT NOT NULL,
            org_count INTEGER, mean REAL,
            PRIMARY KEY (snap_date, code, year)
        );
        CREATE TABLE IF NOT EXISTS crowding (
            trade_date TEXT NOT NULL,
            amount REAL, close REAL, ratio20 REAL,
            PRIMARY KEY (trade_date)
        );
        CREATE TABLE IF NOT EXISTS hot_heat (
            snap_date TEXT NOT NULL,
            heat REAL,
            PRIMARY KEY (snap_date)
        );
        CREATE TABLE IF NOT EXISTS hot_snap (
            snap_date TEXT NOT NULL,
            board TEXT NOT NULL,
            term TEXT NOT NULL,
            rank INTEGER, heat INTEGER,
            PRIMARY KEY (snap_date, board, term)
        );
        CREATE TABLE IF NOT EXISTS fetch_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            n_rows INTEGER,
            message TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    # 已有库迁移：crowding 加 close 列（2026-08-18 起量比<1 时结合价格背景判断）；
    # hot_heat 加 src 口位列（'synth'=三源合成，NULL=旧微博单一口径，分位只在同口径内比较）
    cols = {r[1] for r in conn.execute("PRAGMA table_info(crowding)")}
    if "close" not in cols:
        conn.execute("ALTER TABLE crowding ADD COLUMN close REAL")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(hot_heat)")}
    if "src" not in cols:
        conn.execute("ALTER TABLE hot_heat ADD COLUMN src TEXT")
    conn.commit()
    return conn


def log_fetch(conn, source, status, n_rows=0, message=""):
    import datetime as dt
    conn.execute(
        "INSERT INTO fetch_log (ts, source, status, n_rows, message) VALUES (?,?,?,?,?)",
        (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), source, status, n_rows, message),
    )
    conn.commit()


def last_fetch(conn, source):
    row = conn.execute(
        "SELECT ts, status, n_rows, message FROM fetch_log WHERE source=? "
        "ORDER BY id DESC LIMIT 1", (source,),
    ).fetchone()
    return dict(row) if row else None


# 各业务表的日期列与"新鲜"判定（最新数据距今超过该天数视为可更新）
OVERVIEW_TABLES = {
    "dram_price": ("存储现货价", "date", 9),
    "tw_revenue": ("台股月营收", "month", None),   # 月度披露，按披露节奏单独判定
    "profit_forecast": ("盈利预测", "snap_date", 9),
    "crowding": ("板块拥挤度", "trade_date", 4),
    "hot_heat": ("热搜热度", "snap_date", 4),
}


def _tw_expected_month(today):
    """台股月营收次月 10 日前披露：10 日后预期到上月，10 日前预期到上上月"""
    y, m = today.year, today.month - (1 if today.day >= 10 else 2)
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def data_overview(conn):
    """各数据表概览：行数、覆盖区间、最近抓取时间、新鲜度与原因说明（首页/更新页展示用）"""
    import datetime as dt
    today = dt.date.today()
    out = []
    for key, (name, datecol, fresh_days) in OVERVIEW_TABLES.items():
        row = conn.execute(
            f"SELECT COUNT(*) c, MIN({datecol}) mn, MAX({datecol}) mx FROM {key}"
        ).fetchone()
        latest = row["mx"]
        age = None
        if latest:
            s = str(latest)[:10]
            if len(s) == 7:  # tw_revenue 的 month 是 YYYY-MM
                s += "-01"
            try:
                age = (today - dt.date.fromisoformat(s)).days
            except ValueError:
                pass
        note = ""
        if key == "tw_revenue":
            expected = _tw_expected_month(today)
            fresh = bool(latest) and str(latest) >= expected
            note = f"月度披露（次月10日前），当前最新应到 {expected}"
        else:
            fresh = age is not None and age <= fresh_days
        last = last_fetch(conn, key)
        out.append({
            "key": key, "name": name, "rows": row["c"], "latest": latest,
            "span": f"{row['mn']} ~ {row['mx']}" if row["c"] else "—",
            "age_days": age, "fresh": fresh, "note": note,
            "last_fetch": last["ts"] if last else None,
            "last_status": last["status"] if last else None,
        })
    return out


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return float(row["value"])
    except (TypeError, ValueError):
        return row["value"]


def set_setting(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                 (key, str(value)))
    conn.commit()


def thresholds(conn):
    """当前生效阈值：settings 表覆盖默认值"""
    return {k: get_setting(conn, k, v) for k, v in config.DEFAULT_THRESHOLDS.items()}
