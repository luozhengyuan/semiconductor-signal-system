# -*- coding: utf-8 -*-
"""数据更新：一键更新 + 五个数据源档案卡 + 抓取日志"""

import sys
from pathlib import Path

import datetime as dt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import data_status_panel, get_conn, inject_css  # noqa: E402
from sig import collectors, db  # noqa: E402
from sig.sources import SOURCES  # noqa: E402

st.set_page_config(page_title="数据更新", page_icon="🔄", layout="wide")
inject_css()
st.title("🔄 数据更新与数据源档案")
st.markdown(
    '<p class="knote">数据是这套系统的地基。建议频率：价格/拥挤度/热搜 <b>每周</b>，'
    '盈利预测 <b>每周</b>（积累修正轨迹），台股营收 <b>每月 10 日后</b>。同日重复抓取按主键覆盖，不会产生重复。<br>'
    '🔑 <b>日常只用「一键更新」</b>（抓最新一期）；下面两个「回填」是一次性补历史用的，'
    '各点过一次、历史入库后就不需要再点了。</p>',
    unsafe_allow_html=True,
)

conn = get_conn()

# ---- 数据库状态：先看这里，再决定要不要点更新 ----
data_status_panel(db.data_overview(conn), action_hint="，建议点下方「一键更新」")

if st.button("🚀 一键更新全部数据源", type="primary"):
    bar = st.progress(0.0)
    status = st.empty()

    def on_progress(done, total, message):
        bar.progress(done / max(total, 1))
        status.markdown(f"⏳ {message}")

    results = collectors.run_all(conn, progress_cb=on_progress)
    bar.progress(1.0)
    status.empty()
    ov = {o["key"]: o for o in db.data_overview(conn)}
    names = {k: n for k, n, _ in collectors.COLLECTORS}
    st.session_state["update_report"] = {
        "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": [
            {"数据源": names[src],
             "状态": "✅ 成功" if s == "ok" else "❌ 失败",
             "本次写入行数": n,
             "数据最新到": ov[src]["latest"] or "—",
             "说明": msg or "—"}
            for src, (s, n, msg) in results.items()
        ],
    }
    st.rerun()

# ---- 本次更新报告（存在 session_state，页面刷新不丢）----
rep = st.session_state.get("update_report")
if rep:
    ok = sum(1 for r in rep["rows"] if r["状态"].startswith("✅"))
    st.subheader(f"🧾 本次更新报告（{rep['ts']}，{ok}/{len(rep['rows'])} 个源成功）")
    st.dataframe(pd.DataFrame(rep["rows"]), use_container_width=True, hide_index=True)
    st.caption("数据已是最新时无需重复更新；失败源可稍后重试（按主键覆盖，不会产生重复）。")
note = st.session_state.get("backfill_note")
if note:
    st.info(note)

if st.button("📥 回填台系营收历史（近 12 个月）"):
    bar = st.progress(0.0)
    status = st.empty()

    def on_hist_progress(done, total, message):
        bar.progress(done / max(total, 1))
        status.markdown(f"⏳ {message}")

    try:
        n = collectors.fetch_tw_revenue_history(conn, months=12, progress_cb=on_hist_progress)
        db.log_fetch(conn, "tw_revenue", "ok", n, "MOPS 历史回填（近12个月）")
        st.session_state["backfill_note"] = (
            f"✅ 台系营收回填完成，共写入 {n} 行（近 12 个月 × 4 家），历史曲线已可用。"
            "库中已有 12 个月历史，无需重复回填。")
    except Exception as e:  # noqa: BLE001
        st.session_state["backfill_note"] = f"❌ 台系营收回填失败：{e}"
    bar.progress(1.0)
    status.empty()
    st.rerun()

if st.button("📥 回填存储现货价历史（近半年）"):
    bar = st.progress(0.0)
    status = st.empty()

    def on_dram_progress(done, total, message):
        bar.progress(done / max(total, 1))
        status.markdown(f"⏳ {message}")

    try:
        n = collectors.fetch_dram_price_history(conn, progress_cb=on_dram_progress)
        db.log_fetch(conn, "dram_price", "ok", n, "CFM 详情页历史回填（近半年）")
        st.session_state["backfill_note"] = (
            f"✅ 存储现货价回填完成，共写入 {n} 行（近半年 × 8 个产品），历史曲线已可用。"
            "库中已有近半年历史，无需重复回填。")
    except Exception as e:  # noqa: BLE001
        st.session_state["backfill_note"] = f"❌ 存储现货价回填失败：{e}"
    bar.progress(1.0)
    status.empty()
    st.rerun()

st.divider()

# ---- 数据源档案卡 ----
st.subheader("📇 数据源档案")
for key, src in SOURCES.items():
    last = db.last_fetch(conn, key)
    if last is None:
        status_html = '<span class="knote">尚未抓取</span>'
    elif last["status"] == "ok":
        status_html = f'<span class="ok">✅ 成功</span>（{last["ts"]}，{last["n_rows"]} 行）'
    else:
        status_html = f'<span class="fail">❌ 失败</span>（{last["ts"]}：{last["message"]}）'
    st.markdown(
        f"""<div class="ksrc">
  <div class="t">{src['name']}</div>
  <div class="row"><b>地址</b>：{src['url']}</div>
  <div class="row"><b>更新频率</b>：{src['freq']} ｜ <b>最近抓取</b>：{status_html}</div>
  <div class="row"><b>信号作用</b>：{src['signal']}</div>
  <div class="row"><b>为什么可信</b>：{src['principle']}</div>
  <div class="row"><b>局限性</b>：{src['limit']}</div>
</div>""",
        unsafe_allow_html=True,
    )

# ---- 抓取日志 ----
st.subheader("🧾 抓取日志（最近 30 条）")
logs = pd.read_sql_query(
    "SELECT ts AS 时间, source AS 数据源, status AS 状态, n_rows AS 行数, message AS 说明 "
    "FROM fetch_log ORDER BY id DESC LIMIT 30", conn)
if logs.empty:
    st.caption("暂无日志")
else:
    st.dataframe(logs, use_container_width=True, hide_index=True)

conn.close()
