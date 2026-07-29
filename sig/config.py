# -*- coding: utf-8 -*-
"""半导体信号系统 · 配置"""
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "signals.db"

# 市场需求分析系统的数据库（仅用于 hot_snap 历史的一次性迁移，日常采集不依赖它）
MRS_DB_PATH = Path(r"D:/python projects/市场需求分析系统/data/mrs.db")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

MAX_RETRY = 3
RETRY_BACKOFF = 2.0
REQUEST_INTERVAL = 1.0

# A股存储板块（拥挤度/盈利预测用）
STOCK_POOL = {
    "603986": "兆易创新",
    "301308": "江波龙",
    "688525": "佰维存储",
    "001309": "德明利",
    "300475": "香农芯创",
    "000021": "深科技",
}

# 台股存储/半导体观察标的（TWSE 开放数据）
TW_WATCH = {
    "2408": "南亞科",
    "2344": "華邦電",
    "2337": "旺宏",
}
TW_REFERENCE = {"2330": "台積電"}  # 参考指标，不计入存储均值

# 热搜热度关键词（在 mrs.db hotlist_snap.term 中做包含匹配）
HEAT_KEYWORDS = ["存储芯片", "内存", "HBM", "DDR", "NAND", "闪存"]

# 默认打分阈值（可在"信号详情"页调整，存 settings 表）
DEFAULT_THRESHOLDS = {
    "tw_yoy_green": 20.0,     # 月营收同比 >20% 🟢，0~20% 🟡，<0% 🔴
    "crowding_red": 2.0,      # 拥挤度量比 >2 🔴，1~2 🟡，<1 🟢
    "heat_pct_red": 90.0,     # 热搜热度60日分位 >90% 🔴，>50% 🟡，其他 🟢
    "heat_pct_yellow": 50.0,
}

# CFM 价格页（DRAM 现货周价，实测 2026-07 可用，需直连）
CFM_DDR_URL = "https://www.chinaflashmarket.com/price/ddr"
# CFM 产品详情页（参数：产品id；"最近半年"标签页为公开数据上限，一年需登录会员）
CFM_EWS_URL = "https://www.chinaflashmarket.com/price/ews/{}/2"
# TWSE 上市公司月营收开放数据（实测 2026-07 可用，只给当月快照）
TWSE_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
# 公开资讯观测站（MOPS）上市公司每月营收历史页面，参数：民国年、月（实测 2026-07 可用）
MOPS_REVENUE_URL = "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_{}_{}_0.html"
