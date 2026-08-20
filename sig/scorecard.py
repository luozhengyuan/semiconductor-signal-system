# -*- coding: utf-8 -*-
"""
记分卡打分：五个信号 → 🟢🟡🔴⚪ → 方向分 + 仓位折减。
所有规则透明、纯函数、可测试；阈值从 db.thresholds() 读（页面可调）。

灯的约定（A股习惯：红涨绿跌）：
🔴 顺风（信号偏多/利好）  🟡 中性  🟢 逆风（信号偏空/利空）  ⚪ 数据积累中（不参与评分）

信号分两类（2026-08-18 起，kind 字段）：
- direction 方向信号：价格趋势/台系营收/盈利修正——慢变量，决定多空基调
- risk 风险信号：拥挤度/情绪热度——快变量、反向，只折减仓位不改方向
"""
import pandas as pd

from . import config, db

GREEN, YELLOW, RED, GRAY = "🔴", "🟡", "🟢", "⚪"

DIRECTION_KEYS = {"dram_price", "tw_revenue", "profit_forecast"}
RISK_KEYS = {"crowding", "hot_heat"}


def _latest(conn, sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)


# ---------------- 1. 价格趋势 ----------------

def score_price(conn, th):
    """CFM 最新一期全部产品涨跌幅均值：>0 🔴，=0 🟡，<0 🟢"""
    df = _latest(conn, "SELECT * FROM dram_price WHERE date=(SELECT MAX(date) FROM dram_price)")
    if df.empty:
        return {"key": "dram_price", "name": "存储价格趋势", "light": GRAY, "kind": "direction",
                "value": "无数据", "detail": "请到「数据更新」抓取", "history": None}
    avg_chg = df["chg_pct"].mean()
    n_up = int((df["chg_pct"] > 0).sum())
    n_down = int((df["chg_pct"] < 0).sum())
    if avg_chg > 0:
        light = GREEN
        talk = "现货价在涨，产业景气上行"
    elif avg_chg < 0:
        light = RED
        talk = "现货价在跌，周期承压"
    else:
        light = YELLOW
        talk = "本周价格走平，方向待确认"
    return {
        "key": "dram_price", "name": "存储价格趋势", "light": light, "kind": "direction",
        "value": f"周涨跌 {avg_chg:+.2f}%（{df['date'].iloc[0]}）",
        "detail": f"{len(df)} 个产品中 {n_up} 涨 {n_down} 跌；代表品 DDR4 16Gb 3200 现价 "
                  f"${df.loc[df['product'].str.contains('16Gb 3200', na=False), 'price'].max() or '—'}",
        "history": _latest(conn, "SELECT date, AVG(chg_pct) AS v FROM dram_price GROUP BY date ORDER BY date"),
        "talk": talk,
    }


# ---------------- 2. 台股月营收 ----------------

def score_tw_revenue(conn, th):
    """存储三家（南亚科/华邦电/旺宏）最新月营收同比均值：>20%🔴 0~20%🟡 <0%🟢

    台积电(2330)是参考指标，不计入存储均值——它体量是存储厂 10~20 倍，
    混入会把均值拉向代工景气而非存储景气。"""
    df = _latest(conn, "SELECT * FROM tw_revenue WHERE month=(SELECT MAX(month) FROM tw_revenue)")
    if df.empty:
        return {"key": "tw_revenue", "name": "台系营收验证", "light": GRAY, "kind": "direction",
                "value": "无数据", "detail": "请到「数据更新」抓取", "history": None}
    watch = df[df["yoy_pct"].notna() & df["code"].isin(config.TW_WATCH)]
    if watch.empty:
        return {"key": "tw_revenue", "name": "台系营收验证", "light": GRAY, "kind": "direction",
                "value": "无数据", "detail": "当月无存储三家的营收数据", "history": None}
    avg_yoy = watch["yoy_pct"].mean()
    g = th["tw_yoy_green"]
    if avg_yoy > g:
        light = GREEN
        talk = "台系存储营收高增长，景气验证通过"
    elif avg_yoy < 0:
        light = RED
        talk = "台系营收同比转负，景气退潮"
    else:
        light = YELLOW
        talk = "营收温和增长，景气平稳"
    names = "、".join(f"{r['name']}{r['yoy_pct']:+.0f}%" for _, r in watch.iterrows())
    # 台积电作参考附注（不计入均值）
    tsmc = df[df["code"] == "2330"]
    ref = f"；台積電{tsmc['yoy_pct'].iloc[0]:+.0f}%（参考，不计入存储均值）" \
        if not tsmc.empty and pd.notna(tsmc["yoy_pct"].iloc[0]) else ""
    return {
        "key": "tw_revenue", "name": "台系营收验证", "light": light, "kind": "direction",
        "value": f"同比均值 {avg_yoy:+.1f}%（{df['month'].iloc[0]}）",
        "detail": names + ref,
        "history": _latest(conn, "SELECT month AS date, AVG(yoy_pct) AS v FROM tw_revenue "
                                 "WHERE code IN ('2408','2344','2337') GROUP BY month ORDER BY month"),
        "talk": talk,
    }


