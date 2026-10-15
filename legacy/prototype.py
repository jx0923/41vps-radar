#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LET Deals Radar — 最小可跑原型 (MVP)
=====================================
LowEndTalk "Offers" RSS  ->  结构化字段抽取  ->  JSON / Markdown 总览表

目的：验证「LET RSS -> 抽字段 -> 输出总览表」这条链路是否可行，
      并量化抽取准确率 —— 哪些字段能全自动，哪些必须人工兜底。

只依赖 Python 标准库，无第三方包。

用法:
    python prototype.py                            # 在线抓 LET Offers RSS
    python prototype.py --offline data/feed.xml     # 用本地缓存的 XML
    python prototype.py --limit 20                  # 只处理前 20 条
    python prototype.py --recent-days 60            # 只保留最近 60 天的帖子
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------

FEED_URL = "https://lowendtalk.com/categories/offers/feed.rss"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

# 状态阈值（天）
NEW_DAYS = 7
ACTIVE_DAYS = 30

# --------------------------------------------------------------------------
# 正则：配置
# --------------------------------------------------------------------------

RE_VCPU = re.compile(
    r"(\d+)\s*(?:x\s*)?(?:vCore|vCores|vCPU|vCPUs|vcore|vcpu)\b", re.I)
RE_CORE = re.compile(
    r"(\d+)\s*(?:x\s*)?(?:Cores?|Kerne|核心)\b", re.I)

RE_RAM = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(GB|MB|TB)\s*(?:of\s+)?(?:DDR[45]\s*)?(?:ECC\s*)?"
    r"(?:RAM|Memory|Arbeitsspeicher)\b", re.I)
RE_RAM_LABEL = re.compile(r"\bRAM\s*[:：]\s*(\d+(?:[.,]\d+)?)\s*(GB|MB|TB)", re.I)

RE_STORAGE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(GB|TB)\s*"
    r"(NVMe(?:\s*(?:Gen\s*\d|SSD))?|SSD|HDD|SATA|Storage)\b", re.I)

RE_BW = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(TB|GB)\s*(?:of\s*)?(?:Monthly\s*)?"
    r"(?:Traffic|Bandwidth|BW|transfer|outbound)\b", re.I)
RE_BW_AT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(TB|GB)\s*@", re.I)

# CPU 型号（保守：只认常见服务器 CPU 家族）
RE_CPU_MODEL = re.compile(
    r"\b("
    r"EPYC\s+[0-9]{3,4}[A-Za-z]{0,3}"
    r"|Ryzen\s+(?:9|7|5|3)\s+[0-9]{3,4}[A-Za-z0-9]{0,4}"
    r"|Threadripper\s+[0-9A-Za-z]{3,8}(?:\s+Pro)?"
    r"|Xeon\s+(?:Gold|Silver|Bronze|Platinum|E5-|E-)[0-9A-Za-z]{2,6}"
    r")\b", re.I)

# --------------------------------------------------------------------------
# 正则：价格
# --------------------------------------------------------------------------

CYCLE = r"(mo|mos|month|months|monthly|yr|yrs|year|years|yearly|annual|annually|quarter|quarterly|qtr)"

# 前缀货币:  $2.49/month   €129/year
RE_PRICE_PRE = re.compile(
    r"([$€£])\s*(\d+(?:[.,]\d+)?)\s*(?:USD|EUR|GBP)?\s*(?:/|per\s+)\s*" + CYCLE, re.I)
# 后缀货币:  7.49€/quarterly   129 EUR/year
RE_PRICE_POST = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*([$€£]|USD|EUR|GBP)\s*(?:/|per\s+)\s*" + CYCLE, re.I)

CYCLE_NORM = {
    "mo": "month", "mos": "month", "month": "month", "months": "month",
    "monthly": "month",
    "yr": "year", "yrs": "year", "year": "year", "years": "year",
    "yearly": "year", "annual": "year", "annually": "year",
    "quarter": "quarter", "quarterly": "quarter", "qtr": "quarter",
}

# --------------------------------------------------------------------------
# 正则：折扣 / 优惠码 / 库存
# --------------------------------------------------------------------------

RE_PCT = re.compile(
    r"(\d{1,3})\s*%\s*(?:off|discount|rabatt|reduction|savings?)\b"
    r"|\b(?:off|discount|save|savings?\s+of)\s+(\d{1,3})\s*%", re.I)
RE_RECURRING = re.compile(
    r"\brecurring\b|\blifetime\b|\bfor\s+life\b|\bpermanent(?:ly)?\b|"
    r"\bprice\s+locked\b|\b循环\b|\b永久\b|\b续费同价\b", re.I)
RE_CODE = re.compile(
    r"(?:coupon|promo(?:tion)?\s*code|code|gutschein)\b[^A-Za-z0-9]{0,25}"
    r"([A-Z][A-Z0-9]{2,25})", re.I)
