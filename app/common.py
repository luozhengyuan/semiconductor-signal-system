# -*- coding: utf-8 -*-
"""
页面公共工具：连接、全局样式（kami 暖纸风）、信号卡组件
重要：SQLite 连接绝不缓存进 st.session_state（跨线程报错），每次新建。
"""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sig import db  # noqa: E402


def get_conn():
    """每次新建 SQLite 连接（绝不缓存）"""
    return db.get_conn()


PAGE_CSS = """
<style>
/* kami 暖纸风：羊皮纸底、墨蓝单强调、卡片式 */
.stApp { background: #f5f4ed; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 2rem; max-width: 1100px; }
h1, h2, h3 { color: #141413; font-weight: 500; }

.kcard {
  background: #faf9f5;
  border: 0.5pt solid #e8e6dc;
  border-radius: 10px;
  padding: 16px 18px 12px 18px;
  margin-bottom: 14px;
  min-height: 150px;
}
.kcard .light { font-size: 26px; line-height: 1; }
.kcard .sname { font-size: 15px; font-weight: 600; color: #141413; margin: 6px 0 2px 0; }
.kcard .svalue { font-size: 14px; color: #1B365D; font-weight: 600; margin-bottom: 4px; }
.kcard .stalk { font-size: 12.5px; color: #504e49; line-height: 1.5; }
.kcard .sdetail { font-size: 11px; color: #6b6a64; margin-top: 6px; line-height: 1.5; }

.kbanner {
  background: #faf9f5;
  border-left: 4px solid #1B365D;
  border-radius: 10px;
  padding: 18px 22px;
  margin: 10px 0 18px 0;
}
.kbanner .score { font-size: 34px; font-weight: 600; color: #1B365D; }
.kbanner .pos { font-size: 16px; color: #141413; font-weight: 600; margin-top: 2px; }
.kbanner .ref { font-size: 13px; color: #504e49; margin-top: 2px; }
.kbanner .disclaimer { font-size: 11px; color: #6b6a64; margin-top: 8px; }

.ksrc {
  background: #faf9f5; border: 0.5pt solid #e8e6dc; border-radius: 10px;
  padding: 14px 18px; margin-bottom: 12px;
}
.ksrc .t { font-size: 15px; font-weight: 600; color: #141413; }
.ksrc .row { font-size: 12.5px; color: #504e49; margin-top: 4px; line-height: 1.55; }
.ksrc .row b { color: #3d3d3a; font-weight: 600; }
.ksrc .ok { color: #1B6B3A; font-weight: 600; }
.ksrc .fail { color: #B03A2E; font-weight: 600; }

.knote { font-size: 12px; color: #6b6a64; line-height: 1.6; }
a { color: #1B365D; }
</style>
"""


def inject_css():
    st.markdown(PAGE_CSS, unsafe_allow_html=True)


def data_status_panel(overview, action_hint=""):
    """数据库状态栏：各源数据到哪天/是否新鲜，headline 给出是否要更新的结论"""
    stale = [o for o in overview if not o["fresh"]]
    blocked = [o for o in stale if "mrs.db" in o.get("note", "")]  # 点更新也变不新的外部依赖
    updatable = [o for o in stale if o not in blocked]
    parts = []
    if updatable:
        parts.append(f"🟡 {len(updatable)} 个数据源有新数据可抓："
                     f"{'、'.join(o['name'] for o in updatable)}{action_hint}")
    if blocked:
        parts.append(f"ℹ️ {'、'.join(o['name'] for o in blocked)} 停在旧数据，"
                     "但原因在上游（见下方说明），点更新解决不了")
    headline = "<br>".join(parts) if parts else "✅ 数据库已是最新，现在无需更新"
    rows = "".join(
        f"<div class='row'><b>{o['name']}</b>：数据到 {o['latest'] or '—'}"
        f"（{o['rows']:,} 行，{o['span']}）｜ 最近抓取 {o['last_fetch'] or '从未'} "
        + ("<span class='ok'>✅ 最新</span>" if o["fresh"]
           else "<span style='color:#B7791F;font-weight:600;'>🟡 可更新</span>")
        + (f"<br><span style='color:#6b6a64;font-size:11.5px;'>↳ {o['note']}</span>"
           if o.get("note") else "")
        + "</div>"
        for o in overview
    )
    st.markdown(
        f"""<div class="ksrc">
  <div class="t">{headline}</div>
  {rows}
</div>""",
        unsafe_allow_html=True,
    )


def signal_card(card):
    """渲染一张信号卡（纯 HTML，保持整页风格统一）"""
    st.markdown(
        f"""<div class="kcard">
  <div class="light">{card['light']}</div>
  <div class="sname">{card['name']}</div>
  <div class="svalue">{card['value']}</div>
  <div class="stalk">{card.get('talk', '')}</div>
  <div class="sdetail">{card.get('detail', '')}</div>
</div>""",
        unsafe_allow_html=True,
    )


def mini_chart(history, height=110):
    """信号迷你趋势图（plotly 极简风），history 为含 date/v 列的 DataFrame"""
    import plotly.graph_objects as go
    fig = go.Figure(go.Scatter(
        x=history["date"], y=history["v"], mode="lines",
        line=dict(color="#1B365D", width=1.6),
        hovertemplate="%{x}: %{y:.2f}<extra></extra>",
    ))
    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=4, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig
