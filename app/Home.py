# -*- coding: utf-8 -*-
"""半导体信号系统 · 记分卡 Dashboard（首页）"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import data_status_panel, get_conn, inject_css, mini_chart, signal_card  # noqa: E402
from sig import db, scorecard  # noqa: E402

st.set_page_config(page_title="半导体信号系统", page_icon="📡", layout="wide")
inject_css()

st.title("📡 半导体信号记分卡")
st.markdown(
    '<p class="knote">回答一个问题：<b>存储/半导体现在处于周期什么位置？</b>'
    '五个公开数据信号，三盏灯，一张卡。先去「数据更新」抓取最新数据，再回来看灯。</p>',
    unsafe_allow_html=True,
)

conn = get_conn()
cards, comp = scorecard.build_scorecard(conn)
overview = db.data_overview(conn)
conn.close()

# ---- 数据库状态（避免无效重复更新）----
data_status_panel(overview, action_hint=" → 去「数据更新」页点一键更新")

# ---- 综合评分横幅：方向分定基调 + 风险灯折减仓位 ----
d_cards = [c for c in cards if c.get("kind") == "direction"]
r_cards = [c for c in cards if c.get("kind") == "risk"]
d_lights_str = " ".join(c["light"] for c in d_cards)
r_lights_str = " ".join(c["light"] for c in r_cards)
st.markdown(
    f"""<div class="kbanner">
  <div style="display:flex;align-items:baseline;gap:18px;flex-wrap:wrap;">
    <span class="score">{comp['score']:+d}</span>
    <span style="font-size:20px;">{d_lights_str}</span>
    <span style="font-size:13px;color:#6b6a64;">方向分（产业信号）</span>
    <span style="font-size:20px;margin-left:14px;">{r_lights_str}</span>
    <span style="font-size:13px;color:#6b6a64;">风险灯（拥挤/情绪）</span>
  </div>
  <div class="pos">{comp['position']}</div>
  <div class="ref">仓位参考：基准 {comp['base']} × 风险折减 {comp['deduction']:.0%}（{comp['risk_note']}）</div>
  <div class="disclaimer">⚠️ 经验规则，未经回测，不构成投资建议。方向分 = 产业信号（价格/营收/盈利）🔴−🟢（⚪ 积累中不计）；
  拥挤度与情绪是风险灯，只折减仓位、不改方向判断——🟢 显示 = 危险（A股红涨绿跌）。</div>
</div>""",
    unsafe_allow_html=True,
)

# ---- 五张信号卡（3 方向 + 2 风险 两行）----
for row in (cards[:3], cards[3:]):
    cols = st.columns(len(row))
    for col, card in zip(cols, row):
        with col:
            signal_card(card)
            hist = card.get("history")
            if hist is not None and len(hist) >= 2:
                st.plotly_chart(mini_chart(hist), use_container_width=True,
                                config={"displayModeBar": False})

# ---- 白话教程（折叠）----
with st.expander("💡 怎么看懂这些灯？（3 分钟白话版）"):
    st.markdown("""
**这套系统在干什么？** 存储是强周期行业：价格涨 → 公司赚钱 → 股价涨；价格跌 → 全线承压。
关键是——**股价跑在基本面前面**，等你从财报看到拐点，行情早走了一半。所以我们盯住
比财报更快的五类信号，并把它们分成两组：

**第一组 · 方向信号（定多空基调，构成方向分）**

- **🔴 存储价格趋势**：DRAM 现货价是行业的体温计，价格拐点领先业绩 1~2 个季度
- **🔴 台系营收验证**：台湾上市公司每月必须公布营收，南亚科等存储厂的同比是造不了假的景气刻度
- **⚪ 盈利预测修正**：分析师不断上修盈利 = 周期上行段；开始下修 = 行情尾声（需积累两次快照）

**第二组 · 风险信号（不判断方向，只决定用几成仓）**

- **🟢 板块拥挤度**：成交额爆到平时 2 倍以上 = 太挤了，任何利空都会踩踏。方向是反的：越挤越绿。
  量比 <1 的缩量不再直接视为利好——上涨段缩量 = 惜售（健康），下跌段缩量 = 承接乏力（观望）
- **🟢 情绪热度**：雪球讨论榜 + 百度股票热搜 + 微博热搜三源合成，衡量散户注意力。
  实证证明——热度爆表是**见顶警报**，不是买入信号

**怎么用？** 方向分 = 第一组 🔴 − 🟢，决定基准仓位（+2 → 7~8 成，0 → 3~5 成，−2 → 0~2 成）；
再乘上风险折减（每亮 1 盏风险灯打 75 折，2 盏齐亮减半）。两组信号各司其职：
"产业趋势完好但情绪过热"时，方向分依旧偏多，但仓位会被打折——这正是等权加减会丢失的信息。

更完整的讲解在左侧「新手教程」页；每个信号的来龙去脉在「信号详情」页。
""")

st.markdown(
    '<p class="knote">数据源详情与更新记录见「数据更新」页 ｜ 全部信号规则公开可调，见「信号详情」页</p>',
    unsafe_allow_html=True,
)