RE_CODE_BARE = re.compile(r"\b(LET[A-Z0-9]{2,20}|BF[A-Z0-9]{2,20}|LEB[A-Z0-9]{2,20})\b")

# 误报黑名单：这些"大写词"不是优惠码
CODE_STOP = {
    "CODE", "CODES", "DISCOUNT", "REQUIRED", "NEEDED", "APPLICABLE",
    "AVAILABLE", "EXPIRES", "PROMO", "COUPON", "GUTSCHEIN", "FREE",
    "PLAN", "PLANS", "VPS", "SSD", "NVME", "HDD", "RAM", "CPU", "USD",
    "EUR", "GBP", "IPV4", "IPV6", "DDR4", "DDR5", "AMD", "INTEL", "XEON",
    "EPYC", "RYZEN", "WIN10", "WIN11", "WIN2019", "WIN2022", "LET", "GET",
    "USE", "THE", "AND", "FOR", "ALL", "NEW", "OFF", "ONE", "TWO", "ADD",
    "MONTH", "YEAR", "SAVE", "EXTRA", "BONUS", "DEAL", "SALE", "ORDER",
}

RE_STOCK = re.compile(
    r"\b(out\s+of\s+stock|sold\s*out|restock(?:ed|ing)?|back\s+in\s+stock|"
    r"in\s+stock|no\s+further\s+restocks|limited\s+stock|while\s+stock\s+lasts|"
    r"售罄|缺货|补货|有货)\b", re.I)

RE_EXTRAS = re.compile(
    r"(double\s+(?:ram|bandwidth|storage|traffic|ssd|nvme|cores?|vcpu)|"
    r"triple\s+\w+|free\s+(?:permanent\s+)?upgrade|"
    r"\d+\s+months?\s+free|"
    r"12\s+months?\s+for\s+the\s+price\s+of\s+10|"
    r"免费(?:升级|加倍))", re.I)

# --------------------------------------------------------------------------
# 活动性质
# --------------------------------------------------------------------------

EVENT_RULES = [
    ("anniversary", re.compile(
        r"anniversary|birthday|\b\d+\s*(?:th|st|nd|rd)\s+(?:years?|birthday)|"
        r"years?\s+in\s+business|周年|庆典|jubil", re.I)),
    ("black_friday", re.compile(
        r"black\s*friday|\bBF20\d\d\b|cyber\s*monday|黑五", re.I)),
    ("holiday", re.compile(
        r"christmas|halloween|easter|national\s*day|mid-?autumn|new\s*year|"
        r"advent|summer\s*sale|end\s*of\s*summer|freedom\s*sale|festival|"
        r"中秋|国庆|圣诞|春节", re.I)),
    ("launch", re.compile(
        r"\blaunch|is\s+back|returns?\b|new\s+location|first\s+(?:deal|vps)|"
        r"now\s+live|debut|上新|开业", re.I)),
    ("restock", re.compile(r"restock|back\s+in\s+stock|补货", re.I)),
    ("sale", re.compile(
        r"\bsale\b|\bdeal\b|\bpromo|\bdiscount|flash\s*sale|clearance|budget|"
        r"special\s+offer|特价|促销|优惠", re.I)),
]

# --------------------------------------------------------------------------
# 地点
# --------------------------------------------------------------------------

LOCATIONS = [
    "Frankfurt", "Amsterdam", "Netherlands", "Germany", "Deutschland",
    "London", "Paris", "France", "Singapore", "Tokyo", "Japan",
    "Hong Kong", "Los Angeles", "New York", "Miami", "Dallas", "Chicago",
    "Seattle", "Montreal", "Canada", "Poland", "Warsaw", "Wrocław",
    "Zurich", "Switzerland", "Velbert", "Eygelshoven", "Roubaix",
    "Salt Lake City", "Buffalo", "Ashburn", "Atlanta", "Phoenix",
    "Arizona", "Ohio", "Texas", "Utah", "Milan", "Italy", "Spain",
    "Sweden", "Norway", "Finland", "Denmark", "Austria", "Vienna",
    "Prague", "Czechia", "Estonia", "Latvia", "Lithuania", "Romania",
    "Bulgaria", "India", "Australia", "Sydney", "Brazil", "Sao Paulo",
    "Kansas", "Denver", "Detroit", "Silicon Valley", "Santa Clara",
]
RE_LOC = re.compile(
    r"\b(" + "|".join(re.escape(x) for x in LOCATIONS) + r")\b", re.I)


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def strip_html(s: str) -> str:
    """去 HTML 标签、解码实体、压缩空白。"""
    if not s:
        return ""
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|li|tr|h[1-6]|td|th)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def to_float(s: str) -> float:
    return float(s.replace(",", "."))


def to_gb(amount: float, unit: str) -> float:
    u = unit.upper()
    if u == "TB":
        return amount * 1024.0
    if u == "MB":
        return amount / 1024.0
    return amount