# ---------------- 3. 盈利修正 ----------------

# 可比口径最小样本：两快照交集 < 3 只时不评分（小样本噪声大）
PROFIT_MIN_COMMON = 3


def score_profit(conn, th):
    """当年预测净利润合计：与上一快照比，>0🔴 ≈0🟡 <0🟢；不足两次快照 ⚪

    可比口径（2026-08-20 起）：只统计两个快照**共同覆盖**的股票。
    原因：单票采集偶发失败会让新快照缺股——若按全量合计对比，
    缺席的大权重股（如江波龙 142 亿）会被误读成"分析师集体下修"，
    制造假信号。交集 <3 只降级 ⚪，避免小样本噪声。"""
    dates = [r["snap_date"] for r in conn.execute(
        "SELECT DISTINCT snap_date FROM profit_forecast ORDER BY snap_date DESC LIMIT 2")]
    if len(dates) < 2:
        return {"key": "profit_forecast", "name": "盈利预测修正", "light": GRAY, "kind": "direction",
                "value": "积累中", "detail": "需要至少两次快照（建议每周抓一次），暂不参与评分",
                "history": None}
    cur_year = dates[0][:4]
    n_pool = len(config.STOCK_POOL)

    def codes(d):
        return {r["code"] for r in conn.execute(
            "SELECT DISTINCT code FROM profit_forecast WHERE snap_date=? AND year=?", (d, cur_year))}

    c_cur, c_prev = codes(dates[0]), codes(dates[1])
    common = c_cur & c_prev
    if len(common) < PROFIT_MIN_COMMON:
        return {"key": "profit_forecast", "name": "盈利预测修正", "light": GRAY, "kind": "direction",
                "value": "无可比样本",
                "detail": f"{dates[0]} 与 {dates[1]} 共同覆盖仅 {len(common)} 只"
                          f"（< {PROFIT_MIN_COMMON}），快照不完整，暂不评分",
                "history": None}

    def total(d, codes_common):
        ph = ",".join("?" * len(codes_common))
        row = conn.execute(
            f"SELECT SUM(mean) AS s FROM profit_forecast "
            f"WHERE snap_date=? AND year=? AND code IN ({ph})",
            (d, cur_year, *codes_common)).fetchone()
        return row["s"] or 0

    latest, prev = total(dates[0], common), total(dates[1], common)
    chg = 0.0 if prev == 0 else (latest - prev) / prev * 100
    if chg > 0.1:
        light = GREEN
        talk = "分析师在上修盈利，周期上行段特征"
    elif chg < -0.1:
        light = RED
        talk = "盈利预测被下修，警惕行情进入尾声"
    else:
        light = YELLOW
        talk = "盈利预测持平，等待新催化"
    # 如实披露口径：可比几只、缺哪只
    missing = sorted(c_prev - c_cur)
    miss_note = f"；{dates[0]} 快照缺 {len(missing)} 只：{'、'.join(missing)}" if missing else ""
    return {
        "key": "profit_forecast", "name": "盈利预测修正", "light": light, "kind": "direction",
        "value": f"修正 {chg:+.2f}%（{cur_year} 年预测）",
        "detail": f"{dates[1]} → {dates[0]}，{len(common)}/{n_pool} 只可比口径合计{miss_note}",
        "history": _latest(conn, "SELECT snap_date AS date, SUM(mean) AS v FROM profit_forecast "
                                 "WHERE year=strftime('%Y', snap_date) GROUP BY snap_date ORDER BY snap_date"),
        "talk": talk,
    }


# ---------------- 4. 拥挤度（风险灯） ----------------

