#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LET 回帖抓取器
==============
从 LowEndTalk 讨论页抓取全部回帖，重点提取**商家本人回复**中的库存信号。

为什么需要这个：
    帖子正文通常不写库存，商家只在**回帖里**事后说「售罄了 / 补货了」。
    RSS 只给首帖正文，不含回帖 —— 这是库存信号覆盖率只有 25% 的根因。

关键机制：
    LET 用 CSS class 标记回帖身份，其中商家本人带：
        isOriginalPoster Role_PatronProvider
    这类回复对库存最有权威性，因此单独加权。

分页：
    路径式 /pN（首帖即 p1），最大页码从 Pager 里解析。

用法（独立测试）:
    python fetch_replies.py 221713
    python fetch_replies.py 221713 --max-pages 5
"""

from __future__ import annotations

import argparse
import gzip
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

DEFAULT_TIMEOUT = 30
DEFAULT_DELAY = 0.8      # 页间延迟，对站点友好
MAX_PAGES_HARD = 25      # 硬上限，避免异常帖把抓取拖爆

CACHE_DIR = os.path.join(HERE, "data", "replies")


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def fetch_html(url: str, timeout: int = DEFAULT_TIMEOUT) -> str | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------

RE_ITEM_SPLIT = re.compile(
    r'<li class="(Item[^"]*ItemComment[^"]*)"', re.I)
RE_COMMENT_ID = re.compile(r'id="Comment_(\d+)"')
RE_AUTHOR = re.compile(r'href="/profile/([A-Za-z0-9_\-\.]+)"')
RE_DATETIME = re.compile(r'<time[^>]*datetime="([^"]+)"')
RE_BODY = re.compile(
    r'<div class="Message[^"]*"[^>]*>(.*?)</div>\s*(?:</div>|<div class="Reactions)',
    re.S)
RE_BODY_LOOSE = re.compile(r'<div class="Message[^"]*"[^>]*>(.*)', re.S)
RE_TAG = re.compile(r"<[^>]+>")
RE_MAXPAGE = re.compile(r"/p(\d+)")
RE_BQ_OPEN = re.compile(r"<blockquote\b", re.I)
RE_BQ_CLOSE = re.compile(r"</blockquote\s*>", re.I)
# 把 HTML 切成「标签 / 文本」token 流
RE_TOKEN = re.compile(r"<[^>]+>|[^<]+", re.S)


def strip_quotes_depth_aware(fragment: str) -> str:
    """剥离任意深度的嵌套 <blockquote>，只保留深度 0 的正文。

    LET 的引用是**多层嵌套**的（一条回复可引用「A 引用 B 引用 C」），
    简单的非贪婪正则 `<blockquote.*?</blockquote>` 会从最内层开始剥，
    反而把外层被引用的原文留在结果里 —— 导致把别人的话当成商家表态。
    因此必须按嵌套深度过滤。
    """
    out = []
    depth = 0
    for tok in RE_TOKEN.findall(fragment):
        if tok.startswith("<"):
            if RE_BQ_OPEN.match(tok):
                depth += 1
            elif RE_BQ_CLOSE.match(tok):
                depth = max(0, depth - 1)
            # 其他标签：仅在深度 0 时保留为分隔符
            elif depth == 0 and re.match(r"</(p|div|li|h[1-6]|br)\s*/?>", tok, re.I):
                out.append("\n")
            continue
        if depth == 0:
            out.append(tok)
    return "".join(out)


def clean_text(s: str) -> str:
    """HTML 片段 -> 纯文本（剔除全部引用，含嵌套）。"""
    s = strip_quotes_depth_aware(s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|li|h[1-6])>", "\n", s, flags=re.I)
    s = RE_TAG.sub(" ", s)
    s = html_mod.unescape(s)
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def parse_replies(html: str) -> list[dict]:
    """解析单页 HTML 里的所有回帖。

    LET 的每个回帖是一个 <li class="Item ... ItemComment ..."> 块。
    用 class 属性作为切分锚点，比嵌套 div 正则稳健得多。
    """
    # 按 ItemComment 锚点切块
    marks = [(m.start(), m.group(1)) for m in RE_ITEM_SPLIT.finditer(html)]
    if not marks:
        return []

    replies = []
    for i, (pos, cls) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
        block = html[pos:end]

        cid_m = RE_COMMENT_ID.search(block)
        if not cid_m:
            continue
        cid = cid_m.group(1)

        au = RE_AUTHOR.search(block)
        dt = RE_DATETIME.search(block)

        body_m = RE_BODY.search(block) or RE_BODY_LOOSE.search(block)
        body = clean_text(body_m.group(1)) if body_m else ""

        is_op = "isOriginalPoster" in cls
        is_provider = "Role_PatronProvider" in cls

        replies.append({
            "comment_id": cid,
            "author": au.group(1) if au else None,
            "datetime": dt.group(1) if dt else None,
            "body": body,
            "is_op": is_op,                 # 发帖人（商家）
            "is_provider": is_provider,     # 论坛认证的商家身份
            # 商家本人的回复对库存最有权威性
            "is_vendor_reply": bool(is_op or is_provider),
        })
    return replies


def find_max_page(html: str) -> int:
    pages = [int(x) for x in RE_MAXPAGE.findall(html)]
    return max(pages) if pages else 1


# --------------------------------------------------------------------------
# 库存信号抽取（回帖专用）
# --------------------------------------------------------------------------

# 分档：越靠前越权威。顺序至关重要 —— "working on a restock" 意味着**当前缺货**，
# 必须排在 "restocked"（已补好）之前，否则语义会反。
STOCK_PATTERNS = [
    # 明确售罄
    ("SOLD_OUT", re.compile(
        r"\b(?:is|are|was|were|now)?\s*(?:already\s+)?sold\s*out\b"
        r"|\bout\s+of\s+stock\b|\bno\s+longer\s+available\b"
        r"|\bwe(?:'re| are)\s+out\b|\bstock\s+(?:is\s+)?(?:gone|empty)\b"
        r"|\ball\s+plans?\b[^.]{0,40}\b(?:sold\s*out|out\s+of\s+stock)\b"
        r"|售罄|已售完|缺货", re.I)),
    # 正在补货 => 仍处于缺货状态（关键：必须早于 ON_SALE 判定）
    ("RESTOCKING", re.compile(
        r"\bwork(?:ing)?\s+on\s+(?:a\s+|the\s+)?restock"
        r"|\b(?:working|work)\s+on\s+restocking\b"
        r"|\bwill\s+(?:be\s+)?restock"
        r"|\brestock\s+(?:is\s+)?(?:coming|in\s+progress|underway)\b"
        r"|\bshould\s+take\s+no\s+more\s+than\b"
        r"|\bwait\s+(?:a\s+)?(?:little\s+while|for\s+(?:a\s+)?restock)\b"
        r"|正在补货|补货中", re.I)),
    # 活动结束 / 不再补货
    ("ENDED", re.compile(
        r"\bno\s+further\s+restocks?\b|\bsale\s+is\s+over\b"
        r"|\bpromotion\s+(?:is\s+)?(?:over|ended)\b"
        r"|\bdeal\s+(?:has\s+)?ended\b|\bback\s+to\s+(?:their\s+)?regular\s+prices?\b"
        r"|\bno\s+longer\s+on\s+sale\b|活动结束|不再补货", re.I)),
    # 补货完成 / 有货（放在 RESTOCKING 之后）
    ("ON_SALE", re.compile(
        r"\balready\s+restocked\b|\brestocked\b|\bback\s+in\s+stock\b"
        r"|\bwe(?:'ve| have)\s+(?:just\s+)?(?:added|restocked)\b"
        r"|\bnow\s+available\b|\bstock\s+(?:is\s+)?(?:available|refilled)\b"
        r"|\bin\s+stock\s+again\b|\b(?:plans?|servers?)\s+(?:are|is)\s+(?:still\s+)?available\b"
        r"|补货完成|已补货|重新上架", re.I)),
]

# 只在商家回复里才算数的强信号
VENDOR_ONLY = re.compile(
    r"\bsold\s*out\b|\brestock|\bout\s+of\s+stock\b|\bno\s+further\b"
    r"|\bwe(?:'ve| have)\s+(?:just\s+)?(?:added|restocked)\b", re.I)

# ---- 语境校验：排除「疑问句」和「非库存对象」两类误判 ----
# 1) 疑问句：「BF L Flash sold out ?」是提问，不是表态
RE_QUESTION = re.compile(r"[?？]\s*$|\b(?:is|are|was|were|did|does|do)\b[^.!?]{0,40}$",
                         re.I)
# 2) 非库存对象：说"试用/功能/IP 可用"不等于库存可用
STOCK_OBJECT = re.compile(
    r"\b(stock|stocks|inventory|units?|plans?|packages?|bundles?|servers?|"
    r"vps|vm|vms|slots?|capacity|deals?|offers?)\b", re.I)
NON_STOCK_OBJECT = re.compile(
    r"\b(trial|trials|tier|tiers|feature|features|api|apis?|ip|ips|"
    r"tool|tools|panel|panels|dashboard|docs?|documentation|"
    r"domain|domains|ssl|certificate|coupon|coupons?)\b", re.I)

# 3) 促销资格 vs 库存：说"促销适用于某类套餐"不是库存表态
RE_ELIGIBILITY = re.compile(
    r"\b(?:promotion|promo|discount|coupon|offer|deal)\b[^.]{0,60}"
    r"\b(?:is|are|applies|valid|available|exclusive)\b[^.]{0,60}"
    r"\b(?:only|applies|valid|exclusive|for\s+packages?|for\s+plans?|"
    r"monthly|annual|yearly|billing|cycle)\b", re.I)


def _is_valid_statement(snippet: str, match_text: str) -> bool:
    """判断命中是否构成一次真正的库存表态。

    三类常见误判：
      · 疑问句 —— 「sold out ?」是用户在问，不是商家在说
      · 非库存对象 —— 「trial is now available」「added the test ips」
      · 促销资格 —— 「promotion ... is available only for monthly billing」
    """
    tail = snippet[-60:] if snippet else ""
    # 疑问句：命中点之后紧跟问号，或整句是疑问结构
    if RE_QUESTION.search(tail):
        return False

    low = snippet.lower()
    m = match_text.lower()

    # 促销资格表述：与库存无关
    if RE_ELIGIBILITY.search(snippet):
        return False

    # 「now available」/「added」这类宽泛措辞，要求附近出现库存对象，
    # 且不能是 trial/api/ip 等非库存对象
    if re.search(r"now\s+available|have\s+added|we(?:'ve| have)\s+added"
                 r"|(?:plans?|servers?)\s+(?:are|is)\s+(?:still\s+)?available",
                 m):
        if NON_STOCK_OBJECT.search(low):
            return False
        if not STOCK_OBJECT.search(low):
            return False
        # 若句子主体是 promotion/offer，则不是库存
        if re.search(r"\b(?:promotion|promo|discount|offer)\b", low) and \
           not re.search(r"\b(?:stock|units?|inventory|slots?|capacity)\b", low):
            return False

    return True


def extract_stock_signals(replies: list[dict]) -> dict:
    """从回帖里抽库存信号。

    策略：**商家回复优先**。商家说了算；普通用户说「sold out」可能是猜测。
    """
    vendor_hits = []
    user_hits = []

    for r in replies:
        body = r.get("body") or ""
        if not body:
            continue
        for label, rx in STOCK_PATTERNS:
            m = rx.search(body)
            if not m:
                continue
            snippet = body[max(0, m.start() - 90): m.end() + 90]
            snippet = re.sub(r"\s+", " ", snippet).strip()
            # 语境校验：挡掉疑问句与非库存对象
            if not _is_valid_statement(snippet, m.group(0)):
                continue
            rec = {
                "status": label,
                "author": r.get("author"),
                "is_vendor": r.get("is_vendor_reply"),
                "datetime": r.get("datetime"),
                "match": m.group(0),
                "snippet": snippet,
                "comment_id": r.get("comment_id"),
            }
            (vendor_hits if r.get("is_vendor_reply") else user_hits).append(rec)
            break   # 每条回复只取第一个命中的模式

    # 判定优先级：商家信号 > 用户信号
    if vendor_hits:
        # 取最后一条商家表态（最新状态）
        latest = sorted(vendor_hits, key=lambda x: x.get("datetime") or "")[-1]
        status = latest["status"]
        source = "vendor"
        evidence = latest
    elif user_hits:
        # 用户信号降级：只在没有任何商家表态时才用，且标记为弱证据
        latest = sorted(user_hits, key=lambda x: x.get("datetime") or "")[-1]
        status = latest["status"]
        source = "user"
        evidence = latest
    else:
        status = None
        source = None
        evidence = None

    return {
        "reply_status": status,
        "reply_source": source,          # vendor / user / None
        "reply_evidence": evidence,
        "vendor_signals": vendor_hits[-5:],
        "user_signals": user_hits[-5:],
        "vendor_reply_count": sum(1 for r in replies if r.get("is_vendor_reply")),
        "reply_count": len(replies),
    }


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------

def fetch_thread_replies(thread_id: str, slug: str = "x",
                         max_pages: int = MAX_PAGES_HARD,
                         delay: float = DEFAULT_DELAY,
                         use_cache: bool = True,
                         strategy: str = "latest",
                         verbose: bool = True) -> dict:
    """抓取一个讨论帖的回帖并抽库存信号。

    strategy:
      "latest" (默认) — **从最后一页往前抓**。
          实测根据：库存表态出现在回帖流的 75%–100% 位置
          （商家只在事后回帖说"售罄/补货"），因此末页信息密度最高。
          只抓最后一页即可覆盖大多数库存信号，速度快、请求少。
      "all"    — 从头顺序抓全部分页（最完整，但慢）。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, "%s.json" % thread_id)

    if use_cache and os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < 3600:      # 1 小时内复用，避免重复抓取
            try:
                with open(cache_file, encoding="utf-8") as f:
                    cached = json.load(f)
                if verbose:
                    print("    [cache] #%s 回帖 %d 条"
                          % (thread_id, cached.get("reply_count", 0)))
                return cached
            except Exception:
                pass

    base = "https://lowendtalk.com/discussion/%s/%s" % (thread_id, slug)

    # 先抓首页：既能拿回帖，也能解析出总页数
    first = fetch_html(base)
    if not first:
        return {"thread_id": thread_id, "ok": False,
                "error": "first page fetch failed", "replies": [],
                "reply_count": 0, "reply_status": None}

    total_pages = find_max_page(first)
    all_replies = parse_replies(first)
    pages_fetched = [1]

    # 决定还要抓哪些页
    if strategy == "latest":
        # 从末页往回抓（末页 = 最新回帖 = 商家最新表态）
        order = list(range(total_pages, 1, -1))[:max(1, max_pages - 1)]
    else:
        order = list(range(2, total_pages + 1))[:max(1, max_pages - 1)]

    for p in order:
        time.sleep(delay)
        page_html = fetch_html("%s/p%d" % (base, p))
        if not page_html:
            if verbose:
                print("    [warn] #%s p%d 抓取失败" % (thread_id, p))
            continue
        got = parse_replies(page_html)
        if got:
            all_replies.extend(got)
            pages_fetched.append(p)
        if strategy == "latest" and got:
            # 末页已拿到足够信息：若已发现商家表态即可提前停止
            probe = extract_stock_signals(all_replies)
            if probe.get("reply_source") == "vendor" and len(pages_fetched) >= 1:
                break

    # 去重
    seen, uniq = set(), []
    for r in all_replies:
        if r["comment_id"] in seen:
            continue
        seen.add(r["comment_id"])
        uniq.append(r)
    # 按时间排序，保证时间线正确
    uniq.sort(key=lambda r: (r.get("datetime") or "", r.get("comment_id") or ""))

    signals = extract_stock_signals(uniq)
    result = {
        "thread_id": thread_id,
        "ok": True,
        "strategy": strategy,
        "pages": len(pages_fetched),
        "pages_fetched": sorted(pages_fetched),
        "total_pages": total_pages,
        "reply_count": len(uniq),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **signals,
        "replies": uniq,
    }

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="LET 回帖抓取器")
    ap.add_argument("thread_id")
    ap.add_argument("--slug", default="x")
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES_HARD,
                    help="最多抓几页（latest 策略下 = 从末页往前抓几页）")
    ap.add_argument("--strategy", choices=["latest", "all"], default="latest",
                    help="latest=从末页往前(默认，快)；all=从头顺序抓(慢)")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    print("抓取讨论 #%s (策略=%s) ..." % (args.thread_id, args.strategy))
    res = fetch_thread_replies(args.thread_id, args.slug,
                               max_pages=args.max_pages,
                               strategy=args.strategy,
                               use_cache=not args.no_cache)

    if not res.get("ok"):
        print("失败: %s" % res.get("error"))
        return 1

    print()
    print("=" * 74)
    print("结果")
    print("=" * 74)
    print("  页数       : %d / %d" % (res["pages"], res["total_pages"]))
    print("  回帖数     : %d" % res["reply_count"])
    print("  商家回复数 : %d" % res["vendor_reply_count"])
    print("  库存状态   : %s  (来源: %s)"
          % (res["reply_status"], res["reply_source"]))
    if res.get("reply_evidence"):
        ev = res["reply_evidence"]
        print("  证据作者   : %s (商家=%s)" % (ev["author"], ev["is_vendor"]))
        print("  证据时间   : %s" % ev["datetime"])
        print("  证据片段   : %s" % ev["snippet"][:150])

    if res.get("vendor_signals"):
        print()
        print("商家表态时间线:")
        for s in res["vendor_signals"]:
            print("  [%s] %-10s %s" % (s["datetime"] or "?", s["status"],
                                       s["snippet"][:96]))

    print()
    print("前 5 条回帖预览:")
    for r in res["replies"][:5]:
        flag = "商家" if r["is_vendor_reply"] else "用户"
        print("  [%s] %-16s %s" % (flag, r["author"] or "?",
                                   (r["body"] or "")[:70].replace("\n", " ")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
