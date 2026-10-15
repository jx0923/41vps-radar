"""回帖抓取与库存表态判定。

为什么需要这一层
----------------
帖子正文通常**不写库存**，商家只在**回帖里**事后说「售罄了 / 补货了」。
RSS 只给首帖正文、不含回帖 —— 这是只靠帖文时库存判定率很低的根因。

三个关键设计
------------
1. **末页优先**：实测库存表态出现在回帖流的 75%–100% 位置
   （商家只在被问到时才回），因此从最后一页往前抓，1 页即可拿到最新状态。
2. **商家身份加权**：LET 用 CSS class 标记身份，商家本人带
   ``isOriginalPoster Role_PatronProvider``。判定优先级：
   商家表态 > 帖文关键词 > 用户提及(弱证据)。
3. **语境校验**：挡掉疑问句、「试用可用」、促销资格表述等假信号。
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone

from . import config
from .http import FetchError, fetch
from .textutil import strip_html

# --------------------------------------------------------------------------
# 回帖页解析
# --------------------------------------------------------------------------

RE_ITEM_SPLIT = re.compile(r'<li class="(Item[^"]*ItemComment[^"]*)"', re.I)
RE_COMMENT_ID = re.compile(r'id="Comment_(\d+)"')
RE_AUTHOR = re.compile(r'href="/profile/([A-Za-z0-9_\-\.]+)"')
RE_DATETIME = re.compile(r'<time[^>]*datetime="([^"]+)"')
RE_BODY = re.compile(
    r'<div class="Message[^"]*"[^>]*>(.*?)</div>\s*'
    r'(?:</div>|<div class="Reactions)', re.S)
RE_BODY_LOOSE = re.compile(r'<div class="Message[^"]*"[^>]*>(.*)', re.S)
RE_MAXPAGE = re.compile(r"/p(\d+)")


def parse_replies(html: str) -> list[dict]:
    """解析单页 HTML 里的所有回帖。

    以 ``<li class="... ItemComment ...">`` 作为切分锚点，
    比嵌套 div 正则稳健得多。
    """
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

        au = RE_AUTHOR.search(block)
        dt = RE_DATETIME.search(block)
        body_m = RE_BODY.search(block) or RE_BODY_LOOSE.search(block)
        body = strip_html(body_m.group(1), drop_quotes=True) if body_m else ""

        replies.append({
            "comment_id": cid_m.group(1),
            "author": au.group(1) if au else None,
            "datetime": dt.group(1) if dt else None,
            "body": body,
            "is_op": "isOriginalPoster" in cls,
            "is_provider": "Role_PatronProvider" in cls,
            "is_vendor_reply": bool("isOriginalPoster" in cls
                                    or "Role_PatronProvider" in cls),
        })
    return replies


def find_max_page(html: str) -> int:
    pages = [int(x) for x in RE_MAXPAGE.findall(html)]
    return max(pages) if pages else 1


# --------------------------------------------------------------------------
# 库存信号模式
# --------------------------------------------------------------------------
#
# 顺序至关重要 —— "working on a restock" 意味着**当前缺货**，
# 必须排在 "restocked"（已补好）之前，否则语义会反。

STOCK_PATTERNS = [
    ("SOLD_OUT", re.compile(
        r"\b(?:is|are|was|were|now)?\s*(?:already\s+)?sold\s*out\b"
        r"|\bout\s+of\s+stock\b|\bno\s+longer\s+available\b"
        r"|\bwe(?:'re| are)\s+out\b|\bstock\s+(?:is\s+)?(?:gone|empty)\b"
        r"|\ball\s+plans?\b[^.]{0,40}\b(?:sold\s*out|out\s+of\s+stock)\b"
        r"|售罄|已售完|缺货", re.I)),
    # 正在补货 => 仍处于缺货状态
    ("RESTOCKING", re.compile(
        r"\bwork(?:ing)?\s+on\s+(?:a\s+|the\s+)?restock"
        r"|\b(?:working|work)\s+on\s+restocking\b"
        r"|\bwill\s+(?:be\s+)?restock"
        r"|\brestock\s+(?:is\s+)?(?:coming|in\s+progress|underway)\b"
        r"|\bshould\s+take\s+no\s+more\s+than\b"
        r"|\bwait\s+(?:a\s+)?(?:little\s+while|for\s+(?:a\s+)?restock)\b"
        r"|正在补货|补货中", re.I)),
    ("ENDED", re.compile(
        r"\bno\s+further\s+restocks?\b|\bsale\s+is\s+over\b"
        r"|\bpromotion\s+(?:is\s+)?(?:over|ended)\b"
        r"|\bdeal\s+(?:has\s+)?ended\b"
        r"|\bback\s+to\s+(?:their\s+)?regular\s+prices?\b"
        r"|\bno\s+longer\s+on\s+sale\b|活动结束|不再补货", re.I)),
    ("ON_SALE", re.compile(
        r"\balready\s+restocked\b|\brestocked\b|\bback\s+in\s+stock\b"
        r"|\bwe(?:'ve| have)\s+(?:just\s+)?(?:added|restocked)\b"
        r"|\bnow\s+available\b|\bstock\s+(?:is\s+)?(?:available|refilled)\b"
        r"|\bin\s+stock\s+again\b"
        # 「still in stock」「remains in stock」「still available」——
        # 用于识别"另一部分仍有货"（部分售罄场景）
        r"|\b(?:still|remains?|is|are)\s+in\s+stock\b"
        r"|\bstill\s+available\b"
        r"|\b(?:plans?|servers?)\s+(?:are|is)\s+(?:still\s+)?available\b"
        r"|补货完成|已补货|重新上架", re.I)),
]

# ---- 语境校验：排除假信号 ----

# 疑问句：「BF L Flash sold out ?」是提问，不是表态。
#
# 注意不能用「句中含 is/are」这种过宽的规则 —— 那会把
# 「All plans are sold out now」这类正常陈述也误杀。
# 只认两种明确形态：
#   1) 以问号结尾
#   2) 以疑问词开头（Is it sold out / Are these available / Did you restock）
RE_QUESTION_END = re.compile(r"[?？]\s*$")
RE_QUESTION_START = re.compile(
    r"^\W*(?:is|are|was|were|do|does|did|will|would|can|could|should|"
    r"any|what|why|how|when|where|which|who)\b", re.I)

STOCK_OBJECT = re.compile(
    r"\b(stock|stocks|inventory|units?|plans?|packages?|bundles?|servers?|"
    r"vps|vm|vms|slots?|capacity|deals?|offers?)\b", re.I)
NON_STOCK_OBJECT = re.compile(
    r"\b(trial|trials|tier|tiers|feature|features|api|apis?|ip|ips|"
    r"tool|tools|panel|panels|dashboard|docs?|documentation|"
    r"domain|domains|ssl|certificate|coupon|coupons?)\b", re.I)
# 促销资格 vs 库存：说「促销适用于某类套餐」不是库存表态
RE_ELIGIBILITY = re.compile(
    r"\b(?:promotion|promo|discount|coupon|offer|deal)\b[^.]{0,60}"
    r"\b(?:is|are|applies|valid|available|exclusive)\b[^.]{0,60}"
    r"\b(?:only|applies|valid|exclusive|for\s+packages?|for\s+plans?|"
    r"monthly|annual|yearly|billing|cycle)\b", re.I)

# 「不是那样 / 并非缺货」—— 商家在**否认**缺货，语义须反转。
# 例： "it's always often out of stock unfortunately it's not like that"
RE_NEGATED_STOCK = re.compile(
    r"\b(?:it'?s\s+)?not\s+(?:like\s+that|the\s+case|true|correct)\b"
    r"|\bisn'?t\s+(?:like\s+that|the\s+case|true)\b"
    r"|\bthat'?s\s+(?:not|incorrect)\b"
    r"|\bno,?\s+(?:it'?s\s+)?not\b",
    re.I)

# 「还有货」——若同句同时出现，说明主体是有货（如 "still in stock! Premium is sold out"）
RE_STILL_IN_STOCK = re.compile(
    r"\b(?:still|remains?|are|is)\s+in\s+stock\b|\bstill\s+available\b",
    re.I)

RE_BROAD_AVAIL = re.compile(
    r"now\s+available|have\s+added|we(?:'ve| have)\s+added"
    r"|(?:plans?|servers?)\s+(?:are|is)\s+(?:still\s+)?available", re.I)


def _sentence_around(snippet: str, match_text: str) -> str:
    """取出命中所在的句子（近似）。

    以 .!? 与换行切句，找包含 ``match_text`` 的那一句；
    找不到则退回整段。用于判断该命中是否处于疑问句。
    """
    if not snippet:
        return ""
    idx = snippet.lower().find((match_text or "").lower())
    if idx < 0:
        return snippet
    # 向前找句首
    start = 0
    for i in range(idx - 1, -1, -1):
        if snippet[i] in ".!?\n":
            start = i + 1
            break
    # 向后找句尾
    end = len(snippet)
    for i in range(idx, len(snippet)):
        if snippet[i] in ".!?\n":
            end = i + 1
            break
    return snippet[start:end].strip()


def is_valid_statement(snippet: str, match_text: str) -> bool:
    """判断一次正则命中是否构成真正的库存表态。

    四类常见误判：
      · 疑问句 —— 「sold out ?」是用户在问
      · 否定句 —— 「it's always often out of stock … it's not like that」
        商家其实在**否认**，语义须反转 → 丢弃
      · 非库存对象 —— 「trial is now available」「added the test ips」
      · 促销资格 —— 「promotion ... available only for monthly billing」
    """
    sentence = _sentence_around(snippet, match_text)
    if RE_QUESTION_END.search(sentence) or RE_QUESTION_START.match(sentence):
        return False
    # 否定语境：整段在否认缺货，不能当作「售罄」证据
    if RE_NEGATED_STOCK.search(snippet) or RE_NEGATED_STOCK.search(sentence):
        return False
    if RE_ELIGIBILITY.search(snippet):
        return False

    low = snippet.lower()
    if RE_BROAD_AVAIL.search(match_text):
        if NON_STOCK_OBJECT.search(low):
            return False
        if not STOCK_OBJECT.search(low):
            return False
        # 句子主体是 promotion/offer 时不算库存
        if (re.search(r"\b(?:promotion|promo|discount|offer)\b", low)
                and not re.search(
                    r"\b(?:stock|units?|inventory|slots?|capacity)\b", low)):
            return False
    return True


def extract_stock_signals(replies: list[dict]) -> dict:
    """从回帖里抽库存信号。商家回复优先于普通用户。"""
    vendor_hits: list[dict] = []
    user_hits: list[dict] = []

    for r in replies:
        body = r.get("body") or ""
        if not body:
            continue
        is_vendor = bool(r.get("is_vendor_reply"))
        bucket = vendor_hits if is_vendor else user_hits
        # 一条回复里可能先后提到多个状态（如「已补货…现在又售罄」），
        # 因此收集**全部**命中，后续再按时间与出现顺序取最新。
        for label, rx in STOCK_PATTERNS:
            for m in rx.finditer(body):
                snippet = re.sub(
                    r"\s+", " ",
                    body[max(0, m.start() - 90): m.end() + 90]).strip()
                if not is_valid_statement(snippet, m.group(0)):
                    continue
                bucket.append({
                    "status": label,
                    "author": r.get("author"),
                    "is_vendor": is_vendor,
                    "datetime": r.get("datetime"),
                    "match": m.group(0),
                    "snippet": snippet,
                    "comment_id": r.get("comment_id"),
                    "offset": m.start(),
                })

    def _latest(hits: list[dict]) -> dict | None:
        """选出最具代表性的表态。

        两级裁决：
          1) **同一条回复内** —— 商家常说「Budget 仍有货、Premium 已售罄」，
             两个状态同时为真。此时取 PARTIAL（部分售罄），
             既不谎称全部售罄，也不谎称全部有货。
             若只出现一种状态，则取「最严格」的那个（宁可少承诺）。
          2) **不同回复之间**取时间最新的一条（最新状态覆盖旧状态）。
        """
        if not hits:
            return None

        severity = {"ENDED": 0, "SOLD_OUT": 1, "RESTOCKING": 2,
                    "PARTIAL": 3, "ON_SALE": 4}

        by_comment: dict[str, list[dict]] = {}
        for h in hits:
            by_comment.setdefault(h.get("comment_id") or "", []).append(h)

        chosen: list[dict] = []
        for cid, group in by_comment.items():
            statuses = {g["status"] for g in group}
            has_out = bool(statuses & {"SOLD_OUT", "RESTOCKING", "ENDED"})
            has_in = "ON_SALE" in statuses
            if has_out and has_in:
                # 同一条回复里既有售罄又有在售 -> 部分售罄
                rep = dict(min(group, key=lambda x: severity.get(x["status"], 9)))
                rep = dict(rep)
                rep["status"] = "PARTIAL"
                chosen.append(rep)
            else:
                chosen.append(min(group, key=lambda x: severity.get(x["status"], 9)))

        return sorted(chosen, key=lambda x: (x.get("datetime") or "",
                                             x.get("offset") or 0))[-1]

    if vendor_hits:
        latest = _latest(vendor_hits)
        status, source, evidence = latest["status"], "vendor", latest
    elif user_hits:
        latest = _latest(user_hits)
        status, source, evidence = latest["status"], "user", latest
    else:
        status = source = evidence = None

    return {
        "reply_status": status,
        "reply_source": source,
        "reply_evidence": evidence,
        "vendor_signals": vendor_hits[-5:],
        "user_signals": user_hits[-5:],
        "vendor_reply_count": sum(1 for r in replies
                                  if r.get("is_vendor_reply")),
        "reply_count": len(replies),
    }


# --------------------------------------------------------------------------
# 抓取
# --------------------------------------------------------------------------

def _cache_path(thread_id: str) -> str:
    return os.path.join(config.REPLY_CACHE_DIR, f"{thread_id}.json")


def fetch_thread_replies(
    thread_id: str,
    slug: str = "x",
    *,
    max_pages: int = 2,
    strategy: str = "latest",
    use_cache: bool = True,
    verbose: bool = False,
) -> dict:
    """抓取讨论帖回帖并抽库存信号。

    strategy:
      "latest"（默认）— 从最后一页往前抓。实测库存表态在回帖流末段，
          1 页即可覆盖多数信号，且拿到的是**最新**状态。
      "all"    — 从头顺序抓全部分页（最完整但慢，且可能拿到旧状态）。
    """
    os.makedirs(config.REPLY_CACHE_DIR, exist_ok=True)
    cache_file = _cache_path(thread_id)

    if use_cache and os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < config.REPLY_CACHE_TTL:
            try:
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

    base = f"https://lowendtalk.com/discussion/{thread_id}/{slug}"
    first = fetch(base)
    if not first:
        return {"thread_id": thread_id, "ok": False,
                "error": "first page fetch failed", "replies": [],
                "reply_count": 0, "reply_status": None}

    total_pages = find_max_page(first)
    all_replies = parse_replies(first)
    pages_fetched = [1]

    if strategy == "latest":
        # 末页 = 最新回帖 = 商家最新表态
        order = list(range(total_pages, 1, -1))[:max(1, max_pages - 1)]
    else:
        order = list(range(2, total_pages + 1))[:max(1, max_pages - 1)]

    for p in order:
        time.sleep(config.REPLY_DELAY)
        try:
            page_html = fetch(f"{base}/p{p}")
        except FetchError:
            page_html = None
        if not page_html:
            if verbose:
                print(f"    [warn] #{thread_id} p{p} 抓取失败")
            continue
        got = parse_replies(page_html)
        if got:
            all_replies.extend(got)
            pages_fetched.append(p)
            if strategy == "latest":
                # 末页已有商家表态即可提前停止，省请求
                if extract_stock_signals(all_replies).get(
                        "reply_source") == "vendor":
                    break

    # 去重 + 按时间排序
    seen, uniq = set(), []
    for r in all_replies:
        if r["comment_id"] in seen:
            continue
        seen.add(r["comment_id"])
        uniq.append(r)
    uniq.sort(key=lambda r: (r.get("datetime") or "",
                             r.get("comment_id") or ""))

    result = {
        "thread_id": thread_id,
        "ok": True,
        "strategy": strategy,
        "pages": len(pages_fetched),
        "pages_fetched": sorted(pages_fetched),
        "total_pages": total_pages,
        "reply_count": len(uniq),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **extract_stock_signals(uniq),
        "replies": uniq,
    }

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result
