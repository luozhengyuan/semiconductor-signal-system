# -*- coding: utf-8 -*-
"""
命令行采集入口（独立于 Streamlit，可本地手动跑 / GitHub Actions 自动跑）。

用法：
    python scripts/collect.py             # 跑全部 5 个采集器
    python scripts/collect.py --only dram_price,hot_heat   # 只跑指定源
    python scripts/collect.py --backfill tw_revenue        # 顺带回填历史
    python scripts/collect.py --json        # 输出 JSON 摘要（CI 用）

退出码：
    0  全部成功
    1  有失败源（但已写 fetch_log，可重试）
    2  参数错误或环境异常

设计原则：
- 单文件可独立运行，不依赖 streamlit
- 与 app/pages/1_数据更新.py 走相同的 collectors.run_all 路径，结果一致
- 失败不抛异常，写日志后用退出码标记，便于 CI 判定
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

# 让脚本无论从哪里调用都能找到 sig 包
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sig import collectors, db  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="半导体信号系统 · 命令行采集器")
    p.add_argument("--only", type=str, default="",
                   help="只跑指定源（逗号分隔），如 dram_price,hot_heat。默认全部")
    p.add_argument("--backfill", type=str, default="",
                   choices=["", "tw_revenue", "dram_price"],
                   help="顺带回填历史：tw_revenue 近 12 月 / dram_price 近半年")
    p.add_argument("--json", action="store_true",
                   help="输出 JSON 摘要（CI 友好，最后打印一行 JSON）")
    p.add_argument("--db", type=str, default="",
                   help="覆盖默认数据库路径（默认 data/signals.db）")
    return p.parse_args()


def run_subset(conn, sources):
    """跑指定子集采集器，复用 collectors.run_all 的容错逻辑"""
    results = {}
    for source, name, fn in collectors.COLLECTORS:
        if source not in sources:
            continue
        try:
            ret = fn(conn)
            n, warn = ret if isinstance(ret, tuple) else (ret, "")
            status = "warn" if warn else "ok"
            db.log_fetch(conn, source, status, n, warn)
            results[source] = {"status": status, "n": n, "msg": warn}
            print(f"  ✅ {name}: +{n} 行" + (f"（⚠️ {warn}）" if warn else ""))
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            db.log_fetch(conn, source, "fail", 0, msg)
            results[source] = {"status": "fail", "n": 0, "msg": msg}
            print(f"  ❌ {name}: {msg}")
    return results


def main():
    args = parse_args()
    ts_start = dt.datetime.now()
    print(f"\n=== 半导体信号系统 · 采集开始 {ts_start:%Y-%m-%d %H:%M:%S} ===")

    conn = db.get_conn(args.db or None)

    # 1. 主采集
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        valid = {k for k, _, _ in collectors.COLLECTORS}
        unknown = wanted - valid
        if unknown:
            print(f"❌ 未知数据源: {unknown}，可选: {valid}")
            conn.close()
            sys.exit(2)
        results = run_subset(conn, wanted)
    else:
        print("  跑全部 5 个采集器…")
        raw = collectors.run_all(conn)
        results = {k: {"status": s, "n": n, "msg": m} for k, (s, n, m) in raw.items()}
        for source, name, _ in collectors.COLLECTORS:
            r = results[source]
            tag = "✅" if r["status"] == "ok" else "❌"
            extra = f"+{r['n']} 行" if r["status"] == "ok" else r["msg"]
            print(f"  {tag} {name}: {extra}")

    # 2. 可选回填
    backfill_note = ""
    if args.backfill == "tw_revenue":
        print("\n  回填台系营收历史（近 12 个月）…")
        try:
            n = collectors.fetch_tw_revenue_history(conn, months=12)
            db.log_fetch(conn, "tw_revenue", "ok", n, "MOPS 历史回填（近12个月）")
            backfill_note = f"tw_revenue backfill +{n} rows"
            print(f"  ✅ 回填 {n} 行")
        except Exception as e:  # noqa: BLE001
            backfill_note = f"tw_revenue backfill FAIL: {e}"
            print(f"  ❌ 回填失败: {e}")
    elif args.backfill == "dram_price":
        print("\n  回填存储现货价历史（近半年）…")
        try:
            n = collectors.fetch_dram_price_history(conn)
            db.log_fetch(conn, "dram_price", "ok", n, "CFM 详情页历史回填（近半年）")
            backfill_note = f"dram_price backfill +{n} rows"
            print(f"  ✅ 回填 {n} 行")
        except Exception as e:  # noqa: BLE001
            backfill_note = f"dram_price backfill FAIL: {e}"
            print(f"  ❌ 回填失败: {e}")

    # 3. 数据概览
    overview = db.data_overview(conn)
    conn.close()

    ts_end = dt.datetime.now()
    dur = (ts_end - ts_start).total_seconds()
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    total = len(results)
    print(f"\n=== 完成 {ts_end:%Y-%m-%d %H:%M:%S}（耗时 {dur:.0f}s，{ok}/{total} 成功）===")

    # 4. JSON 摘要（CI 用）
    if args.json:
        summary = {
            "ts": ts_end.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_sec": dur,
            "ok": ok,
            "total": total,
            "results": results,
            "backfill": backfill_note,
            "overview": [
                {"key": o["key"], "latest": o["latest"], "rows": o["rows"],
                 "fresh": o["fresh"], "age_days": o["age_days"]}
                for o in overview
            ],
        }
        print("\nJSON_SUMMARY:" + json.dumps(summary, ensure_ascii=False))

    # 退出码：全部成功 0，部分失败 1
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    main()
