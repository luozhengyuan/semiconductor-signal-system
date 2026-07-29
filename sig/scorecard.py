# -*- coding: utf-8 -*-
"""
记分卡打分：五个信号 → 🟢🟡🔴⚪ → 综合评分。
所有规则透明、纯函数、可测试；阈值从 db.thresholds() 读（页面可调）。

灯的约定：
🟢 顺风（信号偏多/风险低）  🟡 中性  🔴 逆风（信号偏空/风险高）  ⚪ 数据积累中（不参与评分）
"""
import pandas as pd

from . import db

GREEN, YELLOW, RED, GRAY = "🟢", "🟡", "🔴", "⚪"


def _latest(conn, sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)


# ---------------- 1. 价格趋势 ----------------

def score_price(conn, th):
    """CFM 最新一期全部产品涨跌幅均值：>0 🟢，=0 🟡，<0 🔴"""
    df = _latest(conn, "SELECT * FROM dram_price WHERE date=(SELECT MAX(date) FROM dram_price)")
    if df.empty:
        return {"key": "dram_price", "name": "存储价格趋势", "light": GRAY,
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
        "key": "dram_price", "name": "存储价格趋势", "light": light,
        "value": f"周涨跌 {avg_chg:+.2f}%（{df['date'].iloc[0]}）",
        "detail": f"{len(df)} 个产品中 {n_up} 涨 {n_down} 跌；代表品 DDR4 16Gb 3200 现价 "
                  f"${df.loc[df['product'].str.contains('16Gb 3200', na=False), 'price'].max() or '—'}",
        "history": _latest(conn, "SELECT date, AVG(chg_pct) AS v FROM dram_price GROUP BY date ORDER BY date"),
        "talk": talk,
    }


# ---------------- 2. 台股月营收 ----------------

def score_tw_revenue(conn, th):
    """存储三家（南亚科/华邦电/旺宏）最新月营收同比均值：>20%🟢 0~20%🟡 <0%🔴"""
    df = _latest(conn, "SELECT * FROM tw_revenue WHERE month=(SELECT MAX(month) FROM tw_revenue)")
    if df.empty:
        return {"key": "tw_revenue", "name": "台系营收验证", "light": GRAY,
                "value": "无数据", "detail": "请到「数据更新」抓取", "history": None}
    watch = df[df["yoy_pct"].notna()]
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
    return {
        "key": "tw_revenue", "name": "台系营收验证", "light": light,
        "value": f"同比均值 {avg_yoy:+.1f}%（{df['month'].iloc[0]}）",
        "detail": names,
        "history": _latest(conn, "SELECT month AS date, AVG(yoy_pct) AS v FROM tw_revenue "
                                 "WHERE code IN ('2408','2344','2337') GROUP BY month ORDER BY month"),
        "talk": talk,
    }


# ---------------- 3. 盈利修正 ----------------

def score_profit(conn, th):
    """当年预测净利润合计：与上一快照比，>0🟢 ≈0🟡 <0🔴；不足两次快照 ⚪"""
    dates = [r["snap_date"] for r in conn.execute(
        "SELECT DISTINCT snap_date FROM profit_forecast ORDER BY snap_date DESC LIMIT 2")]
    if len(dates) < 2:
        return {"key": "profit_forecast", "name": "盈利预测修正", "light": GRAY,
                "value": "积累中", "detail": "需要至少两次快照（建议每周抓一次），暂不参与评分",
                "history": None}
    cur_year = dates[0][:4]
    def total(d):
        row = conn.execute(
            "SELECT SUM(mean) AS s FROM profit_forecast WHERE snap_date=? AND year=?",
            (d, cur_year)).fetchone()
        return row["s"] or 0
    latest, prev = total(dates[0]), total(dates[1])
    if prev == 0:
        chg = 0.0
    else:
        chg = (latest - prev) / prev * 100
    if chg > 0.1:
        light = GREEN
        talk = "分析师在上修盈利，周期上行段特征"
    elif chg < -0.1:
        light = RED
        talk = "盈利预测被下修，警惕行情进入尾声"
    else:
        light = YELLOW
        talk = "盈利预测持平，等待新催化"
    return {
        "key": "profit_forecast", "name": "盈利预测修正", "light": light,
        "value": f"修正 {chg:+.2f}%（{cur_year} 年预测）",
        "detail": f"{dates[1]} → {dates[0]}，6 只标的当年预测净利润合计",
        "history": _latest(conn, "SELECT snap_date AS date, SUM(mean) AS v FROM profit_forecast "
                                 "WHERE year=strftime('%Y', snap_date) GROUP BY snap_date ORDER BY snap_date"),
        "talk": talk,
    }


