# -*- coding: utf-8 -*-
"""
五个信号采集器：存储现货价 / 台股月营收 / 盈利预测 / 拥挤度 / 热搜热度
统一约定：重试 3 次指数退避；单源失败写 fetch_log 不影响其他源；
入库 INSERT OR REPLACE 幂等；本机代理异常时 trust_env=False 直连重试。
"""
import datetime as dt
import io
import random
import re
import time

import akshare as ak
import pandas as pd
import requests

from . import config, db


def _to_float(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _get(url, referer=None, timeout=15, binary=False):
    """带重试与代理回落的 GET，返回 Response 或抛 RuntimeError"""
    last_err = None
    for attempt in range(config.MAX_RETRY):
        for trust_env in (True, False):
            try:
                s = requests.Session()
                s.trust_env = trust_env
                s.headers.update({"User-Agent": config.USER_AGENT})
                if referer:
                    s.headers.update({"Referer": referer})
                r = s.get(url, timeout=timeout)
                r.raise_for_status()
                return r
            except Exception as e:  # noqa: BLE001
                last_err = e
        time.sleep(config.RETRY_BACKOFF * (2 ** attempt) + random.random())
    raise RuntimeError(f"{url} 连续{config.MAX_RETRY}次失败: {last_err}")


def _sleep():
    time.sleep(config.REQUEST_INTERVAL + random.uniform(0, 0.8))


# ---------------- 1. 存储现货价（CFM） ----------------

_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)\s+\d\d:\d\d")


def fetch_dram_price(conn):
    """抓 CFM DDR 现货周价表，返回行数"""
    r = _get(config.CFM_DDR_URL, referer="https://www.chinaflashmarket.com/")
    html = r.text
    m = _DATE_RE.search(html)
    price_date = m.group(1) if m else dt.date.today().isoformat()

    n = 0
    for row in _ROW_RE.findall(html):
        cells = [_TAG_RE.sub("", c).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]
        cells = [c for c in cells if c != ""]
        if len(cells) < 6 or not cells[0].startswith(("DDR", "LPDDR")):
            continue
        # cells: [产品, 本周价, 涨跌额, 涨跌幅, 上周价, 周高点, 周低点, ...]
        conn.execute(
            "INSERT OR REPLACE INTO dram_price (date, product, price, chg_pct, week_high, week_low)"
            " VALUES (?,?,?,?,?,?)",
            (price_date, cells[0], _to_float(cells[1]), _to_float(cells[3]),
             _to_float(cells[5]), _to_float(cells[6])),
        )
        n += 1
    conn.commit()
    if n == 0:
        raise RuntimeError("CFM 页面解析到 0 行，页面结构可能已改版")
    return n


_EWS_ID_RE = re.compile(r"/price/ews/(\d+)")
_TITLE_RE = re.compile(r"<title>(.*?)价格_报价中心", re.S)
_WEEK_ROW_RE = re.compile(r"(20\d\d-\d\d-\d\d)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)")


def fetch_dram_price_history(conn, progress_cb=None):
    """从 CFM 产品详情页回填近半年周度现货价。

    CFM 主表只给当周快照，但每个产品的详情页公开"最近半年"周度记录
    （"最近一年"需登录会员，不抓取）。chg_pct 由相邻真实周价计算，不虚构。
    入库 INSERT OR REPLACE 幂等，可反复运行。返回写入行数。
    """
    r = _get(config.CFM_DDR_URL, referer="https://www.chinaflashmarket.com/")
    ids = list(dict.fromkeys(_EWS_ID_RE.findall(r.text)))
    if not ids:
        raise RuntimeError("CFM DDR 页未找到产品详情链接，页面结构可能已改版")
    n = 0
    for i, pid in enumerate(ids, 1):
        if progress_cb:
            progress_cb(i, len(ids), f"回填存储价格 {i}/{len(ids)} 个产品")
        pr = _get(config.CFM_EWS_URL.format(pid), referer=config.CFM_DDR_URL, timeout=20)
        m = _TITLE_RE.search(pr.text)
        if not m:
            continue
        product = m.group(1).strip()
        text = re.sub(r"\s+", " ", _TAG_RE.sub(" ", pr.text))
        rows = sorted(set(_WEEK_ROW_RE.findall(text)))  # (日期, 周低点, 周高点, 本周价)
        prev = None
        for date, lo, hi, p in rows:
            p, lo, hi = float(p), float(lo), float(hi)
            chg = round((p - prev) / prev * 100, 2) if prev else None
            conn.execute(
                "INSERT OR REPLACE INTO dram_price (date, product, price, chg_pct, week_high, week_low)"
                " VALUES (?,?,?,?,?,?)",
                (date, product, p, chg, hi, lo),
            )
            prev = p
            n += 1
        conn.commit()
        _sleep()
    if n == 0:
        raise RuntimeError("CFM 详情页解析到 0 行，页面结构可能已改版")
    return n


# ---------------- 2. 台股月营收（TWSE 开放数据） ----------------