def _crowding_price_up(df):
    """板块价格背景：20 日窗口内最新收盘处于上半区且 5 日均价 ≥ 20 日均价。

    df 为按 trade_date 降序的 crowding 最近 20 行。返回 True/False/None（close 缺失时 None）。
    """
    if "close" not in df.columns or df["close"].isna().all():
        return None
    c = df.dropna(subset=["close"])["close"]
    if len(c) < 10:
        return None
    latest = float(c.iloc[0])
    hi, lo = float(c.max()), float(c.min())
    if hi <= lo:
        return None
    pos = (latest - lo) / (hi - lo)
    ma5, ma20 = float(c.iloc[:5].mean()), float(c.mean())
    return pos >= 0.5 and ma5 >= ma20


def score_crowding(conn, th):
    """量比 + 价格背景（风险灯，方向是反的：越挤越危险）：
    >红线 🟢拥挤危险；1~红线 🟡温和放量；<1 时看板块价格背景——
    上行段的缩量 = 惜售（🔴健康）；下行段的缩量 = 承接乏力（🟡）；无 close 背景 🟡"""
    df = _latest(conn, "SELECT * FROM crowding ORDER BY trade_date DESC LIMIT 20")
    if df.empty:
        return {"key": "crowding", "name": "板块拥挤度", "light": GRAY, "kind": "risk",
                "value": "无数据", "detail": "请到「数据更新」抓取", "history": None}
    ratio = float(df["ratio20"].iloc[0])
    if ratio > th["crowding_red"]:
        light = RED
        talk = "成交爆量，短线资金拥挤，控制仓位"
        ctx = ""
    elif ratio >= 1.0:
        light = YELLOW
        talk = "成交温和放大，留意是否持续"
        ctx = ""
    else:
        up = _crowding_price_up(df)
        if up is True:
            light = GREEN
            talk = "缩量上涨，筹码惜售，回踩形态健康"
            ctx = "板块均价处 20 日区间上半区"
        elif up is False:
            light = YELLOW
            talk = "缩量阴跌，承接乏力，等企稳信号"
            ctx = "板块均价处 20 日区间下半区"
        else:
            light = YELLOW
            talk = "成交清淡（中性，不加分）"
            ctx = "无价格背景数据，缩量性质待判断"
    return {
        "key": "crowding", "name": "板块拥挤度", "light": light, "kind": "risk",
        "value": f"量比 {ratio:.2f}（{df['trade_date'].iloc[0]}）",
        "detail": ("6 只标的合计成交额 / 其 20 日均值；>红线为拥挤；"
                   f"<1 时结合价格背景判断缩量性质。{ctx}" if ctx else
                   "6 只标的合计成交额 / 其 20 日均值；>红线为拥挤"),
        "history": _latest(conn, "SELECT trade_date AS date, ratio20 AS v FROM crowding ORDER BY trade_date"),
        "talk": talk,
    }


# ---------------- 5. 热搜热度 ----------------

