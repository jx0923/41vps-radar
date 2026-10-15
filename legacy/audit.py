#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""准确性审计：量化哪些帖子能全自动抽取，哪些必须人工兜底。"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, "data", "deals.json"), encoding="utf-8"))
recs = d["records"]


def avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


withplans = [r for r in recs if r["plans"]]
nop = [r for r in recs if not r["plans"]]

print("=" * 74)
print("解析成功率")
print("=" * 74)
print("解析出套餐表的帖子: %d/%d  (%.0f%%)" % (
    len(withplans), len(recs), len(withplans) / len(recs) * 100))
print("未解析出表的帖子  : %d/%d  (%.0f%%)" % (
    len(nop), len(recs), len(nop) / len(recs) * 100))
print()
print("置信度对比:")
print("  有表: %.2f" % avg([r["confidence"] for r in withplans]))
print("  无表: %.2f" % avg([r["confidence"] for r in nop]))
print()

print("=" * 74)
print("无表帖子（必须人工兜底 / 或改用 LLM 抽取）")
print("=" * 74)
for r in sorted(nop, key=lambda x: -x["confidence"])[:12]:
    print("  [%.2f] %-26s | %s" % (
        r["confidence"], r["provider"][:26], r["title"][:50]))
print()

print("=" * 74)
print("有表帖子中，各字段的可用率")
print("=" * 74)
n = len(withplans) or 1
for label, key in [("vCPU", "vcpu"), ("RAM", "ram_gb"), ("存储", "storage_gb"),
                   ("带宽", "bandwidth_tb")]:
    cnt = sum(1 for r in withplans if r["specs"].get(key))
    print("  %-6s %3d/%d  (%.0f%%)" % (label, cnt, n, cnt / n * 100))

print()
print("=" * 74)
print("全库字段覆盖率（含无表帖子）")
print("=" * 74)
n = len(recs)
for label, fn in [
    ("vCPU", lambda r: r["specs"].get("vcpu")),
    ("RAM", lambda r: r["specs"].get("ram_gb")),
    ("存储", lambda r: r["specs"].get("storage_gb")),
    ("带宽", lambda r: r["specs"].get("bandwidth_tb")),
    ("CPU 型号", lambda r: r["cpu_models"]),
    ("价格", lambda r: r["prices"]),
    ("折扣", lambda r: r["discount"]["strength"]),
    ("优惠码", lambda r: r["discount"]["codes"]),
    ("地点", lambda r: r["locations"]),
    ("库存信号", lambda r: r["stock_hints"]),
    ("套餐表", lambda r: r["plans"]),
]:
    cnt = sum(1 for r in recs if fn(r))
    print("  %-10s %3d/%d  (%.0f%%)" % (label, cnt, n, cnt / n * 100))

print()
print("=" * 74)
print("库存/可用性信号分布（全自动可达的上限）")
print("=" * 74)
dist = {}
for r in recs:
    dist[r["availability"]] = dist.get(r["availability"], 0) + 1
for k, v in sorted(dist.items(), key=lambda kv: -kv[1]):
    print("  %-20s %3d" % (k, v))
print()
print("注：UNVERIFIED* 占多数，说明仅靠帖文无法判断库存，")
print("    必须配合厂商下单页探测才能得到真实库存。")