# ---------------- 4. 拥挤度 ----------------

def score_crowding(conn, th):
    """最新量比：>2🔴 1~2🟡 <1🟢（越挤越危险，注意方向是反的）"""
    df = _latest(conn, "SELECT * FROM crowding ORDER BY trade_date DESC LIMIT 1")
    if df.empty:
        return {"key": "crowding", "name": "板块拥挤度", "light": GRAY,
                "value": "无数据", "detail": "请到「数据更新」抓取", "history": None}
    ratio = float(df["ratio20"].iloc[0])
    if ratio > th["crowding_red"]:
        light = RED
        talk = "成交爆量，短线资金拥挤，控制仓位"
    elif ratio >= 1.0:
        light = YELLOW
        talk = "成交温和放大，留意是否持续"
    else:
        light = GREEN
        talk = "成交清淡，筹码不拥挤"
    return {
        "key": "crowding", "name": "板块拥挤度", "light": light,
        "value": f"量比 {ratio:.2f}（{df['trade_date'].iloc[0]}）",
        "detail": "6 只标的合计成交额 / 其 20 日均值；>2 为拥挤",
        "history": _latest(conn, "SELECT trade_date AS date, ratio20 AS v FROM crowding ORDER BY trade_date"),
        "talk": talk,
    }


# ---------------- 5. 热搜热度 ----------------

def score_heat(conn, th):
    """最新热度在 60 日中的分位：>90%🔴 >50%🟡 其他🟢（反向指标！）"""
    df = _latest(conn, "SELECT * FROM hot_heat ORDER BY snap_date DESC LIMIT 60")
    if df.empty:
        return {"key": "hot_heat", "name": "热搜情绪温度", "light": GRAY,
                "value": "无数据", "detail": "依赖热榜雷达快照积累", "history": None}
    latest = float(df["heat"].iloc[0])
    pct = float((df["heat"] <= latest).mean() * 100)
    if pct > th["heat_pct_red"]:
        light = RED
        talk = "情绪爆表！实证：这是见顶警报，别加仓"
    elif pct > th["heat_pct_yellow"]:
        light = YELLOW
        talk = "情绪升温中，保持关注但不追"
    else:
        light = GREEN
        talk = "情绪冷清，没有过热风险"
    return {
        "key": "hot_heat", "name": "热搜情绪温度", "light": light,
        "value": f"热度 {latest:.0f}（{pct:.0f} 分位）",
        "detail": f"{df['snap_date'].iloc[0]}；60 日分位，>90 分位为爆表（实证反向指标）",
        "history": _latest(conn, "SELECT snap_date AS date, heat AS v FROM hot_heat ORDER BY snap_date"),
        "talk": talk,
    }


SCORERS = [score_price, score_tw_revenue, score_profit, score_crowding, score_heat]


def composite(cards):
    """综合评分 = 🟢数 − 🔴数（⚪ 不参与），返回 (score, 白话解读, 仓位参考)"""
    lights = [c["light"] for c in cards]
    n_g, n_r = lights.count(GREEN), lights.count(RED)
    score = n_g - n_r
    valid = len([l for l in lights if l != GRAY])
    if score >= 3:
        pos, ref = "周期上行确认，信号共振偏多", "正常仓位，按纪律持有"
    elif score >= 1:
        pos, ref = "偏多但有分歧，上行动能不完整", "中性偏积极，别追高加仓"
    elif score <= -3:
        pos, ref = "风险信号共振，防御优先", "显著降仓，等待信号修复"
    elif score <= -1:
        pos, ref = "偏空或有拥挤/情绪风险", "控制仓位，提高警惕"
    else:
        pos, ref = "多空均衡，方向不明", "观望为主，小仓位试探"
    return {
        "score": score, "n_green": n_g, "n_red": n_r, "n_valid": valid,
        "position": pos, "reference": ref,
    }


def build_scorecard(conn):
    th = db.thresholds(conn)
    cards = [fn(conn, th) for fn in SCORERS]
    return cards, composite(cards)
