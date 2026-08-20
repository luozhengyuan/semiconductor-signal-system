# -*- coding: utf-8 -*-
"""
Backtrader 回测模块。

核心思路（2026-08-18 起与 scorecard 新口径一致）：
1. 从 db 读取 5 个信号的历史数据，对每个交易日重新计算（与 scorecard.py 同逻辑）
2. 方向分 = 产业信号（价格/营收/盈利）🔴−🟢，范围 -3 ~ +3
3. 风险灯 = 拥挤度/情绪中危险灯数量；目标仓位 = 基准仓位 × 风险折减（每灯 -25%）
4. 标的为 STOCK_POOL 的 6 只股票等权组合
5. 与"买入持有"基准对比，输出夏普/最大回撤/年化收益/资金曲线

数据限制：
- 5 个信号频率不一（价格周度/营收月度/盈利周度/拥挤度日度/热搜日度）
- 用 forward-fill 对齐到日度，信号在下次更新前保持不变
- 系统从 2026-01 开始积累数据，回测窗口受限于最短信号
"""
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, db, scorecard

try:
    import backtrader as bt
    HAS_BACKTRADER = True
except ImportError:
    bt = None
    HAS_BACKTRADER = False


# ---------------- 1. 历史评分序列构造 ----------------

def _price_score_series(conn):
    """存储价格趋势：每日按"当周全部产品涨跌幅均值"打分，>0🔴 =0🟡 <0🟢"""
    df = pd.read_sql_query(
        "SELECT date, AVG(chg_pct) AS avg_chg FROM dram_price "
        "GROUP BY date ORDER BY date", conn)
    if df.empty:
        return pd.Series(dtype=float)
    df["score"] = df["avg_chg"].apply(
        lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    s = df.set_index(pd.to_datetime(df["date"]))["score"]
    return s.resample("D").ffill()


def _tw_revenue_score_series(conn, th):
    """台系月营收：每月按"存储三家同比均值"打分，>threshold🔴 0~threshold🟡 <0🟢"""
    df = pd.read_sql_query(
        "SELECT month, AVG(yoy_pct) AS avg_yoy FROM tw_revenue "
        "WHERE code IN ('2408','2344','2337') GROUP BY month ORDER BY month", conn)
    if df.empty:
        return pd.Series(dtype=float)
    g = th["tw_yoy_green"]
    df["score"] = df["avg_yoy"].apply(
        lambda x: 1 if x > g else (-1 if x < 0 else 0))
    s = df.set_index(pd.to_datetime(df["month"] + "-01"))["score"]
    return s.resample("D").ffill()


def _profit_score_series(conn):
    """盈利预测修正：每个快照日按"当年预测合计与上次比"打分，>0.1%🔴 <-0.1%🟢 否则🟡"""
    df = pd.read_sql_query(
        "SELECT snap_date, year, SUM(mean) AS total FROM profit_forecast "
        "GROUP BY snap_date, year ORDER BY snap_date, year", conn)
    if df.empty:
        return pd.Series(dtype=float)
    # 每个快照日的"当年"预测合计
    df["cur_year"] = df["snap_date"].str[:4]
    df = df[df["year"] == df["cur_year"]]
    pivot = df.groupby("snap_date")["total"].sum().sort_index()
    if len(pivot) < 2:
        return pd.Series(dtype=float)
    chg = pivot.pct_change() * 100
    score = chg.apply(
        lambda x: 1 if x > 0.1 else (-1 if x < -0.1 else 0)).fillna(0)
    s = score.copy()
    s.index = pd.to_datetime(s.index)
    return s.resample("D").ffill()


def _crowding_score_series(conn, th):
    """拥挤度（风险灯）：>red 危险(-1)；1~red 🟡；<1 结合价格背景——
    有 close 数据：上行段缩量惜售(+1)/下行段承接乏力(0)；无 close 历史：中性(0)"""
    df = pd.read_sql_query(
        "SELECT trade_date, ratio20, close FROM crowding ORDER BY trade_date", conn)
    if df.empty:
        return pd.Series(dtype=float)
    red = th["crowding_red"]
    idx = pd.to_datetime(df["trade_date"])
    # 价格背景：20 日滚动窗口，最新收盘处上半区且 5 日均价 ≥ 20 日均价
    c = df["close"]
    has_close = c.notna()
    c = c.ffill()
    win_pos = (c - c.rolling(20, min_periods=10).min()) / (
        c.rolling(20, min_periods=10).max() - c.rolling(20, min_periods=10).min())
    ma5, ma20 = c.rolling(5, min_periods=3).mean(), c.rolling(20, min_periods=10).mean()
    up = has_close & (win_pos >= 0.5) & (ma5 >= ma20)

    def _score(row):
        ratio = row["ratio20"]
        if ratio > red:
            return -1
        if ratio >= 1.0:
            return 0
        return 1 if row["up"] else 0  # <1：上行段缩量才给偏多分

    df["up"] = up
    df["score"] = df.apply(_score, axis=1)
    s = pd.Series(df["score"].values, index=idx)
    return s.resample("D").ffill()


def _heat_score_series(conn, th):
    """情绪热度（风险灯）：heat=0 中性(0，零膨胀防护)；非零按绝对热度分档，
    ≥abs_red 危险(-1) ≥abs_yellow 🟡(0) 其他(+1)（反向指标，与 scorecard 积累期口径一致）"""
    df = pd.read_sql_query(
        "SELECT snap_date, heat FROM hot_heat ORDER BY snap_date", conn)
    if df.empty:
        return pd.Series(dtype=float)
    df["snap_date"] = pd.to_datetime(df["snap_date"])
    df = df.set_index("snap_date").sort_index()
    abs_red, abs_yellow = th["heat_abs_red"], th["heat_abs_yellow"]
    score = pd.Series(0, index=df.index, dtype=float)
    nonzero = df["heat"] > 0
    score[nonzero] = df["heat"][nonzero].apply(
        lambda v: -1 if v >= abs_red else (0 if v >= abs_yellow else 1))
    return score


def build_daily_scores(conn, th=None, min_signals=3):
    """构造每日「方向分 + 风险灯 + 目标仓位」序列（与 scorecard.composite 同口径）。

    返回 pd.DataFrame，index 为日期，列：
    - direction: 方向分 = 产业信号 🔴−🟢（-3 ~ +3，缺失信号按 0 中性）
    - risk_on:   亮起的风险灯数（0~2）
    - target:    目标仓位 = 基准仓位 × 风险折减（0.1 ~ 0.75）

    min_signals: 至少要有这么多信号有真实数据（非 fillna 补的 0）才返回评分。
                默认 3，避免只有拥挤度一个信号时误导回测。
    """
    if th is None:
        th = db.thresholds(conn)

    series = {
        "price": _price_score_series(conn),
        "tw_revenue": _tw_revenue_score_series(conn, th),
        "profit": _profit_score_series(conn),
        "crowding": _crowding_score_series(conn, th),
        "heat": _heat_score_series(conn, th),
    }
    # 各信号 forward-fill 延伸到今天（周度/月度/快照序列的 resample 只到其最后一个数据点，
    # 不延伸会导致最近几天信号缺失按中性 0 处理——旧版隐藏 bug）
    end = pd.Timestamp.today().normalize()
    series = {
        k: (s.reindex(pd.date_range(s.index.min(), end, freq="D"), method="ffill")
            if not s.empty else s)
        for k, s in series.items()
    }

    # 对齐到同一日期范围
    df = pd.DataFrame(series)
    # 记录每个信号"首次有真实数据"的日期
    first_valid = {k: s.first_valid_index() for k, s in series.items() if not s.empty}
    if len(first_valid) < min_signals:
        # 信号太少，返回空
        return pd.DataFrame()

    # 只保留至少 min_signals 个信号都有真实数据的窗口
    start_date = sorted(first_valid.values())[min_signals - 1]
    df = df.loc[df.index >= start_date]

    df = df.dropna(how="all")
    df = df.fillna(0)  # 某信号缺失视为中性

    df["direction"] = df[["price", "tw_revenue", "profit"]].sum(axis=1)
    df["risk_on"] = ((df["crowding"] == -1).astype(int)
                     + (df["heat"] == -1).astype(int))

    # 方向分 → 基准仓位（与 scorecard.composite 的基准仓位区间取中值）
    base = df["direction"].apply(
        lambda s: 0.75 if s >= 2 else (0.55 if s == 1 else (0.40 if s == 0 else (0.25 if s == -1 else 0.10))))
    df["target"] = (base * (1 - 0.25 * df["risk_on"])).round(3)
    return df[["direction", "risk_on", "target"]]


# ---------------- 2. 标的日线数据 ----------------

def build_price_data(conn):
    """从 crowding 表已有数据反推不出个股价格；直接用 akshare 抓 STOCK_POOL 日线。

    返回 dict: {code: DataFrame[date, open, high, low, close, volume]}
    """
    import akshare as ak
    frames = {}
    for code in config.STOCK_POOL:
        prefix = "sh" if code.startswith("6") else "sz"
        try:
            df = ak.stock_zh_a_daily(symbol=f"{prefix}{code}", adjust="qfq")
        except Exception:  # noqa: BLE001
            continue
        if df is None or len(df) == 0:
            continue
        df = df.rename(columns={"date": "date", "open": "open", "high": "high",
                                "low": "low", "close": "close", "volume": "volume"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        frames[code] = df[["open", "high", "low", "close", "volume"]]
    return frames


def build_equal_weight_index(price_data):
    """从个股日线构造等权基准（每日按收盘价等权再平衡）。

    返回 DataFrame[date, open, high, low, close, volume]，便于注入 Backtrader。
    """
    if not price_data:
        return pd.DataFrame()
    closes = pd.DataFrame({code: df["close"] for code, df in price_data.items()})
    closes = closes.dropna(how="all").sort_index()
    # 等权组合的日收益率
    daily_ret = closes.pct_change().mean(axis=1)
    # 累计净值
    nav = (1 + daily_ret.fillna(0)).cumprod() * 100
    nav.name = "close"
    out = pd.DataFrame(nav)
    out["open"] = out["close"]
    out["high"] = out["close"]
    out["low"] = out["close"]
    out["volume"] = 0
    return out[["open", "high", "low", "close", "volume"]]


# ---------------- 3. Backtrader 策略 ----------------

class ScoreStrategy(bt.Strategy):
    """按目标仓位序列调仓：target = 基准仓位（方向分）× 风险折减（风险灯）。

    params:
        score_series: pd.DataFrame，index 为日期，须含 target 列（0~1 目标仓位比例）
    """
    params = (
        ("score_series", None),
    )

    def __init__(self):
        self.target_series = self.params.score_series["target"]
        self.trade_records = []  # 记录每次调仓
        self.order = None

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            if order.status == order.Completed:
                self.trade_records.append({
                    "date": self.data.datetime.date(0),
                    "exec_price": order.executed.price,
                    "size": order.executed.size,
                    "value": order.executed.value,
                })
            self.order = None

    def next(self):
        if self.order:
            return
        today = self.data.datetime.date(0)
        # 找最近一个目标仓位（序列可能没有今天，取 <= today 的最后一个）
        try:
            target = self.target_series.loc[:pd.Timestamp(today)].iloc[-1]
        except (KeyError, IndexError):
            return
        if pd.isna(target):
            return
        cur = self.position.size if self.position else 0
        if abs(target - cur) < 0.01:
            return  # 变动不足 1% 不动，避免琐碎调仓
        self.order = self.order_target_percent(target=float(target))


# ---------------- 4. 回测主函数 ----------------

def run_backtest(conn, score_series=None, price_data=None,
                 initial_cash=1_000_000, commission=0.001):
    """跑回测，返回 dict（指标 + 资金曲线 + 交易明细）。

    若不传 score_series / price_data，自动从 db 构造。
    score_series 为 build_daily_scores 的 DataFrame（direction/risk_on/target）。
    """
    if not HAS_BACKTRADER:
        return {"error": "未安装 backtrader，请运行 pip install backtrader"}
    if score_series is None:
        score_series = build_daily_scores(conn)
    if price_data is None:
        price_data = build_price_data(conn)

    if not price_data or getattr(score_series, "empty", True):
        return {"error": "数据不足，无法回测（需要至少两只股票的日线 + 评分序列）"}

    # 构造等权基准作为回测标的（简化：把组合当成一个资产）
    benchmark = build_equal_weight_index(price_data)
    if benchmark.empty:
        return {"error": "等权基准构造失败"}

    # 对齐日期范围：以评分序列的起点为准，避免基准历史过长误导回测
    score_start = score_series.index[0]
    benchmark = benchmark.loc[benchmark.index >= score_start]
    if benchmark.empty:
        return {"error": "评分序列与价格数据无交集"}

    # Backtrader 设置
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)

    data = bt.feeds.PandasData(dataname=benchmark)
    cerebro.adddata(data)
    cerebro.addstrategy(ScoreStrategy, score_series=score_series)

    # 分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="timereturn", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    results = cerebro.run()
    strat = results[0]
    final_value = cerebro.broker.getvalue()

    # 提取指标
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis()
    ret = strat.analyzers.returns.get_analysis()
    tr = strat.analyzers.trades.get_analysis()
    timeret = strat.analyzers.timereturn.get_analysis()

    # 策略资金曲线
    strategy_nav = pd.Series(timeret).add(1).cumprod() * initial_cash
    strategy_nav.name = "strategy"

    # 基准（买入持有）资金曲线
    benchmark_nav = benchmark["close"] / benchmark["close"].iloc[0] * initial_cash
    benchmark_nav.name = "benchmark"

    # 对齐
    nav_df = pd.concat([strategy_nav, benchmark_nav], axis=1).dropna()

    # 交易明细（每次调仓记录）
    trade_list = strat.trade_records if hasattr(strat, "trade_records") else []

    # 计算年化收益（按实际回测天数）
    n_days = (nav_df.index[-1] - nav_df.index[0]).days
    n_years = max(n_days / 365.25, 1/365.25)
    strat_total_ret = (nav_df["strategy"].iloc[-1] / initial_cash - 1) * 100
    bench_total_ret = (nav_df["benchmark"].iloc[-1] / initial_cash - 1) * 100
    strat_ann_ret = ((nav_df["strategy"].iloc[-1] / initial_cash) ** (1 / n_years) - 1) * 100
    bench_ann_ret = ((nav_df["benchmark"].iloc[-1] / initial_cash) ** (1 / n_years) - 1) * 100

    return {
        "metrics": {
            "回测区间": f"{nav_df.index[0].date()} ~ {nav_df.index[-1].date()}（{n_days} 天）",
            "初始资金": f"¥{initial_cash:,.0f}",
            "最终资金": f"¥{final_value:,.0f}",
            "策略总收益": f"{strat_total_ret:+.2f}%",
            "基准总收益": f"{bench_total_ret:+.2f}%",
            "策略年化": f"{strat_ann_ret:+.2f}%",
            "基准年化": f"{bench_ann_ret:+.2f}%",
            "超额收益": f"{strat_total_ret - bench_total_ret:+.2f}%",
            "夏普比率": f"{sharpe.get('sharperatio', 0) or 0:.3f}",
            "最大回撤": f"{dd.get('drawdown', 0):.2f}%",
            "回撤持续": f"{dd.get('len', 0)} 天",
            "交易次数": f"{tr.get('total', {}).get('total', 0)}",
            "胜率": f"{(tr.get('won', {}).get('total', 0) / max(tr.get('total', {}).get('total', 1), 1) * 100):.1f}%",
        },
        "nav_df": nav_df,
        "score_series": score_series,
        "trades": trade_list,
        "n_data_points": len(nav_df),
    }
