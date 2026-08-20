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
    """对股票池逐只抓盈利预测快照（当年+明年均值），返回 (行数, 警告)。

    单票失败不再静默：记入警告供 fetch_log 展示（状态 warn），
    评分端 score_profit 按可比口径降级，缺股不制造"集体下修"假信号。"""
    today = dt.date.today().isoformat()
    n = 0
    cur_year = str(dt.date.today().year)
    failed = []
    for code in config.STOCK_POOL:
        try:
            df = ak.stock_profit_forecast_ths(symbol=code, indicator="预测年报净利润")
        except Exception:  # noqa: BLE001 - 单票失败跳过
            failed.append(code)
            _sleep()
            continue
        if df is None or len(df) == 0:
            failed.append(code)
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
    warn = ""
    if failed:
        names = "、".join(config.STOCK_POOL.get(c, c) for c in failed)
        warn = f"{len(failed)}/{len(config.STOCK_POOL)} 只失败（{names}），修正信号按可比口径评估"
    return n, warn


# ---------------- 4. 拥挤度（板块成交额/20日均值 + 板块均价背景） ----------------

def fetch_crowding(conn):
    """抓股票池日线，算板块合计成交额与其 20 日均值之比及板块均价（6 只等权），返回写入天数"""
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
        frames.append(df[["date", "amount", "close"]])
        _sleep()
    if not frames:
        raise RuntimeError("行情全部抓取失败")
    # (date, amount, close) 拼接后按 date 聚合：成交额求和、收盘价等权平均
    merged = pd.concat(frames).groupby("date", as_index=False).agg(
        total=("amount", "sum"), close=("close", "mean"))
    merged = merged.dropna(subset=["total"]).sort_values("date")
    merged["ratio20"] = merged["total"] / merged["total"].rolling(20).mean()
    merged = merged.dropna(subset=["ratio20"])
    n = 0
    for _, row in merged.iterrows():
        conn.execute(
            "INSERT OR REPLACE INTO crowding (trade_date, amount, close, ratio20) VALUES (?,?,?,?)",
            (str(row["date"])[:10], float(row["total"]),
             float(row["close"]) if pd.notna(row["close"]) else None,
             float(row["ratio20"])),
        )
        n += 1
    conn.commit()
    return n


# ---------------- 5. 情绪热度（三源合成：雪球讨论榜 + 百度股票热搜 + 微博热搜） ----------------
# 2026-08-18 起：金融垂直源为主（雪球=散户在交易软件里的注意力，百度=泛搜索热度），
# 微博降为社会面参考。东财人气榜(push2域名)在当前网络环境被封，未采用。

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


def _fetch_xq_hot():
    """雪球讨论热度榜（全市场，发帖讨论量排序），返回 [(code6, name, rank)]"""
    df = ak.stock_hot_tweet_xq()
    df = df.sort_values("关注", ascending=False).reset_index(drop=True)
    out = []
    for i, row in df.iterrows():
        raw = str(row["股票代码"]).upper()  # 形如 SH603986 / SZ000021
        out.append((raw[-6:], str(row["股票简称"]).strip(), i + 1))
    return out


def _fetch_baidu_hot():
    """百度股票热搜（仅 12 只），返回 [(name, rank, heat)]"""
    df = ak.stock_hot_search_baidu()
    out = []
    for i, row in df.iterrows():
        name = str(row["名称/代码"]).strip()
        out.append((name, i + 1, int(_to_float(str(row["综合热度"]).replace(",", "")) or 0)))
    return out


def fetch_hot_snap(conn, snap_date=None):
    """三源热度快照写入 hot_snap 当日（同日覆盖幂等，单源失败不阻断其他源）

    返回 (当日总条数, 失败源列表)。单源失败不再静默——雪球是设计主源，
    缺席会让当日合成热度严重低估，必须让日志可见。

    - 微博热搜：全榜入库（board=微博热搜）
    - 雪球讨论榜：TOP100 + 股票池成分股名次入库（board=雪球讨论榜）
    - 百度股票热搜：全榜 12 条入库（board=百度股票热搜）
    """
    day = snap_date or dt.date.today().isoformat()
    total, errors = 0, []
    error_names = {"微博": "微博热搜", "雪球": "雪球讨论榜", "百度": "百度股票热搜"}

    try:
        for term, rank, heat in _fetch_weibo_hot():
            conn.execute(
                "INSERT OR REPLACE INTO hot_snap (snap_date, board, term, rank, heat)"
                " VALUES (?,?,?,?,?)", (day, "微博热搜", term, rank, heat))
        total += 1
    except Exception as e:  # noqa: BLE001
        errors.append(f"微博:{type(e).__name__}")

    try:
        pool = set(config.STOCK_POOL)
        for code6, name, rank in _fetch_xq_hot():
            if rank <= 100 or code6 in pool:
                conn.execute(
                    "INSERT OR REPLACE INTO hot_snap (snap_date, board, term, rank, heat)"
                    " VALUES (?,?,?,?,?)", (day, "雪球讨论榜", name, rank, None))
        total += 1
    except Exception as e:  # noqa: BLE001
        errors.append(f"雪球:{type(e).__name__}")

    try:
        for name, rank, heat in _fetch_baidu_hot():
            conn.execute(
                "INSERT OR REPLACE INTO hot_snap (snap_date, board, term, rank, heat)"
                " VALUES (?,?,?,?,?)", (day, "百度股票热搜", name, rank, heat))
        total += 1
    except Exception as e:  # noqa: BLE001
        errors.append(f"百度:{type(e).__name__}")

    conn.commit()
    if total == 0:
        raise RuntimeError(f"三源热度快照全部失败: {'; '.join(errors)}")
    rows = conn.execute(
        "SELECT COUNT(*) FROM hot_snap WHERE snap_date=?", (day,)).fetchone()[0]
    warn_boards = [error_names.get(e.split(":")[0], e) for e in errors]
    return rows, warn_boards


