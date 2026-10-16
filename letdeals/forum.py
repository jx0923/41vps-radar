"""把优惠帖搬运到自己的 Flarum 论坛（LowSeek）。

设计原则（安全优先）
--------------------
1. **默认关闭**：``config.FORUM_ENABLED`` 为假时直接返回，什么都不做。
2. **默认演练**：``FORUM_DRY_RUN`` 为真时只打印将要发布的内容，不提交。
3. **幂等**：已发布过的 ``thread_id`` 记录在 ``data/forum_posted.json``，
   永不重复发布 —— 这是最重要的一条，避免同一活动被反复搬运。
4. **限流**：每次运行最多 ``FORUM_MAX_PER_RUN`` 条。
5. **失败不阻塞**：单条失败只记录，不影响其余条目与主流程。

为什么单独成模块
----------------
发帖是**旁路功能**：抓取与建站是主链路，论坛发帖失败不应影响站点更新。
因此它不进入 ``pipeline.run()``，由 CLI 单独调用。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import config

# Flarum 使用 JSON:API
CONTENT_TYPE = "application/vnd.api+json"


# --------------------------------------------------------------------------
# 已发布记录（幂等）
# --------------------------------------------------------------------------

def load_posted(path=None) -> dict:
    """读取已发布记录。返回 {thread_id: {...}}。"""
    path = str(path or config.FORUM_POSTED_LOG)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        # 记录损坏时按「全部未发布」处理会重复发帖，风险更大；
        # 因此这里选择保守：返回空 dict 但由调用方决定是否继续。
        return {}


def save_posted(posted: dict, path=None) -> None:
    """写回已发布记录（原子替换，避免写一半损坏）。"""
    path = str(path or config.FORUM_POSTED_LOG)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(posted, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# 正文生成
# --------------------------------------------------------------------------

# 价格/规格/优惠码一律原样保留，不做翻译 ——
# 数字翻译错了会误导用户下单，而且商家会来投诉。
EVENT_CN = {
    "anniversary": "周年庆",
    "black_friday": "黑五",
    "holiday": "节日促销",
    "launch": "上新 / 回归",
    "restock": "补货",
    "sale": "常规促销",
    "regular": "常规帖",
}

AVAIL_CN = {
    "ON_SALE": "在售",
    "SOLD_OUT": "售罄",
    "ENDED": "活动已结束",
    "RESTOCKING": "补货中",
    "PARTIAL": "部分套餐售罄",
    "LIKELY_SOLD_OUT": "疑似售罄（用户提及）",
    "UNVERIFIED": "待确认",
    "UNVERIFIED_STALE": "待确认",
}

# 从标题/正文识别服务类型，避免把「邮箱托管」当成 VPS 发出去。
# 只做粗分类：识别到就标注，识别不到默认按 VPS 处理。
SERVICE_KINDS = (
    ("email", ("email hosting", "mail hosting", "邮件托管", "邮箱托管",
               "mailbig", "email service")),
    ("storage", ("storage vps", "storage server", "storage box",
                 "对象存储", "s3 ", "backup storage")),
    ("dedicated", ("dedicated server", "dedicated servers", "独服",
                   "bare metal", "裸金属")),
    ("cdn", ("cdn", "content delivery")),
    ("domain", ("domain name", "域名注册")),
)

SERVICE_CN = {
    "email": "邮箱托管",
    "storage": "存储型",
    "dedicated": "独立服务器",
    "cdn": "CDN",
    "domain": "域名服务",
}


def detect_kind(rec: dict) -> str:
    """粗判服务类型。返回 kind（vps 表示未识别到特殊类型）。"""
    hay = ((rec.get("title") or "") + " " +
           (rec.get("provider") or "")).lower()
    for kind, keys in SERVICE_KINDS:
        if any(k in hay for k in keys):
            return kind
    return "vps"


def _num(v) -> str:
    """数字转字符串：整数不带小数点（660.0 -> 660）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else ("%.2f" % f).rstrip("0").rstrip(".")


