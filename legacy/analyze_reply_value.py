#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回帖抓取的收益分析
==================
回答两个问题：
  1. 哪些帖子值得抓回帖（帖子越活跃，商家表态概率越高）？
  2. 抓多少页才够（库存表态通常出现在哪一页）？

结论会指导 --reply-limit / --reply-max-pages 的默认值。
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))

deals = json.load(open(os.path.join(HERE, "data", "deals.json"),
                       encoding="utf-8"))
REPLY_DIR = os.path.join(HERE, "data", "replies")

print("=" * 78)
print("1. 已抓取帖子的回帖规模")
print("=" * 78)
rows = []
for fn in os.listdir(REPLY_DIR):
    if not fn.endswith(".json"):
        continue
    d = json.load(open(os.path.join(REPLY_DIR, fn), encoding="utf-8"))
    rows.append(d)

rows.sort(key=lambda x: -x.get("reply_count", 0))
print("  %-10s %6s %6s %6s %-12s" % ("thread", "页数", "回帖", "商家", "库存信号"))
for d in rows:
    print("  %-10s %6d %6d %6d %-12s" % (
        d["thread_id"], d.get("pages", 0), d.get("reply_count", 0),
        d.get("vendor_reply_count", 0), d.get("reply_status") or "-"))

has_signal = [d for d in rows if d.get("reply_status")]
print()
print("  抓取 %d 帖，其中 %d 帖含库存信号 (%.0f%%)"
      % (len(rows), len(has_signal), len(has_signal) / max(len(rows), 1) * 100))

print()
print("=" * 78)
print("2. 库存表态出现在第几页？")
print("=" * 78)
for fn in os.listdir(REPLY_DIR):
    if not fn.endswith(".json"):
        continue
    d = json.load(open(os.path.join(REPLY_DIR, fn), encoding="utf-8"))
    if not d.get("reply_status"):
        continue
    ev = d.get("reply_evidence") or {}
    # 从 comment_id 顺序推断大致位置（回帖按时间递增）
    cids = [r["comment_id"] for r in d.get("replies", [])]
    pos = None
    if ev.get("comment_id") in cids:
        idx = cids.index(ev["comment_id"])
        pos = (idx + 1) / max(len(cids), 1)
    print("  #%-8s 回帖%3d  商家表态位置≈%.0f%%  (页%d/%d)  %s" % (
        d["thread_id"], len(cids),
        (pos or 0) * 100, d.get("pages", 0), d.get("total_pages", 0),
        ev.get("status")))

print()
print("=" * 78)
print("3. 未抓取的帖子：值不值得抓？（用回帖数代理活跃度）")
print("=" * 78)
fetched = {d["thread_id"] for d in rows}
cand = []
for r in deals["records"]:
    tid = r["thread_id"]
    if tid in fetched:
        continue
    # 活跃度代理：标题含 giveaway / 高置信度 / 大力度事件
    d = r.get("discount") or {}
    score = 0
    if r["event_type"] in ("anniversary", "black_friday"):
        score += 3
    if d.get("recurring"):
        score += 2
    if re.search(r"giveaway|give away", r["title"], re.I):
        score += 2
    if d.get("codes"):
        score += 1
    if r["age_days"] is not None and r["age_days"] <= 30:
        score += 1
    cand.append((score, r))

cand.sort(key=lambda x: -x[0])
print("  未抓取帖子中，优先值得抓的前 12 个:")
for score, r in cand[:12]:
    print("    优先分%2d  %-24s %-10s %s" % (
        score, r["provider"][:24],
        r["event_type"], (r.get("discount") or {}).get("strength", "")[:40]))
