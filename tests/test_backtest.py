# -*- coding: utf-8 -*-
"""回测模块单元测试：验证评分序列构造逻辑（不依赖网络）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sig import backtest, db

conn = db.get_conn()

print("=== 1. 五个信号各自的评分序列 ===")
th = db.thresholds(conn)
print(f"价格:    {len(backtest._price_score_series(conn))} 个评分点")
print(f"台股营收: {len(backtest._tw_revenue_score_series(conn, th))} 个评分点")
print(f"盈利预测: {len(backtest._profit_score_series(conn))} 个评分点")
print(f"拥挤度:  {len(backtest._crowding_score_series(conn, th))} 个评分点")
print(f"热搜:    {len(backtest._heat_score_series(conn, th))} 个评分点")

print("\n=== 2. 合成每日综合评分 ===")
scores = backtest.build_daily_scores(conn)
print(f"评分序列: {scores.index[0].date()} ~ {scores.index[-1].date()}")
print(f"总天数: {len(scores)}")
print(f"评分分布:")
print(f"  🟢 > 0: {(scores > 0).sum()} 天")
print(f"  🟡 = 0: {(scores == 0).sum()} 天")
print(f"  🔴 < 0: {(scores < 0).sum()} 天")
print(f"\n前 5 个评分:")
print(scores.head())
print(f"\n后 5 个评分:")
print(scores.tail())

print("\n=== 3. 评分序列统计 ===")
print(f"均值: {scores.mean():.3f}")
print(f"标准差: {scores.std():.3f}")
print(f"最大: {scores.max()} (满仓信号)")
print(f"最小: {scores.min()} (清仓信号)")

conn.close()
print("\n✅ 评分序列构造测试通过")