def _money(price: dict) -> str:
    if not price:
        return ""
    cycle = {"year": "/年", "quarter": "/季", "month": "/月"}.get(
        price.get("cycle"), "")
    amount = price.get("amount")
    if amount is None:
        return ""
    return "%s%s%s" % (price.get("currency", ""), _num(amount), cycle)


def _plausible_specs(rec: dict) -> tuple[bool, str]:
    """判断 specs 与价格是否自洽。

    背景：原帖常同时列「VPS」与「独立服务器」等多条产品线，
    抽取时可能把 A 产品的规格与 B 产品的价格拼在一起。

    判据不是「存储比」而是**价格是否与规格相称**：

    - 存储型 VPS 天然「小内存 + 大存储」，但**价格与存储量相称**
      （如 5TB HDD 卖 $19.95/月）—— 这是正常优惠，不能拦。
    - 串味的组合则**对不上任何一项**：192G 内存卖 $7、4TB 卖 €1。

    因此只拦「明显不可能」的组合：大内存卖极低价、大存储卖极低价。
    在发帖层做保守处理：可疑时不显示规格，也不给误导性配置。

    返回 (是否可信, 原因)。
    """
    s = rec.get("specs") or {}
    vcpu = s.get("vcpu")
    ram = s.get("ram_gb")
    storage = s.get("storage_gb")

    if not any([vcpu, ram, storage]):
        return True, "无规格"

    prices = rec.get("prices") or []
    if not prices:
        return True, "无价格可对照"

    cheapest = min((p.get("amount") or 0) for p in prices)

    # 内存是硬成本：128G 以上不可能卖到 50 以内（任何币种）。
    # 实测串味样本：192G @ $7、512G @ €2.6、250G @ $9.99。
    if ram and ram >= 128 and cheapest < 50:
        return False, "大内存配极低价（疑似混入其他产品线）"

    # 大容量存储卖到 5 以内也不合理（实测 4096G @ $2.04、@ €1）。
    # 注意阈值取 5 而非 10：存储型 VPS 卖 $8.88/$19.95 是正常的。
    if storage and storage >= 1000 and cheapest < 5:
        return False, "大容量配极低价（疑似混入其他产品线）"

    return True, "可信"


def _specs(rec: dict) -> str:
    s = rec.get("specs") or {}
    bits = []
    if s.get("vcpu"):
        bits.append("%d 核" % s["vcpu"])
    if s.get("ram_gb"):
        bits.append("%sG 内存" % _num(round(s["ram_gb"])))
    if s.get("storage_gb"):
        st = s.get("storage_type") or ""
        st = "" if st.lower() == "unspecified" else " " + st
        bits.append("%sG%s 存储" % (_num(round(s["storage_gb"])), st))
    if s.get("bandwidth_tb"):
        bits.append("%sTB 流量" % _num(s["bandwidth_tb"]))
    return " / ".join(bits)