def fetch_tw_revenue(conn):
    """抓 TWSE 上市公司月营收，筛选存储观察标的，返回行数"""
    r = _get(config.TWSE_REVENUE_URL, timeout=20)
    data = r.json()
    watch = {**config.TW_WATCH, **config.TW_REFERENCE}
    n = 0
    for rec in data:
        code = str(rec.get("公司代號") or "")
        if code not in watch:
            continue
        ym = str(rec.get("資料年月") or "")  # 民国年月，如 11506 = 2026-06
        if len(ym) >= 4:
            month = f"{int(ym[:-2]) + 1911:04d}-{ym[-2:]}"
        else:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO tw_revenue (month, code, name, revenue, yoy_pct, mom_pct)"
            " VALUES (?,?,?,?,?,?)",
            (month, code, rec.get("公司名稱"),
             _to_float(rec.get("營業收入-當月營收")),
             _to_float(rec.get("營業收入-去年同月增減(%)")),
             _to_float(rec.get("營業收入-上月比較增減(%)"))),
        )
        n += 1
    conn.commit()
    if n == 0:
        raise RuntimeError("TWSE 返回中未找到目标公司")
    return n


def fetch_tw_revenue_history(conn, months=12, progress_cb=None):
    """从公开资讯观测站（MOPS）回填最近 months 个月的台股月营收。

    TWSE 开放接口只给当月快照，历史数据从 MOPS 逐月抓取（页面含去年同月增减%）。
    入库 INSERT OR REPLACE 幂等，与当月快照口径一致（单位：千元），可反复运行。
    返回写入行数。
    """
    watch = {**config.TW_WATCH, **config.TW_REFERENCE}
    today = dt.date.today()
    n = 0
    for k in range(1, months + 1):
        y, m = today.year, today.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        month = f"{y:04d}-{m:02d}"
        if progress_cb:
            progress_cb(k, months, f"回填台系营收 {month}")
        try:
            r = _get(config.MOPS_REVENUE_URL.format(y - 1911, m), timeout=30)
        except RuntimeError:
            continue  # 该月页面不存在（尚未披露），跳过
        html = r.content.decode("cp950", errors="replace")
        try:
            tables = pd.read_html(io.StringIO(html))
        except ValueError:
            continue  # 该月页面无表格（尚未披露），跳过
        got = 0
        for t in tables:
            if t.shape[1] != 11:
                continue
            header = " ".join(str(c) for c in t.columns)
            if "公司" not in header or "代號" not in header:
                continue
            # 列序：代號/名稱/當月營收/上月營收/去年當月營收/上月比較增減(%)/去年同月增減(%)/...
            for row in t.itertuples(index=False):
                code = str(row[0]).strip()
                if code not in watch:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO tw_revenue (month, code, name, revenue, yoy_pct, mom_pct)"
                    " VALUES (?,?,?,?,?,?)",
                    (month, code, str(row[1]).strip(),
                     _to_float(row[2]), _to_float(row[6]), _to_float(row[5])),
                )
                got += 1
        conn.commit()
        n += got
        if got == 0:
            break  # 页面存在但无目标公司，说明已到可获得数据的尽头
        _sleep()
    if n == 0:
        raise RuntimeError("MOPS 回填失败：所有月份均未取到目标公司数据")
    return n


# ---------------- 3. 盈利预测（同花顺 akshare，快照积累制） ----------------

def fetch_profit_forecast(conn):
    """对股票池逐只抓盈利预测快照（当年+明年均值），返回行数"""
    today = dt.date.today().isoformat()
    n = 0
    cur_year = str(dt.date.today().year)
    for code in config.STOCK_POOL:
        try:
            df = ak.stock_profit_forecast_ths(symbol=code, indicator="预测年报净利润")
        except Exception:  # noqa: BLE001 - 单票失败跳过
            _sleep()
            continue
        if df is None or len(df) == 0:
            continue
        for _, row in df.iterrows():
            year = str(row["年度"])
            if year not in (cur_year, str(int(cur_year) + 1)):
                continue  # 只存当年与明年，修正信号主要看当年
            conn.execute(
                "INSERT OR REPLACE INTO profit_forecast (snap_date, code, year, org_count, mean)"
                " VALUES (?,?,?,?,?)",
                (today, code, year, int(row["预测机构数"]), _to_float(row["均值"])),
            )
            n += 1
        _sleep()
    conn.commit()
    if n == 0:
        raise RuntimeError("盈利预测接口全部失败或无数据")
    return n


# ---------------- 4. 拥挤度（板块成交额/20日均值） ----------------

