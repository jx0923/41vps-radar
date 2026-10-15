#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归验证：重构后的输出必须与基线逐字段一致。

比较 data/old_deals.json（重构前 prototype.py 产出）
与   data/new_deals.json（重构后 letdeals 产出）。

两者使用相同的输入（data/feed.xml）且都未启用回帖，因此
除了新增字段（source）外，所有共有字段都应完全相同。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

old = json.load(open(os.path.join(HERE, "data", "old_deals.json"), encoding="utf-8"))
new = json.load(open(os.path.join(HERE, "data", "new_deals.json"), encoding="utf-8"))

o = {r["thread_id"]: r for r in old["records"]}
n = {r["thread_id"]: r for r in new["records"]}

print("=" * 76)
print("回归验证：重构前 vs 重构后")
print("=" * 76)
print(f"  旧记录数: {len(o)}   新记录数: {len(n)}")

fails = []
warns = []

if set(o) != set(n):
    only_old = set(o) - set(n)
    only_new = set(n) - set(o)
    if only_old:
        fails.append(f"仅旧代码有的 thread_id: {sorted(only_old)[:5]}")
    if only_new:
        fails.append(f"仅新代码有的 thread_id: {sorted(only_new)[:5]}")
else:
    print("  [OK] thread_id 集合完全一致")

# 逐字段比较（source 是新增字段，跳过）
IGNORE = {"source"}
FIELD_CHECKS = [
    "provider", "title", "url", "author", "posted", "age_days", "age_status",
    "availability", "event_type", "discount", "specs", "specs_all", "plans",
    "flagship_price", "cpu_models", "prices", "locations", "stock_hints",
    "confidence",
]

diffs = {}
drift = {}
for tid in sorted(set(o) & set(n)):
    for f in FIELD_CHECKS:
        a, b = o[tid].get(f), n[tid].get(f)
        if a == b:
            continue
        # age_days 按「当前时间」计算，两次运行跨过 UTC 午夜就会 +1，
        # 这是时间漂移而非回归。仅当差值超出合理范围才判失败。
        if f == "age_days" and isinstance(a, int) and isinstance(b, int) \
                and abs(b - a) <= 1:
            drift.setdefault(f, []).append((tid, a, b))
            continue
        diffs.setdefault(f, []).append((tid, a, b))

print()
print("=" * 76)
print("逐字段差异")
print("=" * 76)
if drift:
    n_drift = sum(len(v) for v in drift.values())
    print(f"  [OK] {n_drift} 处 age_days 为时间漂移（±1 天，非回归）")
if not diffs:
    print("  [OK] 所有共有字段完全一致（零回归差异）")
else:
    for f, items in sorted(diffs.items()):
        print(f"\n  字段 {f}: {len(items)} 处差异")
        for tid, a, b in items[:3]:
            sa = json.dumps(a, ensure_ascii=False)[:110]
            sb = json.dumps(b, ensure_ascii=False)[:110]
            print(f"    #{tid}")
            print(f"      旧: {sa}")
            print(f"      新: {sb}")
        if len(items) > 3:
            print(f"      ... 另有 {len(items)-3} 处")
        fails.append(f"字段 {f} 有 {len(items)} 处差异")

# 重点抽查 BERO
print()
print("=" * 76)
print("关键数据点抽查")
print("=" * 76)
bero_old = [r for r in old["records"] if "BERO" in r["title"].upper()]
bero_new = [r for r in new["records"] if "BERO" in r["title"].upper()]
if bero_old and bero_new:
    a, b = bero_old[0], bero_new[0]
    keys = ["provider", "specs", "flagship_price", "event_type", "confidence"]
    same = all(a.get(k) == b.get(k) for k in keys)
    print(f"  BERO specs : {b['specs']}")
    print(f"  BERO price : {b['flagship_price']}")
    print(f"  BERO plans : {len(b['plans'])} 条")
    print(f"  [{'OK' if same else 'FAIL'}] 关键字段一致")
    if not same:
        for k in keys:
            if a.get(k) != b.get(k):
                print(f"      {k}: 旧={a.get(k)} 新={b.get(k)}")
        fails.append("BERO 关键字段不一致")
else:
    warns.append("样本中未找到 BERO 记录")

# 新字段检查
has_source = all("source" in r for r in new["records"])
print(f"  [{'OK' if has_source else 'FAIL'}] 新记录均含 source 字段")
if not has_source:
    fails.append("部分新记录缺少 source 字段")

print()
print("=" * 76)
if fails:
    print(f"结果: {len(fails)} 项失败")
    for f in fails[:10]:
        print(f"  - {f}")
    sys.exit(1)
print(f"结果: 回归通过 —— 重构未改变抽取行为 ({len(warns)} 项提示)")