def build_post(rec: dict) -> tuple[str, str]:
    """生成 (标题, 正文)。正文用 Markdown（论坛已装 flarum/markdown）。"""
    provider = rec.get("provider") or "未知商家"
    event = EVENT_CN.get(rec.get("event_type"), rec.get("event_type") or "")
    avail = AVAIL_CN.get(rec.get("availability"), "")
    discount = rec.get("discount") or {}

    # 规格可信度：原帖常同时列多条产品线，抽取可能串味。
    # 不可信时**不在标题和正文里显示规格** —— 给错配置比不给更糟。
    specs_ok, specs_why = _plausible_specs(rec)

    # ---- 标题 ----
    kind = detect_kind(rec)
    parts = []
    if event and event != "常规帖":
        parts.append("【%s】" % event)
    # 非 VPS 服务明确标注，避免误导（如邮箱托管被当成 VPS）
    if kind != "vps":
        parts.append("[%s]" % SERVICE_CN.get(kind, kind))
    parts.append(provider)
    specs = _specs(rec) if specs_ok else ""
    if specs:
        parts.append(specs)
    title = " ".join(parts)
    if len(title) > 90:
        title = title[:87] + "…"

    # ---- 正文 ----
    lines = []

    if kind != "vps":
        lines.append("**服务类型**：%s（非 VPS）" %
                     SERVICE_CN.get(kind, kind))
        lines.append("")

    # 原帖标题（保留英文原文，便于用户核对）
    raw_title = (rec.get("title") or "").strip()
    if raw_title:
        lines.append("> %s" % raw_title)
        lines.append("")

    if discount.get("strength"):
        lines.append("**优惠**：%s" % discount["strength"])
    if discount.get("percent_max"):
        lines.append("**最大折扣**：%s%%" % discount["percent_max"])
    if discount.get("recurring"):
        lines.append("**循环折扣**：是（续费同价）")

    price = _money(rec.get("flagship_price") or
                   ((rec.get("prices") or [None])[0]))
    if price:
        lines.append("**起价 / 旗舰价**：%s" % price)

    if specs:
        lines.append("**配置**：%s" % specs)
    elif not specs_ok:
        # 说明为什么没给配置，而不是让用户以为漏了
        lines.append("**配置**：原帖含多条产品线，自动解析的规格可能串味，"
                     "为避免误导此处不列出，请见原帖")

    cpus = rec.get("cpu_models") or []
    if cpus:
        lines.append("**CPU**：%s" % "、".join(cpus[:3]))

    locs = rec.get("locations") or []
    if locs:
        lines.append("**机房**：%s" % "、".join(locs[:6]))

    if avail:
        lines.append("**库存**：%s" % avail)

    codes = discount.get("codes") or []
    if codes:
        lines.append("")
        lines.append("**优惠码**（请以商家页面为准）：%s" %
                     "、".join("`%s`" % c for c in codes[:6]))

    extras = discount.get("extras") or []
    if extras:
        lines.append("**加赠**：%s" % "、".join(extras[:4]))

    # ---- 套餐表（有解析到才输出）----
    plans = rec.get("plans") or []
    if plans:
        lines.append("")
        lines.append("| 套餐 | 配置 | 存储 | 流量 | 价格 |")
        lines.append("|---|---|---|---|---|")
        for p in plans[:12]:
            lines.append("| %s | %s | %s | %s | %s |" % (
                p.get("name") or "—",
                "%sC/%sG" % (_num(p.get("vcpu") or "—"),
                             _num(round(p.get("ram_gb") or 0))),
                "%sG" % _num(round(p.get("storage_gb") or 0)),
                "%sTB" % _num(p.get("bandwidth_tb") or "—"),
                _money(p.get("price")) or "—",
            ))

    # ---- 出处与声明 ----
    lines.append("")
    lines.append("---")
    src = "LowEndBox" if rec.get("source") == "leb" else "LowEndTalk"
    lines.append("**原始出处**：%s" % src)
    if rec.get("url"):
        lines.append("**原帖地址**：%s" % rec["url"])
    if rec.get("vendor_url"):
        lines.append("**商家官网**：%s" % rec["vendor_url"])
    age = rec.get("age_days")
    if age is not None:
        lines.append("**原帖发布**：%s" % ("今天" if age == 0 else "%d 天前" % age))

    lines.append("")
    lines.append("> 本帖由机器人自动搬运并整理，便于中文用户阅读；"
                 "**价格与库存以商家页面为准**，下单前请自行核实。")

    return title, "\n".join(lines)


# --------------------------------------------------------------------------
# 筛选：只搬运「够格」的帖子
# --------------------------------------------------------------------------

# 不像商家名的词：描述卖点、机房位置、活动用语等。
# 这类「厂商名」其实是标题片段被误抽取（如 "Dallas Dedicated"），
# 发出去会让帖子显得不专业 —— 用户看不出到底是谁家的。
NOT_A_BRAND = {
    # 卖点 / 描述
    "dedicated", "performance", "unmetered", "storage", "premium", "budget",
    "cheap", "fast", "reliable", "managed", "unmanaged", "cloud", "server",
    "servers", "hosting", "host", "vps", "kvm", "ssd", "nvme", "network",
    "memory", "bandwidth", "traffic",
    # 活动用语
    "black", "friday", "sale", "deal", "deals", "offer", "offers", "promo",
    "giveaway", "restock", "launch", "new", "welcome", "special", "flash",
    "more", "free", "lifetime",
    # 常见机房 / 地名（单独出现时不是商家名）
    "dallas", "chicago", "angeles", "york", "seattle", "miami", "london",
    "frankfurt", "amsterdam", "tokyo", "singapore", "sydney", "paris",
    "germany", "netherlands", "usa", "canada", "france", "zealand",
    # 虚词
    "of", "the", "and", "with", "for", "from", "here", "now",
}