def fetch_crowding(conn):
    """抓股票池日线，算板块合计成交额与其 20 日均值之比，返回写入天数"""
    frames = []
    for code in config.STOCK_POOL:
        prefix = "sh" if code.startswith("6") else "sz"
        try:
            df = ak.stock_zh_a_daily(symbol=f"{prefix}{code}", adjust="")
        except Exception:  # noqa: BLE001
            _sleep()
            continue
        if df is None or len(df) == 0:
            continue
        df = df[["date", "close", "volume"]].copy()
        df["amount"] = df["close"] * df["volume"]  # 近似成交额
        frames.append(df[["date", "amount"]])
        _sleep()
    if not frames:
        raise RuntimeError("行情全部抓取失败")
    # 6 只股票的 (date, amount) 拼接后按 date 聚合求和，避免多表 merge 产生重复列名
    merged = pd.concat(frames).groupby("date", as_index=False).sum(min_count=1)
    merged = merged.rename(columns={"amount": "total"})
    merged = merged.dropna(subset=["total"]).sort_values("date")
    merged["ratio20"] = merged["total"] / merged["total"].rolling(20).mean()
    merged = merged.dropna(subset=["ratio20"])
    n = 0
    for _, row in merged.iterrows():
        conn.execute(
            "INSERT OR REPLACE INTO crowding (trade_date, amount, ratio20) VALUES (?,?,?)",
            (str(row["date"])[:10], float(row["total"]), float(row["ratio20"])),
        )
        n += 1
    conn.commit()
    return n


# ---------------- 5. 热搜热度（本系统自采微博热搜，每日快照积累） ----------------

_WEIBO_HOT_URL = "https://weibo.com/ajax/side/hotSearch"
_WEIBO_HOT_FALLBACK_URL = "https://weibo.com/ajax/statuses/hot_band"


def _fetch_weibo_hot():
    """微博热搜实时榜，返回 [(term, rank, heat)]；主接口失败回落 hot_band"""
    def normalize(rows):
        items, rank = [], 0
        for t in rows:
            if t.get("is_ad"):
                continue
            term = (t.get("note") or t.get("word") or "").strip().strip("#")
            if not term or not t.get("realpos"):
                continue  # 置顶/广告位无 realpos，不计入榜单
            rank += 1
            items.append((term, rank, int(_to_float(t.get("num") or t.get("raw_hot")) or 0)))
        return items

    r = _get(_WEIBO_HOT_URL, referer="https://weibo.com", timeout=15)
    items = normalize(((r.json().get("data") or {}).get("realtime")) or [])
    if items:
        return items
    r = _get(_WEIBO_HOT_FALLBACK_URL, referer="https://weibo.com", timeout=15)
    return normalize(((r.json().get("data") or {}).get("band_list")) or [])


def fetch_hot_snap(conn, snap_date=None):
    """抓微博热搜写入 hot_snap 当日快照（同日覆盖幂等），返回条数"""
    day = snap_date or dt.date.today().isoformat()
    items = _fetch_weibo_hot()
    if not items:
        raise RuntimeError("微博热搜解析到 0 条，接口可能已改版")
    for term, rank, heat in items:
        conn.execute(
            "INSERT OR REPLACE INTO hot_snap (snap_date, board, term, rank, heat)"
            " VALUES (?,?,?,?,?)",
            (day, "微博热搜", term, rank, heat),
        )
    conn.commit()
    return len(items)


def fetch_hot_heat(conn):
    """先采今日热搜快照，再从本地 hot_snap 重算关键词每日热度（无命中补 0），返回天数"""
    fetch_hot_snap(conn)
    rows = conn.execute(
        "SELECT snap_date, term, rank FROM hot_snap WHERE board='微博热搜'"
    ).fetchall()
    kws = config.HEAT_KEYWORDS
    daily: dict = {}
    for r in rows:
        daily.setdefault(r["snap_date"], 0)
        if any(k in (r["term"] or "") for k in kws):
            daily[r["snap_date"]] += max(0, 51 - (r["rank"] or 25))
    n = 0
    for d, heat in daily.items():
        conn.execute("INSERT OR REPLACE INTO hot_heat (snap_date, heat) VALUES (?,?)",
                     (d, float(heat)))
        n += 1
    conn.commit()
    return n


# ---------------- 统一调度 ----------------

COLLECTORS = [
    ("dram_price", "存储现货价", fetch_dram_price),
    ("tw_revenue", "台股月营收", fetch_tw_revenue),
    ("profit_forecast", "盈利预测", fetch_profit_forecast),
    ("crowding", "拥挤度", fetch_crowding),
    ("hot_heat", "热搜热度", fetch_hot_heat),
]


def run_all(conn, progress_cb=None):
    """依次跑全部采集器，单源失败写日志继续。返回 {source: (status, n, message)}"""
    results = {}
    for i, (source, name, fn) in enumerate(COLLECTORS):
        if progress_cb:
            progress_cb(i, len(COLLECTORS), f"正在更新：{name}")
        try:
            n = fn(conn)
            db.log_fetch(conn, source, "ok", n)
            results[source] = ("ok", n, "")
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            db.log_fetch(conn, source, "fail", 0, msg)
            results[source] = ("fail", 0, msg)
    if progress_cb:
        progress_cb(len(COLLECTORS), len(COLLECTORS), "全部完成")
    return results
