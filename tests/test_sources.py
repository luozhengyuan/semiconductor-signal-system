# -*- coding: utf-8 -*-
"""五个数据源的真实抓取测试：逐源调用、打印样例、断言非空或明确降级原因"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sig import collectors, db  # noqa: E402


def main():
    conn = db.get_conn()
    passed, failed = [], []
    for source, name, fn in collectors.COLLECTORS:
        print(f"== {name} ({source}) ==")
        try:
            n = fn(conn)
            assert n > 0, "返回 0 行"
            print(f"  通过：{n} 行\n")
            passed.append(source)
        except Exception as e:  # noqa: BLE001
            print(f"  失败：{type(e).__name__}: {e}\n")
            failed.append((source, str(e)))

    # 样例抽查
    print("== 样例抽查 ==")
    for table, sql in [
        ("dram_price", "SELECT * FROM dram_price ORDER BY date DESC LIMIT 3"),
        ("tw_revenue", "SELECT * FROM tw_revenue ORDER BY month DESC LIMIT 3"),
        ("profit_forecast", "SELECT * FROM profit_forecast ORDER BY snap_date DESC LIMIT 3"),
        ("crowding", "SELECT * FROM crowding ORDER BY trade_date DESC LIMIT 3"),
        ("hot_heat", "SELECT * FROM hot_heat ORDER BY snap_date DESC LIMIT 3"),
    ]:
        rows = conn.execute(sql).fetchall()
        print(f"{table}: {[dict(r) for r in rows]}")

    print(f"\n[结论] {len(passed)} 源通过, {len(failed)} 源失败: {[f[0] for f in failed]}")
    return not failed


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