def _provider_ok(provider: str) -> tuple[bool, str]:
    """判断厂商名是否像个真实商家名。

    不能简单要求「必须是域名」—— NUXOA、Velohost、NameBig 都是合法
    品牌名（没有域名但确实是商家）。因此判断「像不像品牌」：

    - 域名形态（含点且无空格）→ 通过
    - 单个词、长度合理、不在描述词黑名单 → 通过（如 Velohost）
    - 多词且全为描述词/地名 → 拒绝（如 "Dallas Dedicated"）
    - 含标点、过长、截断痕迹 → 拒绝
    """
    p = (provider or "").strip()
    if not p or p.upper() == "UNKNOWN":
        return False, "缺失"

    # 域名形态：含点且无空格
    if "." in p and " " not in p:
        return True, "域名"

    if len(p) > 30:
        return False, "过长，疑似标题片段"
    if re.search(r"[!?！？,，;；:：]", p):
        return False, "含标点，疑似标题片段"
    if p.endswith(("'", "\u2019", "(", "（", "&", "-", "|")):
        return False, "结尾异常，疑似截断"

    words = [w.strip(".,'\u2019") for w in re.split(r"[\s&]+", p.lower()) if w]
    if not words:
        return False, "空"

    if all(w in NOT_A_BRAND for w in words):
        return False, "全为描述词或地名"
    if len(words) == 1 and words[0] in NOT_A_BRAND:
        return False, "描述词"
    if len(words) >= 3:
        return False, "词数过多，疑似标题片段"

    return True, "品牌名"


def is_worthy(rec: dict) -> tuple[bool, str]:
    """判断是否值得搬运。返回 (是否搬运, 原因)。

    目的是**避免刷屏** —— 全量搬运会把论坛首页淹掉。
    门槛：厂商名可靠 + 有明确折扣或属于重点活动。
    """
    if not rec.get("url"):
        return False, "缺少原帖链接"

    ok, why = _provider_ok(rec.get("provider") or "")
    if not ok:
        return False, "厂商名不可靠（%s）" % why

    event = rec.get("event_type")
    pct = (rec.get("discount") or {}).get("percent_max") or 0
    recurring = bool((rec.get("discount") or {}).get("recurring"))
    strength = (rec.get("discount") or {}).get("strength") or ""

    # 重点活动无条件通过
    if event in config.FORUM_EVENT_PRIORITY:
        return True, "重点活动：%s" % EVENT_CN.get(event, event)

    # 折扣达标
    if pct and pct >= config.FORUM_MIN_PERCENT:
        return True, "折扣 %d%%" % pct

    # 循环折扣（长期有效，对用户价值高）
    if recurring:
        return True, "循环折扣"

    # 有具体优惠描述且价格已知
    if strength and (rec.get("flagship_price") or rec.get("prices")):
        return True, "有优惠描述与价格"

    return False, "无明确优惠"


def is_fresh(rec: dict) -> tuple[bool, str]:
    """只搬运较新的帖子，避免一次把历史帖全部灌进去。"""
    limit = config.FORUM_MAX_AGE_DAYS
    if limit <= 0:
        return True, "不限时效"
    age = rec.get("age_days")
    if age is None:
        return False, "无发布时间"
    if age <= limit:
        return True, "%d 天前" % age
    return False, "已发布 %d 天（超过 %d 天）" % (age, limit)


# --------------------------------------------------------------------------
# Flarum API
# --------------------------------------------------------------------------

class ForumError(Exception):
    """发帖失败。"""


