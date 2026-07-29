# -*- coding: utf-8 -*-
"""深挖 CFM DDR/NAND 报价页的表格结构，确认解析方式。"""
import re, requests


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


H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
OUT = []

for page in ["nandflash", "ddr"]:
    r = get(f"https://www.chinaflashmarket.com/price/{page}", headers=H)
    h = r.text
    OUT.append(f"===== {page} len={len(h)} =====")
    # 提取 <tr> 行，清洗标签看单元格序列
    rows = re.findall(r"<tr[\s\S]*?</tr>", h)
    OUT.append(f"tr count: {len(rows)}")
    for row in rows[:12]:
        cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        cells = [c for c in cells if c]
        if cells:
            OUT.append(" | ".join(cells)[:200])
    # 日期信息：页面上有没有报价日期
    dates = re.findall(r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}", h)
    OUT.append(f"dates on page: {sorted(set(dates))[:10]}")

with open("D:/python projects/半导体信号系统/tests/probe_cfm.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
