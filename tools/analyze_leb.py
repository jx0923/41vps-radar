#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经验分析：LEB 的真优惠 vs 新闻，在正文特征上如何区分。"""
import re
import sys
import os
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from letdeals.textutil import strip_html  # noqa: E402

CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
root = ET.parse(os.path.join(HERE, "data", "feed_leb.xml")).getroot()

rows = []
for it in root.iter("item"):
    title = (it.findtext("title") or "").strip()
    cats = [(c.text or "").strip() for c in it.findall("category")]
    body = (it.findtext(CONTENT) or it.findtext("description") or "")
    txt = strip_html(body)
    plain = body

    feat = {
        "cats": ",".join(cats[:2]),
        # 优惠特征
        "has_order_link": bool(re.search(r"\[ORDER|Order Now|ORDER NOW|"
                                         r"/cart|add&pid|store/|billing", plain, re.I)),
        "has_coupon": bool(re.search(r"coupon|promo\s*code", txt, re.I)),
        "n_prices": len(re.findall(r"[$€£]\s*\d+(?:[.,]\d+)?", txt)),
        "has_specs": bool(re.search(r"\d+\s*(?:GB|TB)\s*(?:RAM|SSD|NVMe|HDD|"
                                    r"storage|bandwidth|traffic)", txt, re.I)),
        "n_specs": len(re.findall(r"\d+\s*(?:GB|TB)\s*(?:RAM|SSD|NVMe|HDD|"
                                  r"storage|bandwidth|traffic)", txt, re.I)),
        "has_vcpu": bool(re.search(r"\d+\s*(?:vCPU|vCores?|Cores?)", txt, re.I)),
        "has_provider_link": bool(re.search(r"https?://(?!lowendbox|lowendtalk|"
                                            r"gravatar|wp\.com|i\.imgur)",
                                            plain, re.I)),
    }
    rows.append((title, feat))

print("=" * 100)
print("%-44s %-20s %4s %4s %4s %4s %4s %4s" % (
    "标题", "分类", "ORDER", "券", "价格", "规格", "核", "商链"))
print("=" * 100)
for title, f in rows:
    print("%-44s %-20s %4s %4s %4d %4d %4s %4s" % (
        title[:42], f["cats"][:20],
        "Y" if f["has_order_link"] else ".",
        "Y" if f["has_coupon"] else ".",
        f["n_prices"],
        f["n_specs"],
        "Y" if f["has_vcpu"] else ".",
        "Y" if f["has_provider_link"] else "."))