def score_heat(conn, th):
    """情绪热度（风险灯，反向指标）：
    同口径（三源合成）60 日分位 >红线 危险；三源样本 <10 天时按绝对热度分档"""
    df = _latest(conn, "SELECT * FROM hot_heat WHERE src='synth' ORDER BY snap_date DESC LIMIT 60")
    if df.empty:
        df = _latest(conn, "SELECT * FROM hot_heat ORDER BY snap_date DESC LIMIT 60")
    if df.empty:
        return {"key": "hot_heat", "name": "情绪热度", "light": GRAY, "kind": "risk",
                "value": "无数据", "detail": "依赖热榜快照积累", "history": None}
    latest = float(df["heat"].iloc[0])
    hist_all = _latest(conn, "SELECT snap_date AS date, heat AS v FROM hot_heat ORDER BY snap_date")
    if latest == 0:
        # 零膨胀分布：历史多数天数为 0，0 参与分位比较会虚高（0 也能拿高分位）
        return {
            "key": "hot_heat", "name": "情绪热度", "light": GREEN, "kind": "risk",
            "value": f"热度 0（{df['snap_date'].iloc[0]}，无命中）",
            "detail": "当日三源均无命中（雪球讨论榜 TOP100 / 百度股票热搜 / 微博关键词），"
                      "热度 0 不做分位比较（避免零膨胀失真）",
            "history": hist_all,
            "talk": "今日无命中，情绪冷清",
        }
    n_synth = int((df["src"] == "synth").sum()) if "src" in df.columns else len(df)
    if n_synth >= 10:
        pct = float((df["heat"] <= latest).mean() * 100)
        mode = (f"{df['snap_date'].iloc[0]}；三源口径 60 日分位，"
                f"> {th['heat_pct_red']:.0f} 分位为爆表（反向指标）")
        value = f"热度 {latest:.0f}（{pct:.0f} 分位）"
        if pct > th["heat_pct_red"]:
            light, talk = RED, "情绪爆表！实证：这是见顶警报，别加仓"
        elif pct > th["heat_pct_yellow"]:
            light, talk = YELLOW, "情绪升温中，保持关注但不追"
        else:
            light, talk = GREEN, "情绪温和，没有过热风险"
    else:
        # 三源口径积累不足：分位无意义（首日必 100 分位），按绝对热度分档
        if latest >= th["heat_abs_red"]:
            light, talk = RED, "情绪爆表！实证：这是见顶警报，别加仓"
        elif latest >= th["heat_abs_yellow"]:
            light, talk = YELLOW, "情绪升温中，保持关注但不追"
        else:
            light, talk = GREEN, "情绪温和，没有过热风险"
        mode = (f"{df['snap_date'].iloc[0]}；三源口径积累 {n_synth}/10 天，暂按绝对热度分档"
                f"（≥{th['heat_abs_red']:.0f} 爆表 / ≥{th['heat_abs_yellow']:.0f} 升温）")
        value = f"热度 {latest:.0f}（绝对分档）"
    return {
        "key": "hot_heat", "name": "情绪热度", "light": light, "kind": "risk",
        "value": value,
        "detail": (f"{mode}；合成口径：雪球讨论榜 TOP100 名次分 + "
                   "百度股票热搜 50 分/只 + 微博关键词分"),
        "history": hist_all,
        "talk": talk,
    }


SCORERS = [score_price, score_tw_revenue, score_profit, score_crowding, score_heat]


# 风险折减表：0 盏风险灯不打折，每亮 1 盏折 25%
RISK_DEDUCTION = {0: 1.0, 1: 0.75, 2: 0.5}


def composite(cards):
    """方向分定基调，风险灯折减仓位。

    方向分 = 方向信号（价格/营收/盈利）中 🔴数 − 🟢数，范围 -3 ~ +3；
    风险灯 = 风险信号（拥挤度/情绪）中亮 🟢 的数量（🟢 显示 = 危险），
    建议仓位 = 基准仓位 × 折减系数（1.0 / 0.75 / 0.5）。

    旧版五灯等权加减的问题：产业趋势完好 + 情绪过热 会互相抵消，
    丢失"方向看多但该减仓"这层信息。分区后两个维度各自保留。
    """
    d_cards = [c for c in cards if c.get("kind") == "direction"]
    r_cards = [c for c in cards if c.get("kind") == "risk"]
    d_lights = [c["light"] for c in d_cards]
    n_g, n_r = d_lights.count(GREEN), d_lights.count(RED)
    score = n_g - n_r
    valid = len([l for l in d_lights if l != GRAY])

    n_risk_on = sum(1 for c in r_cards if c["light"] == RED)
    deduction = RISK_DEDUCTION[min(n_risk_on, 2)]

    if score >= 2:
        pos, base = "周期上行确认，方向信号共振偏多", "7~8 成"
    elif score == 1:
        pos, base = "偏多但有分歧，上行动能不完整", "5~6 成"
    elif score == 0:
        pos, base = "方向信号均衡或不明", "3~5 成"
    elif score == -1:
        pos, base = "偏空，景气信号转弱", "2~3 成"
    else:
        pos, base = "景气风险共振，防御优先", "0~2 成"

    if n_risk_on == 0:
        risk_note = "风险灯未亮，仓位不打折"
    elif n_risk_on == 1:
        risk_note = "亮 1 盏风险灯，仓位打 75 折"
    else:
        risk_note = "2 盏风险灯齐亮，仓位减半"

    return {
        "score": score, "n_green": n_g, "n_red": n_r, "n_valid": valid,
        "position": pos,
        "base": base,                      # 方向分对应的基准仓位
        "n_risk_on": n_risk_on,            # 亮起的风险灯数
        "deduction": deduction,            # 折减系数
        "risk_note": risk_note,
        "reference": f"基准 {base} × 风险折减 {deduction:.0%} → {risk_note}",
    }


def build_scorecard(conn):
    th = db.thresholds(conn)
    cards = [fn(conn, th) for fn in SCORERS]
    return cards, composite(cards)
