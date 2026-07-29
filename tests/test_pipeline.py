# -*- coding: utf-8 -*-
"""端到端冒烟：采集（真实网络）→ 打分 → dashboard 数据就绪"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sig import collectors, db, scorecard  # noqa: E402


def main():
    conn = db.get_conn()
    print("== 1) 采集 ==")
    results = collectors.run_all(conn)
    for src, (status, n, msg) in results.items():
        print(f"  {src}: {status} {n} {msg[:60]}")

    print("== 2) 记分卡 ==")
    cards, comp = scorecard.build_scorecard(conn)
    assert len(cards) == 5
    for c in cards:
        assert c["light"] in ("🟢", "🟡", "🔴", "⚪")
        print(f"  {c['light']} {c['name']}: {c['value']}")
    print(f"  综合评分: {comp['score']:+d} | {comp['position']} | {comp['reference']}")
    assert -5 <= comp["score"] <= 5
    print("\n[结论] 端到端冒烟通过")


if __name__ == "__main__":
    main()