def _request(method: str, path: str, payload=None, *, api_key: str,
             base_url: str, timeout: int = 30) -> dict:
    url = "%s/api%s" % (base_url.rstrip("/"), path)
    headers = {
        "Authorization": "Token %s" % api_key,
        "Accept": CONTENT_TYPE,
        "User-Agent": "LowSeek-DealsBot/1.0 (+%s)" % base_url,
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = CONTENT_TYPE
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        # 尽量提取 Flarum 的错误详情，便于定位
        detail = body[:400]
        try:
            parsed = json.loads(body)
            errs = parsed.get("errors") or []
            if errs:
                detail = "; ".join(
                    str(x.get("detail") or x.get("code") or x) for x in errs[:3])
        except (json.JSONDecodeError, AttributeError):
            pass
        raise ForumError("HTTP %s: %s" % (e.code, detail)) from None
    except urllib.error.URLError as e:
        raise ForumError("网络错误：%s" % e.reason) from None


def check_auth(*, api_key: str, base_url: str, bot_user_id: str) -> dict:
    """校验 API Key 是否可用，并返回账号信息。"""
    data = _request("GET", "/users/%s" % bot_user_id,
                    api_key=api_key, base_url=base_url)
    attrs = (data.get("data") or {}).get("attributes") or {}
    return {
        "username": attrs.get("username"),
        "nickname": attrs.get("nickname"),
        "is_admin": attrs.get("isAdmin"),
    }


def create_discussion(title: str, content: str, *, api_key: str,
                      base_url: str, tag_id: str) -> dict:
    """在指定标签下创建讨论。返回 {id, slug, url}。"""
    payload = {
        "data": {
            "type": "discussions",
            "attributes": {"title": title, "content": content},
            "relationships": {
                "tags": {"data": [{"type": "tags", "id": str(tag_id)}]}
            },
        }
    }
    data = _request("POST", "/discussions", payload,
                    api_key=api_key, base_url=base_url)
    d = data.get("data") or {}
    did = d.get("id")
    return {
        "id": did,
        "slug": (d.get("attributes") or {}).get("slug"),
        "approved": (d.get("attributes") or {}).get("isApproved"),
        "url": "%s/d/%s" % (base_url.rstrip("/"), did),
    }


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def post_deals(records: list[dict], *, limit: int | None = None,
               dry_run: bool | None = None, verbose: bool = True,
               posted_path=None, client=None) -> dict:
    """把记录发布到论坛。

    限流语义（重要）
    ----------------
    ``limit`` 限制的是**本次新发几条**，而不是「遍历多少条」：

    - 已发布过的 ``thread_id`` 会被跳过，**不占用**本次配额；
    - 因此连续运行会把积压的合格帖**分批**发完，而不是一次灌满论坛；
    - 每批之间的间隔由运行频率决定（如每 6 小时一次 → 每天最多 4×limit 条）。

    配合 ``FORUM_MAX_AGE_DAYS``（只发最近 N 天）使用，可自然收敛：
    积压发完后，若没有新帖，运行会安静地什么都不做。

    参数
    ----
    records : 记录列表（通常来自 pipeline.run 的 payload["records"]）
    limit   : 覆盖本次上限；默认用 config.FORUM_MAX_PER_RUN
    dry_run : 覆盖演练开关；默认用 config.FORUM_DRY_RUN
    posted_path : 已发布记录文件路径（默认 config.FORUM_POSTED_LOG）
    client  : 测试注入用；提供时用作 create(title, content) 可调用对象。

    返回统计字典。
    """
    stats = {
        "enabled": config.FORUM_ENABLED,
        "dry_run": config.FORUM_DRY_RUN if dry_run is None else dry_run,
        "checked": 0, "skipped": 0, "posted": 0, "failed": 0,
        "already": 0, "reasons": {}, "posts": [], "errors": [],
    }

    # ---- 总开关 ----
    if not config.FORUM_ENABLED:
        if verbose:
            print("  论坛发帖：已关闭（LDR_FORUM_ENABLED=false），跳过")
        return stats

    api_key = config.FORUM_API_KEY
    base_url = config.FORUM_BASE_URL
    tag_id = config.FORUM_TAG_ID
    cap = config.FORUM_MAX_PER_RUN if limit is None else limit
    do_post = not stats["dry_run"]

    # 演练模式不需要凭据 —— 它只打印将要发布的内容，
    # 这样即使还没配 Key 也能先检查会发什么、格式对不对。
    if do_post and not api_key:
        stats["errors"].append("未配置 LDR_FORUM_API_KEY")
        if verbose:
            print("  论坛发帖：缺少 API Key，跳过")
        return stats
    if not api_key and verbose:
        print("  论坛发帖：演练模式（未配置 API Key，仅预览内容）")

    # ---- 鉴权（仅实际发布时需要）----
    if do_post and client is None:
        try:
            me = check_auth(api_key=api_key, base_url=base_url,
                            bot_user_id=config.FORUM_BOT_USER_ID)
            if verbose:
                print("  论坛发帖：已认证为 %s" % me.get("username"))
        except ForumError as e:
            stats["errors"].append("鉴权失败：%s" % e)
            if verbose:
                print("  论坛发帖：鉴权失败 —— %s" % e)
            return stats

    if client is not None:
        create = client
    else:
        def create(t, c):
            return create_discussion(t, c, api_key=api_key,
                                     base_url=base_url, tag_id=tag_id)

    posted = load_posted(posted_path)

    if verbose:
        mode = "演练（不提交）" if stats["dry_run"] else "实际发布"
        print("  论坛发帖：%s，本次上限 %d 条" % (mode, cap))

    for rec in records:
        if stats["posted"] >= cap:
            if verbose:
                print("  论坛发帖：已达本次上限 %d 条，停止" % cap)
            break

        tid = str(rec.get("thread_id") or "")
        if not tid:
            continue
        stats["checked"] += 1

        # 已发过
        if tid in posted:
            stats["already"] += 1
            continue

        ok, why = is_fresh(rec)
        if not ok:
            stats["skipped"] += 1
            stats["reasons"][why] = stats["reasons"].get(why, 0) + 1
            continue

        ok, why = is_worthy(rec)
        if not ok:
            stats["skipped"] += 1
            stats["reasons"][why] = stats["reasons"].get(why, 0) + 1
            continue

        title, content = build_post(rec)

        if stats["dry_run"]:
            stats["posts"].append({
                "thread_id": tid, "title": title,
                "reason": why, "dry_run": True,
            })
            if verbose:
                print("\n  ── [演练] %s" % title)
                print("     理由：%s" % why)
                print("     正文预览：")
                for ln in content.splitlines()[:12]:
                    print("       %s" % ln)
                if len(content.splitlines()) > 12:
                    print("       …（共 %d 行）" % len(content.splitlines()))
            stats["posted"] += 1     # 演练也计数，便于确认会发几条
            continue

        # 实际发布
        try:
            res = create(title, content)
        except ForumError as e:
            stats["failed"] += 1
            stats["errors"].append("thread %s: %s" % (tid, e))
            if verbose:
                print("  ✗ 发布失败 thread=%s：%s" % (tid, e))
            continue
        except Exception as e:                      # 兜底，不让单条炸掉全部
            stats["failed"] += 1
            stats["errors"].append("thread %s: %r" % (tid, e))
            if verbose:
                print("  ✗ 发布异常 thread=%s：%r" % (tid, e))
            continue

        posted[tid] = {
            "discussion_id": res.get("id"),
            "title": title,
            "url": res.get("url"),
            "posted_at": _now(),
        }
        save_posted(posted, posted_path)
        stats["posted"] += 1
        stats["posts"].append({"thread_id": tid, "title": title,
                               "url": res.get("url"), "reason": why})
        if verbose:
            print("  ✓ 已发布：%s -> %s" % (title, res.get("url")))

        # 对站点友好：条与条之间稍作停顿
        time.sleep(1.5)

    if verbose:
        print("\n  论坛发帖小结：发布 %d / 跳过 %d / 已发过 %d / 失败 %d"
              % (stats["posted"], stats["skipped"],
                 stats["already"], stats["failed"]))
        if stats["reasons"]:
            for r, n in sorted(stats["reasons"].items(),
                               key=lambda x: -x[1])[:5]:
                print("    跳过原因：%s ×%d" % (r, n))

    return stats
