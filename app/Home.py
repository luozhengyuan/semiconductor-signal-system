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

# ---- 综合评分横幅 ----
lights_str = " ".join(c["light"] for c in cards)
st.markdown(
    f"""<div class="kbanner">
  <div style="display:flex;align-items:baseline;gap:18px;flex-wrap:wrap;">
    <span class="score">{comp['score']:+d}</span>
    <span style="font-size:20px;">{lights_str}</span>
  </div>
  <div class="pos">{comp['position']}</div>
  <div class="ref">仓位参考：{comp['reference']}（{comp['n_valid']}/5 个信号参与评分，🟢{comp['n_green']} 🔴{comp['n_red']}）</div>
  <div class="disclaimer">⚠️ 经验规则，未经回测，不构成投资建议。评分 = 🟢数 − 🔴数；⚪ 为数据积累中，暂不参与。</div>
</div>""",
    unsafe_allow_html=True,
)

# ---- 五张信号卡（3+2 两行）----
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
比财报更快的五类信号：

- **🟢 存储价格趋势**：DRAM 现货价是行业的体温计，价格拐点领先业绩 1~2 个季度
- **🟢 台系营收验证**：台湾上市公司每月必须公布营收，南亚科等存储厂的同比是造不了假的景气刻度
- **⚪ 盈利预测修正**：分析师不断上修盈利 = 周期上行段；开始下修 = 行情尾声（需积累两次快照）
- **🟢 板块拥挤度**：成交额爆到平时 2 倍以上 = 太挤了，任何利空都会踩踏（注意这盏灯方向是反的：越挤越红）
- **🟢 热搜情绪温度**：我们的实证研究证明——热度爆表是**见顶警报**，不是买入信号

**怎么用？** 看综合评分：≥+3 信号共振偏多，正常持有；≤−3 风险共振，显著降仓；中间状态控制仓位别追高。
单独的 🔴 也值得重视——尤其是拥挤度和热搜这两盏"风险灯"。

更完整的讲解在左侧「新手教程」页；每个信号的来龙去脉在「信号详情」页。
""")

st.markdown(
    '<p class="knote">数据源详情与更新记录见「数据更新」页 ｜ 全部信号规则公开可调，见「信号详情」页</p>',
    unsafe_allow_html=True,
)
