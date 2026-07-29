# -*- coding: utf-8 -*-
"""临时探测脚本：实测五个数据源的可用性与返回字段。"""
import sys, json, sqlite3, traceback
import requests

OUT = []


def rec(name, fn):
    try:
        r = fn()
        OUT.append(f"===== {name}: OK =====\n{r}\n")
    except Exception as e:
        OUT.append(f"===== {name}: FAIL =====\n{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}\n")


def get(url, **kw):
    s = requests.Session()
    try:
        r = s.get(url, timeout=20, **kw)
        r.raise_for_status()
        return r
    except Exception:
        s2 = requests.Session()
        s2.trust_env = False
        r = s2.get(url, timeout=20, **kw)
        r.raise_for_status()
        return r


# 1. TrendForce 中文站公开新闻
def t_trendforce():
    texts = []
    for url in ["https://www.trendforce.cn/presscenter/news", "https://www.trendforce.cn/"]:
        try:
            r = get(url, headers={"User-Agent": "Mozilla/5.0"})
            texts.append(f"{url} -> {r.status_code}, len={len(r.text)}, enc={r.encoding}")
            texts.append(r.text[:800])
        except Exception as e:
            texts.append(f"{url} -> FAIL {e}")
    return "\n".join(texts)


# 1b. CFM 中国闪存市场
def t_cfm():
    texts = []
    for url in ["https://www.chinaflashmarket.com/", "https://www.chinaflashmarket.com/price"]:
        try:
            r = get(url, headers={"User-Agent": "Mozilla/5.0"})
            texts.append(f"{url} -> {r.status_code}, len={len(r.text)}")
            texts.append(r.text[:800])
        except Exception as e:
            texts.append(f"{url} -> FAIL {e}")
    return "\n".join(texts)


# 2. TWSE 月营收
def t_twse():
    r = get("https://openapi.twse.com.tw/v1/opendata/t187ap05_L")
    data = r.json()
    keys = list(data[0].keys())
    targets = ["南亞科", "華邦電", "旺宏", "台積電"]
    hits = [d for d in data if d.get("公司名稱", "") in targets]
    return f"rows={len(data)} keys={keys}\n" + json.dumps(hits, ensure_ascii=False, indent=1)


# 3. 同花顺盈利预测
def t_ths():
    import akshare as ak
    df = ak.stock_profit_forecast_ths(symbol="603986", indicator="预测年报净利润")
    return f"cols={list(df.columns)}\n{df.head().to_string()}"


# 4. 新浪日线
def t_sina():
    import akshare as ak
    df = ak.stock_zh_a_daily(symbol="sh603986", adjust="")
    return f"cols={list(df.columns)} rows={len(df)}\n{df.tail(3).to_string()}"


# 5. mrs.db 热搜
def t_mrs():
    db = "D:/python projects/市场需求分析系统/data/mrs.db"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    info = f"tables={tables}\n"
    if "hotlist_snap" in tables:
        cols = [r[1] for r in cur.execute("PRAGMA table_info(hotlist_snap)")]
        n = cur.execute("SELECT COUNT(*) FROM hotlist_snap").fetchone()[0]
        info += f"cols={cols} rows={n}\n"
        for row in cur.execute("SELECT * FROM hotlist_snap ORDER BY rowid DESC LIMIT 3"):
            info += str(row)[:300] + "\n"
    conn.close()
    return info


rec("trendforce", t_trendforce)
rec("cfm", t_cfm)
rec("twse", t_twse)
rec("ths_forecast", t_ths)
rec("sina_daily", t_sina)
rec("mrs_db", t_mrs)

with open("D:/python projects/半导体信号系统/tests/probe_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