def fetch_hot_heat(conn):
    """先采三源快照，再重算每日合成热度，返回 (写入天数, 警告)

    合成口径（2026-08-18 起）：
      heat = 雪球讨论分 + 百度热搜分 + 微博热词分
      雪球讨论分：股票池成分股进入雪球讨论榜 TOP100，按名次累计 max(0, 101-rank)
      百度热搜分：成分股上榜百度股票热搜每只 +50（榜仅 12 只，上榜即高热）
      微博热词分：原口径，关键词命中累计 max(0, 51-rank)
    2026-08-18 前的旧值保持微博单一口径原样（当时唯一数据源，不回溯重算）。

    2026-08-20 修复：旧日期写入改为 INSERT OR IGNORE——此前全量 REPLACE 会把
    已有 synth 记录覆写回微博单一口径并清掉 src 标记，导致分位积累永远无法
    达到「三源口径满 10 天」的启用条件。
    """
    _, _failed_this_run = fetch_hot_snap(conn)
    day = dt.date.today().isoformat()
    # warn 以当日 hot_snap 实际覆盖为准（同日多轮采集取并集：本轮网络失败
    # 但早前已入库的源数据仍参与合成，不算缺）
    boards_have = {r["board"] for r in conn.execute(
        "SELECT DISTINCT board FROM hot_snap WHERE snap_date=?", (day,))}
    really_missing = {"微博热搜", "雪球讨论榜", "百度股票热搜"} - boards_have
    warn = (f"当日热度只含 {3 - len(really_missing)}/3 源（缺失：{'、'.join(sorted(really_missing))}），"
            f"数值偏低勿直接当冷清信号") if really_missing else ""

    pool_names = set(config.STOCK_POOL.values())
    stock_score = 0
    for r in conn.execute(
            "SELECT term, rank FROM hot_snap WHERE snap_date=? AND board='雪球讨论榜'", (day,)):
        if r["term"] in pool_names and r["rank"] and r["rank"] <= 100:
            stock_score += max(0, 101 - r["rank"])
    for r in conn.execute(
            "SELECT term FROM hot_snap WHERE snap_date=? AND board='百度股票热搜'", (day,)):
        if r["term"] in pool_names:
            stock_score += 50

    kws = config.HEAT_KEYWORDS
    daily: dict = {}
    for r in conn.execute("SELECT snap_date, term, rank FROM hot_snap WHERE board='微博热搜'"):
        daily.setdefault(r["snap_date"], 0)
        if any(k in (r["term"] or "") for k in kws):
            daily[r["snap_date"]] += max(0, 51 - (r["rank"] or 25))
    stock_part = daily.pop(day, 0) + stock_score  # 当日合成值（幂等：各部分均从头计算）

    n = 0
    # 旧日期：微博单一口径，src 保持 NULL（分位不与三源口径混算）
    # IGNORE：已有记录（含 synth 或微博口径）不覆盖，微博历史本身不变
    for d, heat in daily.items():
        conn.execute("INSERT OR IGNORE INTO hot_heat (snap_date, heat) VALUES (?,?)",
                     (d, float(heat)))
        n += 1
    # 当日：三源合成口径
    conn.execute("INSERT OR REPLACE INTO hot_heat (snap_date, heat, src) VALUES (?,?,'synth')",
                 (day, float(stock_part)))
    n += 1
    conn.commit()
    return n, warn


# ---------------- 统一调度 ----------------

COLLECTORS = [
    ("dram_price", "存储现货价", fetch_dram_price),
    ("tw_revenue", "台股月营收", fetch_tw_revenue),
    ("profit_forecast", "盈利预测", fetch_profit_forecast),
    ("crowding", "拥挤度", fetch_crowding),
    ("hot_heat", "热搜热度", fetch_hot_heat),
]


def run_all(conn, progress_cb=None):
    """依次跑全部采集器，单源失败写日志继续。返回 {source: (status, n, message)}

    采集器可返回 int（行数）或 (int, str)（行数 + 部分失败警告）；
    有警告时状态记 warn（部分成功，日志可见缺失详情），全失败才记 fail。"""
    results = {}
    for i, (source, name, fn) in enumerate(COLLECTORS):
        if progress_cb:
            progress_cb(i, len(COLLECTORS), f"正在更新：{name}")
        try:
            ret = fn(conn)
            n, warn = ret if isinstance(ret, tuple) else (ret, "")
            status = "warn" if warn else "ok"
            db.log_fetch(conn, source, status, n, warn)
            results[source] = (status, n, warn)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            db.log_fetch(conn, source, "fail", 0, msg)
            results[source] = ("fail", 0, msg)
    if progress_cb:
        progress_cb(len(COLLECTORS), len(COLLECTORS), "全部完成")
    return results
