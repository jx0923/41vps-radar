#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽查库存判定的准确性：列出所有非 UNVERIFIED 的判定及其证据。"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, "data", "deals.json"), encoding="utf-8"))

VENDOR_STATES = ("ON_SALE", "SOLD_OUT", "ENDED", "RESTOCKING")
USER_STATES = ("LIKELY_SOLD_OUT",)

print("=" * 78)
print("A. 商家表态驱动的判定（权威，需逐条核对）")
print("=" * 78)
n = 0
for r in d["records"]:
    rp = r.get("replies") or {}
    if rp.get("source") != "vendor":
        continue
    n += 1
    ev = rp.get("evidence") or {}
    print("\n%2d. %-24s -> %s" % (n, r["provider"][:24], r["availability"]))
    print("    匹配: %r" % (ev.get("match") or "")[:70])
    print("    原文: %s" % (ev.get("snippet") or "")[:150])

print()
print("=" * 78)
print("B. 用户回帖驱动的判定（弱证据，仅提示）")
print("=" * 78)
for r in d["records"]:
    rp = r.get("replies") or {}
    if rp.get("source") != "user":
        continue
    ev = rp.get("evidence") or {}
    print("\n  %-24s -> %s" % (r["provider"][:24], r["availability"]))
    print("    作者: %s   原文: %s" % (ev.get("author"), (ev.get("snippet") or "")[:130]))

print()
print("=" * 78)
print("C. 帖文关键词驱动（回帖无信号时）")
print("=" * 78)
m = 0
for r in d["records"]:
    rp = r.get("replies") or {}
    if rp.get("source"):
        continue
    if r["availability"] in ("UNVERIFIED", "UNVERIFIED_STALE"):
        continue
    m += 1
    print("  %-24s -> %-12s 词: %s" % (
        r["provider"][:24], r["availability"], r["stock_hints"]))

print()
print("=" * 78)
print("汇总")
print("=" * 78)
tot = len(d["records"])
v = sum(1 for r in d["records"] if (r.get("replies") or {}).get("source") == "vendor")
u = sum(1 for r in d["records"] if (r.get("replies") or {}).get("source") == "user")
k = sum(1 for r in d["records"]
        if not (r.get("replies") or {}).get("source")
        and r["availability"] not in ("UNVERIFIED", "UNVERIFIED_STALE"))
print("  总记录            : %d" % tot)
print("  商家表态判定      : %d  (%.0f%%)" % (v, v / tot * 100))
print("  用户回帖判定(弱)  : %d  (%.0f%%)" % (u, u / tot * 100))
print("  仅帖文关键词      : %d  (%.0f%%)" % (k, k / tot * 100))
print("  完全未判定        : %d  (%.0f%%)" % (
    tot - v - u - k, (tot - v - u - k) / tot * 100))
