# -*- coding: utf-8 -*-
"""信号详情：历史曲线 + 阈值调整 + 白话原理长文"""

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import get_conn, inject_css  # noqa: E402
from sig import db, scorecard  # noqa: E402
from sig.sources import SOURCES  # noqa: E402

st.set_page_config(page_title="信号详情", page_icon="🔍", layout="wide")
inject_css()
st.title("🔍 信号详情")

conn = get_conn()
cards, _ = scorecard.build_scorecard(conn)
options = {f"{c['light']} {c['name']}": c for c in cards}
picked = st.selectbox("选择要深入的信号", list(options.keys()))
card = options[picked]
key = card["key"]
src = SOURCES[key]

# ---- 当前状态 ----
st.markdown(
    f"""<div class="kbanner">
  <div class="pos">{card['light']} {card['name']}：{card['value']}</div>
  <div class="ref">{card.get('talk', '')}</div>
  <div class="disclaimer">{card.get('detail', '')}</div>
</div>""",
    unsafe_allow_html=True,
)

# ---- 历史曲线 ----
hist = card.get("history")
if hist is not None and len(hist) >= 2:
    fig = go.Figure(go.Scatter(
        x=hist["date"], y=hist["v"], mode="lines+markers",
        line=dict(color="#1B365D", width=2), marker=dict(size=5),
        hovertemplate="%{x}: %{y:.2f}<extra></extra>",
    ))
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#faf9f5",
        xaxis=dict(gridcolor="#e8e6dc"), yaxis=dict(gridcolor="#e8e6dc"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
else:
    st.info("历史数据不足（需要多次抓取积累），曲线将在数据充足后显示。")

# ---- 白话原理 ----
st.subheader("💡 这个信号为什么可信")
st.markdown(
    f"""<div class="ksrc">
  <div class="row">{src['principle']}</div>
  <div class="row" style="margin-top:8px;"><b>局限性（同样重要）</b>：{src['limit']}</div>
  <div class="row" style="margin-top:8px;"><b>数据来源</b>：{src['url']} ｜ <b>频率</b>：{src['freq']}</div>
</div>""",
    unsafe_allow_html=True,
)

# ---- 阈值调整 ----
th = db.thresholds(conn)
THRESHOLD_UI = {
    "tw_revenue": [("tw_yoy_green", "营收同比绿灯线（%）", 0.0, 100.0)],
    "crowding": [("crowding_red", "拥挤度红灯线（量比）", 1.0, 5.0)],
    "hot_heat": [("heat_pct_red", "情绪爆表红线（60日分位）", 50.0, 99.0),
                 ("heat_pct_yellow", "情绪升温黄线（60日分位）", 10.0, 90.0)],
}
if key in THRESHOLD_UI:
    st.subheader("⚙️ 打分阈值（调整后即时生效，永久保存）")
    for skey, label, lo, hi in THRESHOLD_UI[key]:
        cur = float(th[skey])
        new = st.slider(label, lo, hi, cur, key=skey)
        if new != cur:
            db.set_setting(conn, skey, new)
            st.toast(f"已保存：{label} = {new}")
            st.rerun()
else:
    st.caption("该信号使用固定规则（涨🟢 平🟡 跌🔴 / 修正方向），无可调阈值。")

conn.close()
