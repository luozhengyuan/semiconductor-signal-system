# -*- coding: utf-8 -*-
"""回测完整流程测试：评分 + 价格 + Backtrader"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sig import backtest, db

conn = db.get_conn()

print("=== 1. 构造评分序列 ===")
scores = backtest.build_daily_scores(conn)
print(f"评分: {scores.index[0].date()} ~ {scores.index[-1].date()}（{len(scores)} 天）")

print("\n=== 2. 抓取个股日线 ===")
prices = backtest.build_price_data(conn)
print(f"获取 {len(prices)} 只股票")
for code, df in prices.items():
    print(f"  {code}: {df.index[0].date()} ~ {df.index[-1].date()}（{len(df)} 天）")

print("\n=== 3. 跑 Backtrader 回测 ===")
result = backtest.run_backtest(conn, score_series=scores, price_data=prices)

if "error" in result:
    print(f"❌ {result['error']}")
    conn.close()
    sys.exit(1)

print("\n=== 4. 回测指标 ===")
for k, v in result["metrics"].items():
    print(f"  {k}: {v}")

print(f"\n=== 5. 资金曲线点数: {result['n_data_points']} ===")
print(result["nav_df"].head())
print("...")
print(result["nav_df"].tail())

print(f"\n=== 6. 交易明细: {len(result['trades'])} 笔 ===")
for t in result["trades"][:5]:
    print(f"  {t}")

conn.close()
print("\n✅ 回测完整流程测试通过")
