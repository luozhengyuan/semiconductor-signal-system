# -*- coding: utf-8 -*-
"""映射分析：存储现货价信号 → 三只模组股（江波龙/佰维存储/德明利）的相关性验证

口径：CFM 周二报价日对齐个股周收益（W-TUE，前复权收盘价）；Pearson 相关。
样本区间自动取 dram_price 表覆盖范围（回填后约 24 周，随每周抓取增长）。
"""

import sys
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import get_conn, inject_css  # noqa: E402

st.set_page_config(page_title="映射分析", page_icon="🧭", layout="wide")
inject_css()
st.title("🧭 信号 → 模组股映射分析")
st.markdown(
    '<p class="knote">模组厂低价囤晶圆、高价卖模组，利润直接吃价差——理论上现货价对它们的映射最强。'
    '本页用真实数据验证：CFM 现货周涨跌 vs 个股周收益的相关系数 r。'
    'r≥0.4 记<b>强</b>，0.2~0.4 记<b>中</b>，&lt;0.2 记<b>弱</b>。样本随每周抓取积累，越久越可信。</p>',
    unsafe_allow_html=True,
)

MODULE_STOCKS = {"301308": "江波龙", "688525": "佰维存储", "001309": "德明利"}
SIGNAL_PRODUCTS = ["DDR5 16Gb Major", "DDR4 8Gb 3200"]  # 近半年最活跃的两个单品
AVG_LABEL = "8品均值"


@st.cache_data(ttl=43200, show_spinner=False)
def load_stock_close(code):
    """新浪源前复权日线（与拥挤度采集器同口径），缓存 12 小时"""
    prefix = "sh" if code.startswith("6") else "sz"
    df = ak.stock_zh_a_daily(symbol=f"{prefix}{code}", adjust="qfq")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["close"].astype(float)


@st.cache_data(ttl=600, show_spinner=False)
def load_signal_chg():
    """dram_price 透视成周度价格表，返回各产品周涨跌%（含 8 品均值列）"""
    conn = get_conn()
    px = pd.read_sql_query(
        "SELECT date, product, price FROM dram_price ORDER BY date",
        conn, parse_dates=["date"])
    conn.close()
    pv = px.pivot(index="date", columns="product", values="price")
    chg = pv.pct_change(fill_method=None) * 100
    chg[AVG_LABEL] = chg.mean(axis=1)
    return chg


def strength(r):
    if r is None or np.isnan(r):
        return "样本不足"
    if r >= 0.4:
        return "强"
    if r >= 0.2:
        return "中"
    return "弱"


def corr_series(sig, ret):
    m = pd.concat([sig.rename("sig"), ret.rename("ret")], axis=1).dropna()
    if len(m) < 3 or m["sig"].std() == 0:
        return None, m
    return m["sig"].corr(m["ret"]), m


chg = load_signal_chg()
if len(chg.dropna(how="all")) < 4:
    st.info("现货价历史不足 4 周。请先到「数据更新」页点「📥 回填存储现货价历史（近半年）」。")
    st.stop()

signal_cols = SIGNAL_PRODUCTS + [AVG_LABEL]
start = chg.index.min() - pd.Timedelta(days=10)

# ---- 汇总表 ----
rows, weekly = [], {}
fetch_failed = []
for code, name in MODULE_STOCKS.items():
    try:
        close = load_stock_close(code)
    except Exception:  # noqa: BLE001 - 单票失败不拖垮整页
        fetch_failed.append(name)
        continue
    w_ret = close[close.index >= start].resample("W-TUE").last().pct_change(fill_method=None) * 100
    weekly[name] = (close, w_ret)
    row = {"个股": name}
    for col in signal_cols:
        r, m = corr_series(chg[col], w_ret)
        row[col] = f"{r:.2f}（{strength(r)}）" if r is not None else "—"
        row["周样本"] = len(m)
    rows.append(row)

st.subheader("📊 映射力度总览（当周相关）")
if rows:
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
if fetch_failed:
    st.warning(f"行情抓取失败：{'、'.join(fetch_failed)}（检查网络/代理后刷新）")
if not rows:
    st.stop()

# ---- 个股详图：价格走势 vs 信号涨跌 + 散点 ----
for name, (close, w_ret) in weekly.items():
    sig = chg[AVG_LABEL]
    r, m = corr_series(sig, w_ret)
    st.subheader(f"{name}：{strength(r)}映射" + (f"（r={r:.2f}）" if r is not None else ""))

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=close[close.index >= chg.index.min()].index,
        y=close[close.index >= chg.index.min()],
        mode="lines", name="股价（前复权）",
        line=dict(color="#1B365D", width=1.8),
    ), secondary_y=False)
    colors = ["#1B6B3A" if v >= 0 else "#B03A2E" for v in sig.fillna(0)]
    fig.add_trace(go.Bar(
        x=sig.index, y=sig, name="现货价周涨跌%（8品均值）",
        marker_color=colors, opacity=0.55,
    ), secondary_y=True)
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=10, b=10), barmode="relative",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#faf9f5",
        legend=dict(orientation="h", y=1.12, font=dict(size=11)),
    )
    fig.update_yaxes(gridcolor="#e8e6dc", secondary_y=False)
    fig.update_yaxes(gridcolor="#e8e6dc", secondary_y=True, zerolinecolor="#c8c6bc")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    if len(m) >= 3 and m["sig"].std() > 0:
        k, b = np.polyfit(m["sig"], m["ret"], 1)
        xs = np.linspace(m["sig"].min(), m["sig"].max(), 20)
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=m["sig"], y=m["ret"], mode="markers", name="每周",
            marker=dict(color="#1B365D", size=7, opacity=0.7),
            hovertemplate="信号 %{x:.1f}% → 个股 %{y:.1f}%<extra></extra>",
        ))
        fig2.add_trace(go.Scatter(
            x=xs, y=k * xs + b, mode="lines", name=f"拟合线（斜率 {k:.2f}）",
            line=dict(color="#B03A2E", width=1.5, dash="dash"),
        ))
        fig2.update_layout(
            height=260, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#faf9f5",
            xaxis=dict(title="现货价周涨跌 %", gridcolor="#e8e6dc"),
            yaxis=dict(title="个股周收益 %", gridcolor="#e8e6dc"),
            legend=dict(orientation="h", y=1.15, font=dict(size=11)),
        )
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

# ---- 方法与局限 ----
st.markdown(
    """<div class="ksrc">
  <div class="row"><b>口径</b>：CFM 每周二报价；个股用新浪前复权日线重采样到同一周二（W-TUE）算周收益；Pearson 相关。</div>
  <div class="row" style="margin-top:6px;"><b>怎么读</b>：r 是<b>当周同步</b>相关——它回答"现货价动的时候这只股跟不跟"，不回答"现货价能不能预测下周"。
  实测信号领先 1 周的相关性全部归零，即现货价是<b>同步验证器</b>而非先行指标。</div>
  <div class="row" style="margin-top:6px;"><b>局限</b>：样本仅二十余周（随积累变可靠）；相关系数不区分牛熊段；
  DDR4 16Gb 3200 近半年钉死 $50 无波动，故单品选了活跃的 DDR5 16Gb Major 与 DDR4 8Gb 3200。不构成投资建议。</div>
</div>""",
    unsafe_allow_html=True,
)