def to_tb(amount: float, unit: str) -> float:
    u = unit.upper()
    if u == "GB":
        return round(amount / 1024.0, 2)
    return round(amount, 2)


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# RSS 解析
# --------------------------------------------------------------------------

DC_CREATOR = "{http://purl.org/dc/elements/1.1/}creator"


def parse_rss(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for it in root.iter("item"):
        def g(tag: str) -> str:
            el = it.find(tag)
            return (el.text or "") if el is not None else ""

        guid_el = it.find("guid")
        guid = (guid_el.text or "") if guid_el is not None else ""
        thread_id = guid.split("@")[0].strip() if guid else ""

        out.append({
            "thread_id": thread_id,
            "title": g("title").strip(),
            "link": g("link").strip(),
            "pubDate": g("pubDate").strip(),
            "author": g(DC_CREATOR).strip(),
            "description": g("description"),
        })
    return out


# --------------------------------------------------------------------------
# 字段抽取
# --------------------------------------------------------------------------

def extract_provider(title: str, author: str, body: str) -> str:
    """从标题取商家名。

    优先用分隔符切出的首段；但很多帖子标题是描述性句子
    （如 "Free Ryzen 5900XT Server | From $99/mo"），首段不是商家名。
    此时回退到正文里出现的域名 / 明确的品牌名，最后才用作者名。
    """
    head = re.split(r"\s*[|│｜–—]\s*|\s+-\s+", title, maxsplit=1)[0].strip()
    head = re.sub(r"^[\[\【(（][^\])）]{0,30}[\])）]\s*", "", head).strip()
    head = re.sub(r"\s*[:\-]\s*$", "", head)

    # 判定首段是否像"商家名"而非描述句：
    #   像描述句的特征 -> 含价格/规格/过多普通单词
    looks_descriptive = bool(
        re.search(r"[$€£]\s*\d", head)
        or re.search(r"\b(from|starting|for only|deals?|sale|off|free)\b", head, re.I)
        or len(head.split()) > 6
        or re.search(r"\d+\s*(?:GB|TB|Cores?|vCPU|RAM)", head, re.I)
    )
    if 2 <= len(head) <= 60 and not looks_descriptive:
        return head

    # 回退 1：正文中的厂商域名（排除论坛/通用/第三方平台域名）
    SKIP = {
        "lowendtalk.com", "lowendbox.com", "github.com", "youtube.com",
        "discord.gg", "discord.com", "twitter.com", "x.com", "twitch.tv",
        "google.com", "t.me", "telegram.org", "cloudflare.com", "imgur.com",
        "i.imgur.com", "pastebin.com", "instatus.com", "trustpilot.com",
        "statuspage.io", "facebook.com", "instagram.com", "reddit.com",
    }
    for m in re.finditer(r"https?://(?:www\.)?([a-z0-9][a-z0-9\-]*\.[a-z.]{2,10})",
                         body, re.I):
        dom = m.group(1).lower().rstrip(".")
        if dom in SKIP or dom.endswith((".lowendtalk.com", ".lowendbox.com")):
            continue
        # 排除子域名式误抓（如 status.limitlessh / lg-nl.nolimitclo）
        # 只在"顶级域看起来完整"时采用
        if re.fullmatch(r"[a-z0-9\-]+\.[a-z]{2,6}", dom):
            return dom
    # 回退 1b：允许带子域，但裁掉常见前缀
    for m in re.finditer(r"https?://(?:www\.)?([a-z0-9][a-z0-9\-\.]*\.[a-z]{2,6})",
                         body, re.I):
        dom = m.group(1).lower().rstrip(".")
        if dom in SKIP or dom.endswith((".lowendtalk.com", ".lowendbox.com")):
            continue
        parts = dom.split(".")
        if len(parts) > 2:
            dom = ".".join(parts[-2:])
        return dom

    # 回退 2：作者名
    return author or "UNKNOWN"


def extract_specs(text: str) -> dict:
    vcpu = [int(m) for m in RE_VCPU.findall(text)]
    if not vcpu:
        vcpu = [int(m) for m in RE_CORE.findall(text)]

    ram = [to_gb(to_float(a), u) for a, u in RE_RAM.findall(text)]
    ram += [to_gb(to_float(a), u) for a, u in RE_RAM_LABEL.findall(text)]

    storage = []
    for a, u, kind in RE_STORAGE.findall(text):
        kind_n = re.sub(r"\s+", " ", kind).strip()
        if kind_n.lower() == "storage":
            kind_n = "unspecified"
        storage.append({"gb": to_gb(to_float(a), u), "type": kind_n})

    bw = [to_tb(to_float(a), u) for a, u in RE_BW.findall(text)]
    bw += [to_tb(to_float(a), u) for a, u in RE_BW_AT.findall(text)]

    def top(vals):
        return max(vals) if vals else None

    storage_sorted = sorted(storage, key=lambda x: x["gb"], reverse=True)
    flagship_storage = storage_sorted[0] if storage_sorted else None

    return {
        "vcpu": top(vcpu),
        "ram_gb": top(ram),
        "storage_gb": flagship_storage["gb"] if flagship_storage else None,
        "storage_type": flagship_storage["type"] if flagship_storage else None,
        "bandwidth_tb": top(bw),
        "_all": {
            "vcpu": sorted(set(vcpu), reverse=True)[:8],
            "ram_gb": sorted(set(ram), reverse=True)[:8],
            "storage_gb": [s["gb"] for s in storage_sorted][:8],
        },
    }


def extract_prices(text: str) -> list[dict]:
    found = []
    for cur, amt, cyc in RE_PRICE_PRE.findall(text):
        found.append({"amount": to_float(amt), "currency": cur,
                      "cycle": CYCLE_NORM.get(cyc.lower(), cyc.lower())})
    for amt, cur, cyc in RE_PRICE_POST.findall(text):
        c = cur if cur in "$€£" else {"USD": "$", "EUR": "€", "GBP": "£"}.get(cur.upper(), cur)
        found.append({"amount": to_float(amt), "currency": c,
                      "cycle": CYCLE_NORM.get(cyc.lower(), cyc.lower())})

    # 去重 + 排序（按年化价格）
    mult = {"month": 12, "quarter": 4, "year": 1}
    seen, uniq = set(), []
    for p in found:
        key = (p["amount"], p["currency"], p["cycle"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    uniq.sort(key=lambda p: p["amount"] * mult.get(p["cycle"], 12))
    return uniq


def extract_discount(text: str) -> dict:
    pcts = []
    for a, b in RE_PCT.findall(text):
        v = a or b
        if v and 0 < int(v) <= 95:
            pcts.append(int(v))
    recurring = bool(RE_RECURRING.search(text))

    codes = set()
    for m in RE_CODE.findall(text):
        u = m.upper()
        if u not in CODE_STOP and not u.isdigit():
            codes.add(u)
    for m in RE_CODE_BARE.findall(text):
        u = m.upper()
        if u not in CODE_STOP:
            codes.add(u)

    extras = sorted({m.group(0).strip().lower() for m in RE_EXTRAS.finditer(text)})

    parts = []
    if recurring:
        parts.append("循环/永久")
    if pcts:
        parts.append(f"最高 {max(pcts)}% off")
    if extras:
        parts.append("+".join(extras[:2]))
    if codes:
        parts.append("码 " + "/".join(sorted(codes)[:3]))

    return {
        "strength": " · ".join(parts) if parts else "",
        "percent_max": max(pcts) if pcts else None,
        "recurring": recurring,
        "codes": sorted(codes)[:6],
        "extras": extras[:5],
    }


def extract_event(title: str, body: str) -> str:
    hay = title + "\n" + body[:1500]
    for name, rx in EVENT_RULES:
        if rx.search(hay):
            return name
    return "regular"


def extract_locations(text: str) -> list[str]:
    seen, out = set(), []
    for m in RE_LOC.finditer(text):
        v = m.group(1)
        k = v.lower()
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out[:5]


def age_days(pub: str) -> int | None:
    try:
        dt = parsedate_to_datetime(pub)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return None


def availability(stock_hints: list[str], days: int | None,
                 reply_status: str | None = None,
                 reply_source: str | None = None) -> str:
    """可用性判定。

    优先级：**商家回帖表态 > 帖文关键词 > 用户回帖(弱证据) > 帖子年龄**。
    回帖是库存的权威来源 —— 商家只在回帖里说「售罄 / 补货」。
    """
    # 1) 商家回帖表态（最高优先级）
    if reply_source == "vendor" and reply_status:
        return {
            "SOLD_OUT": "SOLD_OUT",
            "RESTOCKING": "RESTOCKING",
            "ENDED": "ENDED",
            "ON_SALE": "ON_SALE",
        }.get(reply_status, "UNVERIFIED")

    # 2) 帖文正文关键词
    blob = " ".join(stock_hints).lower()
    if re.search(r"sold\s*out|out\s+of\s+stock|售罄|缺货", blob):
        return "SOLD_OUT"
    if re.search(r"no\s+further\s+restocks", blob):
        return "ENDED"
    if re.search(r"restock|back\s+in\s+stock|in\s+stock|补货|有货", blob):
        return "ON_SALE"

    # 3) 用户回帖（弱证据，仅作提示，不能当作结论）
    if reply_source == "user" and reply_status == "SOLD_OUT":
        return "LIKELY_SOLD_OUT"

    # 4) 兜底
    if days is not None and days > ACTIVE_DAYS:
        return "UNVERIFIED_STALE"
    return "UNVERIFIED"


# --------------------------------------------------------------------------
# 表格重建：HTML 表格被拍平成逐行文本后，字段名与值会分离
# --------------------------------------------------------------------------

# 表格行里常见的"值"形态
CELL_VCPU = re.compile(r"^(\d{1,3})\s*(?:x\s*)?(?:Cores?|vCores?|vCPUs?|Kerne)$", re.I)
CELL_RAM = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(GB|MB|TB)(?:\s*DDR[45])?(?:\s*ECC)?$", re.I)
# 存储：带明确介质关键词，或裸容量（由出现顺序决定是 RAM 还是存储）
CELL_STORAGE_TYPED = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*(GB|TB)\s*(NVMe(?:\s*(?:Gen\s*\d|SSD))?|SSD|HDD|SATA)$", re.I)
CELL_SIZE_BARE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(GB|MB|TB)$", re.I)
CELL_BW = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(TB|GB)$", re.I)
CELL_PRICE = re.compile(r"^([$€£])\s*(\d+(?:[.,]\d+)?)$|^(\d+(?:[.,]\d+)?)\s*([$€£])$")
CELL_IPV4 = re.compile(r"^\d+\s*IPv4$|^IPv4$", re.I)
CELL_IPV6 = re.compile(r"^/?64\s*IPv6$|^IPv6$", re.I)
CELL_PLAN = re.compile(r"^[A-Za-z][\w\s\-\.\+]{1,40}$")

# 所有"值型单元格"，用于判断套餐块边界
VALUE_CELLS = (CELL_VCPU, CELL_RAM, CELL_STORAGE_TYPED, CELL_SIZE_BARE,
               CELL_BW, CELL_PRICE, CELL_IPV4, CELL_IPV6)


def _is_value_cell(s: str) -> bool:
    return any(rx.match(s) for rx in VALUE_CELLS)


def parse_flat_tables(body: str) -> list[dict]:
    """从拍平的文本里恢复出"套餐行"。

    LET 帖子的套餐表被 strip_html 拍平后，每行一个单元格。例如 BERO 的帖子:

        Anniversary XXL / 8 Cores / 32 GB / 300 GB / 1 IPv4 / /64 IPv6 / 25 TB / €129

    列顺序高度一致: 套餐名 | CPU | RAM | 存储 | IPv4 | IPv6 | 流量 | 价格

    关键点：裸容量单元格（"32 GB" / "300 GB" / "25 TB"）本身不带语义，
    必须**按出现顺序**推断 —— 第 1 个 GB 是 RAM，第 2 个是存储，TB 是流量。
    """
    lines = [l.strip() for l in body.split("\n")]
    plans: list[dict] = []
    i, n = 0, len(lines)

    while i < n:
        name = lines[i]
        if (not name or not CELL_PLAN.match(name) or _is_value_cell(name)
                or len(name.split()) > 5):
            i += 1
            continue

        # 收集本块内的有序单元格
        seq: list[tuple[str, object]] = []
        last = i
        for j in range(i + 1, min(i + 16, n)):
            cell = lines[j]
            if not cell:
                continue
            # 撞到下一个套餐名 -> 结束本块
            if CELL_PLAN.match(cell) and not _is_value_cell(cell):
                break

            if CELL_VCPU.match(cell):
                seq.append(("vcpu", int(CELL_VCPU.match(cell).group(1))))
            elif CELL_STORAGE_TYPED.match(cell):
                mm = CELL_STORAGE_TYPED.match(cell)
                seq.append(("storage", (to_gb(to_float(mm.group(1)), mm.group(2)),
                                        mm.group(3).strip())))
            elif CELL_IPV4.match(cell) or CELL_IPV6.match(cell):
                seq.append(("ip", cell))
            elif CELL_PRICE.match(cell):
                mm = CELL_PRICE.match(cell)
                if mm.group(1):
                    seq.append(("price", (to_float(mm.group(2)), mm.group(1))))
                else:
                    seq.append(("price", (to_float(mm.group(3)), mm.group(4))))
            elif CELL_RAM.match(cell):
                mm = CELL_RAM.match(cell)
                seq.append(("size", (to_float(mm.group(1)), mm.group(2).upper())))
            else:
                break
            last = j

        if not seq:
            i += 1
            continue

        vcpu = next((v for k, v in seq if k == "vcpu"), None)
        price = next((v for k, v in seq if k == "price"), None)
        typed_storage = next((v for k, v in seq if k == "storage"), None)

        sizes = [v for k, v in seq if k == "size"]
        ram = None
        storage = None
        bw = None

        if typed_storage:
            storage = {"gb": typed_storage[0], "type": typed_storage[1]}
            # typed storage 占了存储位；剩下的按序推断 RAM / 流量
            for amt, unit in sizes:
                if unit in ("GB", "MB") and ram is None:
                    ram = to_gb(amt, unit)
                elif unit == "TB" and bw is None:
                    bw = to_tb(amt, unit)
        else:
            # 裸容量：按顺序 第1个=RAM, 第2个=存储, TB=流量
            for amt, unit in sizes:
                if unit in ("GB", "MB"):
                    if ram is None:
                        ram = to_gb(amt, unit)
                    elif storage is None:
                        storage = {"gb": to_gb(amt, unit), "type": "unspecified"}
                    elif bw is None:
                        bw = to_tb(amt, unit)
                elif unit == "TB":
                    if bw is None:
                        bw = to_tb(amt, unit)

        if vcpu is not None and (ram is not None or storage is not None):
            plans.append({
                "name": name, "vcpu": vcpu, "ram_gb": ram,
                "storage_gb": storage["gb"] if storage else None,
                "storage_type": storage["type"] if storage else None,
                "bandwidth_tb": bw,
                "price": ({"amount": price[0], "currency": price[1]}
                          if price else None),
            })
            i = last + 1
        else:
            i += 1

    return plans




KEY_FIELDS = ("vcpu", "ram_gb", "storage_gb", "prices", "cpu_models", "discount")


def build_record(item: dict, reply_info: dict | None = None) -> dict:
    body = strip_html(item["description"])
    text = item["title"] + "\n" + body

    specs = extract_specs(text)
    plans = parse_flat_tables(body)
    prices = extract_prices(text)
    discount = extract_discount(text)
    cpu_models = sorted({re.sub(r"\s+", " ", m).strip()
                         for m in RE_CPU_MODEL.findall(text)})
    locs = extract_locations(item["title"] + "\n" + body[:800])
    stock = sorted({m.group(0).strip() for m in RE_STOCK.finditer(text)})
    days = age_days(item["pubDate"])

    # 表格解析成功时，用表格里的旗舰套餐覆盖/补齐 specs（更准确）
    flagship_price = None
    if plans:
        top_plan = max(plans, key=lambda p: (p["ram_gb"] or 0, p["vcpu"] or 0))
        if top_plan["vcpu"]:
            specs["vcpu"] = top_plan["vcpu"]
        if top_plan["ram_gb"]:
            specs["ram_gb"] = top_plan["ram_gb"]
        if top_plan["storage_gb"]:
            specs["storage_gb"] = top_plan["storage_gb"]
            specs["storage_type"] = top_plan["storage_type"]
        if top_plan["bandwidth_tb"]:
            specs["bandwidth_tb"] = top_plan["bandwidth_tb"]
        # 旗舰套餐的价格（与上面的规格同源，避免"配置是旗舰、价格是入门"）
        tp = top_plan.get("price")
        if tp:
            flagship_price = {"amount": tp["amount"], "currency": tp["currency"],
                              "cycle": "year"}
            prices = [flagship_price] + [
                p for p in prices
                if not (abs(p["amount"] - tp["amount"]) < 1e-9
                        and p["currency"] == tp["currency"])
            ]
        specs["_all"] = {
            "vcpu": sorted({p["vcpu"] for p in plans if p["vcpu"]}, reverse=True),
            "ram_gb": sorted({p["ram_gb"] for p in plans if p["ram_gb"]}, reverse=True),
            "storage_gb": sorted({p["storage_gb"] for p in plans if p["storage_gb"]},
                                 reverse=True),
        }

    age_status = ("NEW" if days is not None and days < NEW_DAYS
                  else "ACTIVE" if days is not None and days <= ACTIVE_DAYS
                  else "STALE" if days is not None else "UNKNOWN")

    filled = sum([
        specs["vcpu"] is not None,
        specs["ram_gb"] is not None,
        specs["storage_gb"] is not None,
        bool(prices),
        bool(cpu_models),
        bool(discount["strength"]),
    ])
    confidence = round(filled / len(KEY_FIELDS), 2)

    # 回帖信号（若已抓取）：库存的权威来源
    reply_status = reply_source = None
    reply_block = None
    if reply_info and reply_info.get("ok"):
        reply_status = reply_info.get("reply_status")
        reply_source = reply_info.get("reply_source")
        reply_block = {
            "reply_count": reply_info.get("reply_count"),
            "vendor_reply_count": reply_info.get("vendor_reply_count"),
            "status": reply_status,
            "source": reply_source,
            "evidence": reply_info.get("reply_evidence"),
            "vendor_signals": reply_info.get("vendor_signals", []),
            "fetched_at": reply_info.get("fetched_at"),
        }

    return {
        "thread_id": item["thread_id"],
        "provider": extract_provider(item["title"], item["author"], body),
        "title": item["title"],
        "url": item["link"],
        "author": item["author"],
        "posted": item["pubDate"],
        "age_days": days,
        "age_status": age_status,
        "availability": availability(stock, days, reply_status, reply_source),
        "replies": reply_block,
        "event_type": extract_event(item["title"], body),
        "discount": discount,
        "specs": {k: v for k, v in specs.items() if not k.startswith("_")},
        "specs_all": specs["_all"],
        "plans": plans[:40],
        "flagship_price": flagship_price,
        "cpu_models": cpu_models[:5],
        "prices": prices[:4],
        "locations": locs,
        "stock_hints": stock,
        "confidence": confidence,
    }


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

EVENT_CN = {
    "anniversary": "周年庆", "black_friday": "黑五", "holiday": "节日促销",
    "launch": "上新/回归", "restock": "补货", "sale": "常规促销",
    "regular": "常规帖",
}
AVAIL_CN = {
    "ON_SALE": "在售", "SOLD_OUT": "售罄", "ENDED": "活动结束",
    "RESTOCKING": "补货中", "LIKELY_SOLD_OUT": "疑似售罄",
    "UNVERIFIED": "待确认", "UNVERIFIED_STALE": "待确认(较旧)",
}


def spec_line(rec: dict) -> str:
    s = rec["specs"]
    bits = []
    if s.get("vcpu"):
        bits.append(f"{s['vcpu']}C")
    if s.get("ram_gb"):
        bits.append(f"{int(s['ram_gb'])}G")
    if s.get("storage_gb"):
        st = s.get("storage_type") or ""
        if st.lower() == "unspecified":
            st = ""
        bits.append(f"{int(s['storage_gb'])}G{st}")
    cpu = ", ".join(rec["cpu_models"][:2])
    head = "/".join(bits) if bits else "—"
    return f"{head} | {cpu}" if cpu else head


def price_line(rec: dict) -> str:
    # 优先用与旗舰配置同源的价格
    p = rec.get("flagship_price") or (rec["prices"][0] if rec["prices"] else None)
    if not p:
        return "—"
    cyc = {"month": "/月", "quarter": "/季", "year": "/年"}.get(p["cycle"], "")
    return f"{p['currency']}{p['amount']:g}{cyc}"


def to_markdown(rows: list[dict]) -> str:
    lines = ["| 厂商 | 活动性质 | 力度 | 配置/CPU | 起价 | 状态 | 置信度 |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            r["provider"].replace("|", "/"),
            EVENT_CN.get(r["event_type"], r["event_type"]),
            (r["discount"]["strength"] or "—").replace("|", "/"),
            spec_line(r).replace("|", "/"),
            price_line(r),
            AVAIL_CN.get(r["availability"], r["availability"]),
            f"{r['confidence']:.2f}",
        ))
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="LET Deals Radar MVP")
    ap.add_argument("--offline", metavar="XML", help="使用本地 RSS XML 文件")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条")
    ap.add_argument("--recent-days", type=int, default=0, help="只保留最近 N 天")
    ap.add_argument("--min-confidence", type=float, default=0.0)
    ap.add_argument("--json-out", default=os.path.join(DATA_DIR, "deals.json"))
    ap.add_argument("--md-out", default=os.path.join(DATA_DIR, "deals.md"))
    ap.add_argument("--with-replies", action="store_true",
                    help="抓取回帖以获取库存信号（慢，但库存准确率高得多）")
    ap.add_argument("--reply-max-pages", type=int, default=2,
                    help="每个帖子最多抓几页回帖（latest 策略下=末页起抓几页）")
    ap.add_argument("--reply-strategy", choices=["latest", "all"], default="latest",
                    help="latest=从末页往前(默认，快且新)；all=从头顺序抓")
    ap.add_argument("--reply-limit", type=int, default=0,
                    help="只对前 N 条抓回帖（0=全部；配合 --with-replies）")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)

    # 1) 取数据 ------------------------------------------------------------
    if args.offline:
        with open(args.offline, "r", encoding="utf-8", errors="replace") as f:
            xml_text = f.read()
        print(f"[1/4] 读取本地 XML: {args.offline} ({len(xml_text):,} 字节)")
    else:
        print(f"[1/4] 抓取 {FEED_URL} ...")
        try:
            xml_text = fetch(FEED_URL)
        except Exception as e:
            print(f"  !! 抓取失败: {e}")
            print("  -> 可以先用浏览器保存 feed，再用 --offline data/feed.xml")
            return 2
        cache = os.path.join(DATA_DIR, "feed.xml")
        with open(cache, "w", encoding="utf-8") as f:
            f.write(xml_text)
        print(f"  成功, {len(xml_text):,} 字节 (已缓存到 {cache})")

    # 2) 解析 RSS ----------------------------------------------------------
    items = parse_rss(xml_text)
    print(f"[2/4] 解析到 {len(items)} 条帖子")
    if args.limit:
        items = items[:args.limit]
        print(f"  限制为前 {len(items)} 条")

    # 3) 回帖抓取（可选）---------------------------------------------------
    reply_map: dict[str, dict] = {}
    if args.with_replies:
        try:
            from fetch_replies import fetch_thread_replies
        except ImportError:
            print("  !! 找不到 fetch_replies.py，跳过回帖抓取")
        else:
            targets = items[:args.reply_limit] if args.reply_limit else items
            print(f"[3/5] 抓取回帖（{len(targets)} 个帖子，策略={args.reply_strategy}，"
                  f"最多 {args.reply_max_pages} 页）...")
            for n, it in enumerate(targets, 1):
                tid = it["thread_id"]
                slug = it["link"].rstrip("/").split("/")[-1] or "x"
                try:
                    info = fetch_thread_replies(
                        tid, slug, max_pages=args.reply_max_pages,
                        strategy=args.reply_strategy, verbose=False)
                    if info.get("ok"):
                        reply_map[tid] = info
                except Exception as e:
                    print(f"    [warn] #{tid} 抓取失败: {type(e).__name__}")
                if n % 10 == 0:
                    print(f"    已处理 {n}/{len(targets)}")
            got = sum(1 for v in reply_map.values() if v.get("reply_status"))
            vgot = sum(1 for v in reply_map.values()
                       if v.get("reply_source") == "vendor")
            print(f"  完成：{len(reply_map)} 个帖子抓到回帖，"
                  f"{got} 个含库存信号（其中 {vgot} 个来自商家表态）")

    # 4) 抽取 --------------------------------------------------------------
    records = [build_record(it, reply_map.get(it["thread_id"])) for it in items]
    step = 4 if args.with_replies else 3
    if args.recent_days:
        before = len(records)
        records = [r for r in records
                   if r["age_days"] is not None and r["age_days"] <= args.recent_days]
        print(f"[{step}/5] 抽取完成，按 {args.recent_days} 天内过滤: "
              f"{before} -> {len(records)}")
    else:
        print(f"[{step}/5] 抽取完成: {len(records)} 条")

    if args.min_confidence:
        records = [r for r in records if r["confidence"] >= args.min_confidence]

    # 4) 输出 --------------------------------------------------------------
    payload = {
        "source": FEED_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(records),
        "records": records,
    }
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 按「活动力度」相关度排序：周年庆/黑五优先，其次置信度
    EVENT_RANK = {"anniversary": 0, "black_friday": 1, "holiday": 2,
                  "launch": 3, "restock": 4, "sale": 5, "regular": 6}
    ranked = sorted(records, key=lambda r: (
        EVENT_RANK.get(r["event_type"], 9),
        -r["confidence"],
        r["age_days"] if r["age_days"] is not None else 9999,
    ))
    md = to_markdown(ranked)
    with open(args.md_out, "w", encoding="utf-8") as f:
        f.write(md)

    # 统计
    n = len(records) or 1
    def pct(pred):
        return f"{sum(1 for r in records if pred(r)) / n * 100:.0f}%"

    print(f"[5/5] 输出: {args.json_out}")
    print(f"          {args.md_out}")
    print()
    print("=" * 72)
    print("字段覆盖率（决定哪些能全自动）")
    print("=" * 72)
    print(f"  vCPU          {pct(lambda r: r['specs'].get('vcpu'))}")
    print(f"  RAM           {pct(lambda r: r['specs'].get('ram_gb'))}")
    print(f"  存储          {pct(lambda r: r['specs'].get('storage_gb'))}")
    print(f"  带宽          {pct(lambda r: r['specs'].get('bandwidth_tb'))}")
    print(f"  CPU 型号      {pct(lambda r: r['cpu_models'])}")
    print(f"  价格          {pct(lambda r: r['prices'])}")
    print(f"  折扣/优惠码    {pct(lambda r: r['discount']['strength'])}")
    print(f"  地点          {pct(lambda r: r['locations'])}")
    print(f"  帖文库存词     {pct(lambda r: r['stock_hints'])}")
    if args.with_replies:
        print(f"  回帖已抓取     {pct(lambda r: r.get('replies'))}")
        print(f"  商家库存表态   {pct(lambda r: (r.get('replies') or {}).get('source') == 'vendor')}")
        print(f"  库存已判定     {pct(lambda r: r['availability'] not in ('UNVERIFIED', 'UNVERIFIED_STALE'))}")
    print()
    print(f"  平均置信度    {sum(r['confidence'] for r in records)/n:.2f}")
    print()
    print("活动性质分布:")
    dist: dict[str, int] = {}
    for r in records:
        dist[r["event_type"]] = dist.get(r["event_type"], 0) + 1
    for k, v in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"    {EVENT_CN.get(k, k):<10} {v:>3}")
    print()
    print("库存状态分布:")
    adist: dict[str, int] = {}
    for r in records:
        adist[r["availability"]] = adist.get(r["availability"], 0) + 1
    for k, v in sorted(adist.items(), key=lambda kv: -kv[1]):
        print(f"    {k:<20} {v:>3}")
    print()
    print("=" * 72)
    print("总览表（按活动力度排序，前 25 条）")
    print("=" * 72)
    print(to_markdown(ranked[:25]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
