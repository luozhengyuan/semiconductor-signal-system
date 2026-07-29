# -*- coding: utf-8 -*-
"""深挖价格源：TrendForce 新闻列表/正文 + CFM 报价页结构。"""
import re, json, requests

OUT = []


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

# --- TrendForce 新闻列表 ---
r = get("https://www.trendforce.cn/presscenter/news", headers=H)
html = r.text
# 找出所有新闻链接与标题
links = re.findall(r'href="(/presscenter/news/[^"]+)"[^>]*>([^<]{6,120})<', html)
OUT.append(f"--- trendforce list links: {len(links)} ---")
for u, t in links[:40]:
    OUT.append(f"{u} | {t.strip()}")
# 关键词过滤
kw = re.compile(r"DRAM|NAND|内存|存储|闪存|价格|涨|跌|合约价|现货")
hits = [(u, t.strip()) for u, t in links if kw.search(t)]
OUT.append(f"--- keyword hits: {len(hits)} ---")
for u, t in hits[:20]:
    OUT.append(f"{u} | {t}")

# 找一篇相关文章正文
art = None
for u, t in hits:
    if re.search(r"DRAM|NAND|内存|存储|闪存", t) and re.search(r"价格|涨|跌|价", t):
        art = (u, t)
        break
if art:
    url = "https://www.trendforce.cn" + art[0] if art[0].startswith("/") else art[0]
    r2 = get(url, headers=H)
    body = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", r2.text)
    text = re.sub(r"<[^>]+>", "\n", body)
    text = re.sub(r"\n{2,}", "\n", text)
    OUT.append(f"--- article {art[1]} ({url}) len={len(r2.text)} ---")
    OUT.append(text[:3000])
else:
    OUT.append("--- no price article found on list page ---")

# --- CFM 报价页 ---
r3 = get("https://www.chinaflashmarket.com/price", headers=H)
h3 = r3.text
OUT.append(f"--- cfm price page len={len(h3)} ---")
# 找内嵌 JSON / 数据接口
for m in re.findall(r"(?:url|api|href|src)\s*[:=]\s*[\"']([^\"']*(?:price|quot|api)[^\"']*)[\"']", h3)[:30]:
    OUT.append(f"api-ish: {m}")
# 找表格片段
tbl = re.findall(r"<table[\s\S]*?</table>", h3)
OUT.append(f"tables: {len(tbl)}")
if tbl:
    t0 = re.sub(r"<[^>]+>", "|", tbl[0])
    OUT.append(re.sub(r"\|{2,}", "|", t0)[:2000])
# 价格相关文本片段
nums = re.findall(r"(DDR\d?[^<]{0,60}|NAND[^<]{0,60}|[0-9]+\.[0-9]{2,3}\s*(?:\$|美元))", h3)
OUT.append(f"price-ish fragments: {len(nums)}")
for n in nums[:30]:
    OUT.append(n.strip())

with open("D:/python projects/半导体信号系统/tests/probe_price.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
