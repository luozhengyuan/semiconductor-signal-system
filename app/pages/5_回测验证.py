# -*- coding: utf-8 -*-
"""回测验证：用历史综合评分作为信号，Backtrader 跑回测，对比买入持有基准"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import get_conn, inject_css  # noqa: E402
from sig import backtest, db  # noqa: E402

st.set_page_config(page_title="回测验证", page_icon="📊", layout="wide")
inject_css()
st.title("📊 回测验证：评分信号到底有没有用？")

# 如果 backtrader 未安装，显示安装提示并停止
if not backtest.HAS_BACKTRADER:
    st.error(
        "❌ 回测模块需要 `backtrader` 库，请先安装：\n\n"
        "```bash\n"
        "pip install backtrader\n"
        "```\n\n"
        "如果使用虚拟环境（如 `run_app.bat` 启动），请在对应环境中安装：\n\n"
        "```bash\n"
        '你的python路径\\Scripts\\pip.exe install backtrader\n'
        "```"
    )
    st.stop()

st.markdown(
    '<p class="knote">把历史信号（方向分 + 风险灯 → 目标仓位）作为交易信号，用 Backtrader 跑回测，'
    '对比"买入持有"基准。<b>这是把"经验规则"升级为"实测数据"的关键一步</b>。<br>'
    '⚠️ <b>数据限制</b>：系统从 2026-01 开始积累数据，回测窗口较短，结果<b>仅供参考</b>，'
    '不构成投资建议。随着 CI 自动积累，数据会越来越长，回测结果会越来越可靠。</p>',
    unsafe_allow_html=True,
)

conn = get_conn()

# ---- 数据状态预检 ----
scores = backtest.build_daily_scores(conn)
if scores.empty:
    st.warning("⚠️ 评分序列为空，请先到「数据更新」抓取数据。")
    conn.close()
    st.stop()

d = scores["direction"]
st.markdown(
    f'<div class="ksrc"><div class="t">📅 可回测区间</div>'
    f'<div class="row">评分序列：<b>{scores.index[0].date()} ~ {scores.index[-1].date()}</b>'
    f'（{(scores.index[-1] - scores.index[0]).days} 天，{len(scores)} 个评分点）</div>'
    f'<div class="row">方向分分布：🟢{(d > 0).sum()} 天 ｜ 🟡{((d == 0)).sum()} 天 ｜'
    f'🔴{(d < 0).sum()} 天 ｜ 风险灯亮起：{(scores["risk_on"] > 0).sum()} 天</div></div>',
    unsafe_allow_html=True,
)

# ---- 参数调节 ----
initial_cash = st.selectbox("初始资金", [100_000, 500_000, 1_000_000], index=2, format_func=lambda x: f"¥{x:,}")

st.markdown(
    '<p class="knote">交易规则（与首页新口径一致）：方向分（价格/营收/盈利 🔴−🟢）→ 基准仓位'
    '（+2→75% / +1→55% / 0→40% / −1→25% / ≤−2→10%），再乘风险折减'
    '（拥挤度/情绪每亮 1 盏灯 ×0.75，2 盏 ×0.5）得目标仓位<br>'
    '标的：6 只 A 股存储股等权组合（兆易创新/江波龙/佰维/德明利/香农/深科技）｜ '
    '基准：买入持有同一组合 | 手续费：0.1%</p>',
    unsafe_allow_html=True,
)

# ---- 运行回测 ----
if st.button("🚀 运行回测", type="primary"):
    with st.spinner("正在抓取个股日线数据（约 30 秒）…"):
        import akshare as ak
        price_data = backtest.build_price_data(conn)

    if not price_data:
        st.error("❌ 抓取个股日线失败，请检查网络后重试。")
        conn.close()
        st.stop()

    with st.spinner("正在跑 Backtrader 回测…"):
        result = backtest.run_backtest(
            conn, score_series=scores, price_data=price_data,
            initial_cash=initial_cash,
        )

    if "error" in result:
        st.error(f"❌ {result['error']}")
        conn.close()
        st.stop()

    st.session_state["backtest_result"] = result
    st.success(f"✅ 回测完成（{result['n_data_points']} 个交易日）")

# ---- 展示回测结果 ----
result = st.session_state.get("backtest_result")
if not result:
    st.caption("点上方「运行回测」开始。")
    conn.close()
    st.stop()

# 指标卡
st.subheader("📋 核心指标")
metrics = result["metrics"]
cols = st.columns(4)
keys = list(metrics.items())
for i, (k, v) in enumerate(keys[:8]):
    cols[i % 4].markdown(
        f'<div class="kcard"><div class="sname">{k}</div>'
        f'<div class="svalue">{v}</div></div>',
        unsafe_allow_html=True,
    )
cols = st.columns(4)
for i, (k, v) in enumerate(keys[8:]):
    cols[i % 4].markdown(
        f'<div class="kcard"><div class="sname">{k}</div>'
        f'<div class="svalue">{v}</div></div>',
        unsafe_allow_html=True,
    )

# 资金曲线
st.subheader("📈 资金曲线")
nav_df = result["nav_df"]
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=nav_df.index, y=nav_df["strategy"], name="策略（评分信号）",
    line=dict(color="#1B365D", width=2),
    hovertemplate="%{x|%Y-%m-%d}: ¥%{y:,.0f}<extra></extra>",
))
fig.add_trace(go.Scatter(
    x=nav_df.index, y=nav_df["benchmark"], name="基准（买入持有）",
    line=dict(color="#B7791F", width=1.5, dash="dash"),
    hovertemplate="%{x|%Y-%m-%d}: ¥%{y:,.0f}<extra></extra>",
))
fig.update_layout(
    height=400, margin=dict(l=20, r=20, t=10, b=20),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    yaxis=dict(title="资金（¥）", gridcolor="#e8e6dc"),
    xaxis=dict(gridcolor="#e8e6dc"),
)
st.plotly_chart(fig, use_container_width=True)

# 评分时间序列
st.subheader("🎯 方向分与目标仓位时间序列")
score_series = result["score_series"]
fig2 = go.Figure()
colors = ["#1B6B3A" if v > 0 else ("#B03A2E" if v < 0 else "#6b6a64")
          for v in score_series["direction"].values]
fig2.add_trace(go.Bar(
    x=score_series.index, y=score_series["direction"],
    marker_color=colors, name="方向分",
    hovertemplate="%{x|%Y-%m-%d}: %{y}<extra></extra>",
))
fig2.add_trace(go.Scatter(
    x=score_series.index, y=score_series["target"] * 100,
    name="目标仓位 %", yaxis="y2",
    line=dict(color="#B7791F", width=1.5, dash="dot"),
    hovertemplate="%{x|%Y-%m-%d}: %{y:.0f}%<extra></extra>",
))
fig2.update_layout(
    height=300, margin=dict(l=20, r=20, t=10, b=20),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    yaxis=dict(title="方向分", gridcolor="#e8e6dc", dtick=1),
    yaxis2=dict(title="目标仓位 %", overlaying="y", side="right",
                range=[0, 100], gridcolor="rgba(0,0,0,0)"),
    xaxis=dict(gridcolor="#e8e6dc"),
)
st.plotly_chart(fig2, use_container_width=True)

# 交易明细
trades = result["trades"]
if trades:
    st.subheader(f"📝 交易明细（{len(trades)} 笔）")
    trades_df = pd.DataFrame(trades)
    trades_df["date"] = pd.to_datetime(trades_df["date"]).dt.date
    trades_df["方向"] = trades_df["size"].apply(lambda s: "买入" if s > 0 else "卖出")
    trades_df["size"] = trades_df["size"].abs()
    trades_df["value"] = trades_df["value"].abs().round(0)
    trades_df["exec_price"] = trades_df["exec_price"].round(2)
    trades_df = trades_df.rename(columns={
        "date": "日期", "exec_price": "成交价", "size": "数量", "value": "金额(¥)",
    })
    st.dataframe(trades_df[["日期", "方向", "成交价", "数量", "金额(¥)"]],
                 use_container_width=True, hide_index=True)
else:
    st.info("回测期间无交易（评分信号始终在观望区间）。")

# 免责声明
st.divider()
st.markdown(
    '<div class="ksrc"><div class="t">⚠️ 重要说明</div>'
    '<div class="row">1. <b>数据量有限</b>：当前回测窗口仅半年左右，统计意义有限。'
    '请关注"策略与基准的相对表现"而非绝对收益。</div>'
    '<div class="row">2. <b>前视偏差已避免</b>：每个交易日只用<b>截至当日</b>已知信号，'
    '未来数据不会泄漏到过去。</div>'
    '<div class="row">3. <b>简化假设</b>：等权组合作为单一资产回测，未考虑停牌/涨跌停/滑点；'
    '实盘表现可能差于回测。</div>'
    '<div class="row">4. <b>本回测仅为方法验证</b>，不构成投资建议。</div></div>',
    unsafe_allow_html=True,
)

conn.close()
