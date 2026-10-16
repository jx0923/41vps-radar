"""数据源：LowEndTalk Offers 版块 + LowEndBox。

两者都是标准 RSS，但结构差异需要分别适配：

  LET  —  Vanilla 论坛，``<guid>`` 形如 ``221713@/discussions``（可提 thread_id），
         作者在 ``dc:creator``，正文是 HTML 表格（套餐表）。
  LEB  —  WordPress 博客，正文在 ``content:encoded``（更完整），
         作者在 ``dc:creator``，且**无需抓回帖**（博客无讨论串）。

LET 是全量优惠帖（含非优惠闲聊），LEB 是编辑精选，单帖信息密度更高，
两者合起来覆盖面更好。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from . import config
from .http import fetch
from .textutil import strip_html, strip_md_markers

DC_CREATOR = "{http://purl.org/dc/elements/1.1/}creator"
CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"

RE_URL_SLUG = re.compile(r"/([^/]+)/?$")

# LEB 的文章分类（实测）：这些分类不是「优惠」
LEB_NON_DEAL_CATEGORIES = {
    "editorial & news", "editorial", "news", "giveaways",
    "tutorials", "tutorial", "interview", "interviews",
    "videos", "reviews", "review",
}
# 真优惠的分类
LEB_DEAL_CATEGORIES = {
    "low end virtual", "dedicated servers", "shared hosting",
    "reseller hosting", "special offers", "seedbox offers",
    "community offers", "vpn", "virtual servers", "storage",
}


def _text(item: ET.Element, *tags: str) -> str:
    for tag in tags:
        el = item.find(tag)
        if el is not None and el.text:
            return el.text
    return ""


def _slug_from_link(link: str) -> str:
    m = RE_URL_SLUG.search(link.rstrip("/"))
    return m.group(1) if m else "x"


def parse_let_feed(xml_text: str) -> list[dict]:
    """解析 LET Offers RSS。"""
    root = ET.fromstring(xml_text)
    out = []
    for it in root.iter("item"):
        guid = _text(it, "guid")
        thread_id = guid.split("@")[0].strip() if guid else ""
        link = _text(it, "link").strip()
        if not thread_id:
            # 从链接兜底提取
            m = re.search(r"/discussion/(\d+)", link)
            thread_id = m.group(1) if m else ""
        out.append({
            "thread_id": thread_id,
            "source": "let",
            "slug": _slug_from_link(link),
            "title": strip_md_markers(_text(it, "title")).strip(),
            "link": link,
            "pubDate": _text(it, "pubDate").strip(),
            "author": _text(it, DC_CREATOR).strip(),
            "description": _text(it, "description"),
        })
    return out


# 明显的非优惠分类（抽奖、教程、访谈等，基本不可能是优惠）
LEB_HARD_EXCLUDE = {
    "giveaways", "tutorials", "tutorial", "interview", "interviews",
    "videos", "reviews", "review",
}
# 软排除分类：偏新闻，但**若正文含明确价格则可保留**
LEB_SOFT_EXCLUDE = {"editorial & news", "editorial", "news"}

# 正文里出现这些，说明是正经报价（而非新闻评论）
RE_DEAL_SIGNAL = re.compile(
    r"\d+\s*(?:GB|TB)\s*(?:RAM|SSD|NVMe|HDD|storage|disk|bandwidth|traffic)"
    r"|\d+\s*(?:vCPU|vCores?|Cores?)\b", re.I)

# 软排除分类的放行门槛：正文至少要有这么多次规格描述。
# 实测真优惠普遍 >= 4 次，新闻多为 0 次（详见 tools/analyze_leb.py）。
LEB_SOFT_MIN_SPECS = 2


def parse_leb_feed(xml_text: str, *, deals_only: bool = True) -> list[dict]:
    """解析 LowEndBox RSS（WordPress）。

    LEB 无讨论串，因此不抓回帖；thread_id 用链接 slug 代替。

    deals_only 时按 ``<category>`` + **正文优惠信号**双重判定：
      · Giveaways/Tutorials 等硬排除
      · Editorial & News 属软排除 —— 但若正文含明确报价（价格+规格）
        则保留，因为 LEB 有时把优惠也归到这类
    纯靠分类过滤会误杀真优惠，纯靠关键词过滤会混入新闻，故取交集判定。
    """
    root = ET.fromstring(xml_text)
    out = []
    for it in root.iter("item"):
        link = _text(it, "link").strip()
        cats = [(c.text or "").strip() for c in it.findall("category")]
        cat_lower = {c.lower() for c in cats}

        # 优先用 content:encoded（含完整正文），退回 description
        body = _text(it, CONTENT_ENCODED) or _text(it, "description")

        if deals_only:
            if cat_lower & LEB_HARD_EXCLUDE:
                continue
            if cat_lower & LEB_SOFT_EXCLUDE:
                # 软排除分类：要求正文有足够多的规格描述才放行。
                # 实测新闻类文章的价格数字多、规格描述少（多为 0），
                # 真优惠则普遍有 4 次以上规格描述。
                text = strip_html(body)[:6000]
                if len(RE_DEAL_SIGNAL.findall(text)) < LEB_SOFT_MIN_SPECS:
                    continue

        slug = _slug_from_link(link)
        out.append({
            "thread_id": f"leb-{slug}",
            "source": "leb",
            "slug": slug,
            "title": strip_md_markers(_text(it, "title")).strip(),
            "link": link,
            "pubDate": _text(it, "pubDate").strip(),
            "author": _text(it, DC_CREATOR).strip(),
            "description": body,
            "categories": cats,
        })
    return out


# --------------------------------------------------------------------------
# 抓取入口
# --------------------------------------------------------------------------

SOURCES = {
    "let": {
        "url": config.LET_FEED_URL,
        "parser": parse_let_feed,
        "cache": "feed_let.xml",
        "label": "LowEndTalk Offers",
    },
    "leb": {
        "url": config.LEB_FEED_URL,
        "parser": parse_leb_feed,
        "cache": "feed_leb.xml",
        "label": "LowEndBox",
    },
}


def fetch_source(name: str, *, offline: str | None = None,
                 verbose: bool = True) -> list[dict]:
    """抓取并解析一个数据源。

    offline 指定本地 XML 时直接读文件（便于离线重跑与测试）。
    """
    spec = SOURCES.get(name)
    if not spec:
        raise ValueError(f"unknown source: {name}")

    if offline:
        try:
            with open(offline, "r", encoding="utf-8", errors="replace") as f:
                xml_text = f.read()
        except OSError as e:
            if verbose:
                print(f"  !! 读取 {offline} 失败: {e}")
            return []
        if verbose:
            print(f"  [{spec['label']}] 读取本地 {offline} "
                  f"({len(xml_text):,} 字节)")
    else:
        if verbose:
            print(f"  [{spec['label']}] 抓取 {spec['url']} ...")
        xml_text = fetch(spec["url"], accept=(
            "application/rss+xml, application/xml, text/xml, */*"))
        if xml_text is None:
            if verbose:
                print(f"  !! {spec['label']} 返回空内容，跳过")
            return []
        # 缓存供离线重跑
        import os
        os.makedirs(config.DATA_DIR, exist_ok=True)
        try:
            with open(config.DATA_DIR / spec["cache"], "w",
                      encoding="utf-8") as f:
                f.write(xml_text)
        except OSError:
            pass
        if verbose:
            print(f"    成功, {len(xml_text):,} 字节")

    try:
        items = spec["parser"](xml_text)
    except ET.ParseError as e:
        if verbose:
            print(f"  !! {spec['label']} XML 解析失败: {e}")
        return []

    if verbose:
        print(f"    解析到 {len(items)} 条")
    return items
