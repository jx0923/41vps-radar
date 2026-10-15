#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成精简测试夹具。

为什么不直接提交实时快照：
  1) 700KB+ 的快照会让每次 Actions 运行产生巨大的 git 噪音；
  2) 实时内容会变，导致测试不稳定。

因此只挑选**有代表性**的条目，并截断超长正文，生成稳定的小夹具。

用法: python tools/make_fixtures.py
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(HERE, "tests", "fixtures")
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"

# LET：BERO 十周年帖必须包含 —— 它是表格重建的黄金样本
LET_WANTED_TITLES = [
    "BERO HOST 10th Anniversary",
]
LET_KEEP_EXTRA = 4          # 再保留几条普通帖，验证通用抽取

# LEB：混合「真优惠」与「新闻」，用于验证分类过滤确实生效
LEB_WANTED_TITLES = [
    "Velohost Returns",     # 真优惠
    "Microsoft Slashes",    # 新闻（应被滤除）
    "Giveaway",             # 抽奖（应被硬排除）
]
LEB_KEEP_EXTRA = 3

MAX_BODY = 9000             # 单条正文截断上限（字符）


def _title(it: ET.Element) -> str:
    return (it.findtext("title") or "").strip()


def _truncate(it: ET.Element) -> None:
    """截断超长正文，控制夹具体积。"""
    for tag in (CONTENT, "description"):
        el = it.find(tag)
        if el is not None and el.text and len(el.text) > MAX_BODY:
            el.text = el.text[:MAX_BODY]


def pick(items: list[ET.Element], wanted: list[str], extra: int) -> list[ET.Element]:
    """优先取 wanted 命中的条目，再补足普通条目。"""
    chosen: list[ET.Element] = []
    used = set()
    for want in wanted:
        for i, it in enumerate(items):
            if i in used:
                continue
            if want.lower() in _title(it).lower():
                chosen.append(it)
                used.add(i)
                break
    for i, it in enumerate(items):
        if len(chosen) >= len(wanted) + extra:
            break
        if i not in used:
            chosen.append(it)
            used.add(i)
    return chosen


def build(src: str, dst: str, wanted: list[str], extra: int, label: str) -> int:
    if not os.path.exists(src):
        print(f"  !! 缺少 {src}，跳过")
        return 0
    tree = ET.parse(src)
    channel = tree.getroot().find("channel")
    if channel is None:
        print(f"  !! {src} 无 channel")
        return 0

    items = channel.findall("item")
    keep = pick(items, wanted, extra)

    for it in items:
        channel.remove(it)
    for it in keep:
        _truncate(it)
        channel.append(it)

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tree.write(dst, encoding="utf-8", xml_declaration=True)
    size = os.path.getsize(dst) / 1024
    print(f"  {label:<10} {len(keep):>2} 条  {size:>7.1f} KB  -> {os.path.basename(dst)}")
    for it in keep:
        print(f"      · {_title(it)[:62]}")
    return len(keep)


def main() -> int:
    print("生成精简测试夹具:")
    n1 = build(os.path.join(HERE, "data", "feed_let.xml"),
               os.path.join(FIX, "let_offers_sample.xml"),
               LET_WANTED_TITLES, LET_KEEP_EXTRA, "LET")
    n2 = build(os.path.join(HERE, "data", "feed_leb.xml"),
               os.path.join(FIX, "leb_sample.xml"),
               LEB_WANTED_TITLES, LEB_KEEP_EXTRA, "LEB")
    if not n1 and not n2:
        return 1
    print()
    print("提示：夹具用于测试；实时抓取缓存 data/feed_*.xml 不应提交（见 .gitignore）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
