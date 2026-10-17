"""联盟推广链接（Affiliate）映射。

用途
----
把厂商域名映射到**你自己的推广链接**。用户通过该链接下单，你拿佣金。

设计原则
--------
1. **默认空表**：不配置就完全不影响现有行为（用原始链接）。
2. **域名级映射**：按厂商域名匹配，与帖子内容无关，规则简单可预测。
3. **不猜参数**：每家的 AFF 参数格式不同，必须显式给出完整链接，
   不做 `?aff=` 这类拼接猜测 —— 拼错会导致佣金丢失且难以发现。
4. **可灰度**：填一家生效一家，其余继续走原链接。

配置方式
--------
环境变量 ``LDR_AFFILIATES`` 用 JSON 给出，或直接改下方 ``DEFAULTS``：

    LDR_AFFILIATES='{"racknerd.com": "https://my.racknerd.com/aff.php?aff=123"}'

键是**域名**（可带或不带 www），值是**完整的推广链接**。

合规提醒
--------
多数厂商禁止：自己下单赚自己佣金、用脚本批量注册、投竞品品牌词广告。
启用前请确认各家条款。另外建议在站点上**明示**「部分链接含推广佣金」——
佣金由商家从利润中出，不影响用户支付价格。
"""

from __future__ import annotations

import json
import os
import re

# 域名 -> 完整推广链接。
# 例：'racknerd.com': 'https://my.racknerd.com/aff.php?aff=123'
DEFAULTS: dict[str, str] = {}


def _load() -> dict[str, str]:
    """读取映射：环境变量优先，其次模块内 DEFAULTS。

    环境变量解析失败时**静默回退到 DEFAULTS** —— 配置写错不应导致
    抓取流程失败，最坏情况只是没有推广链接。
    """
    raw = os.getenv("LDR_AFFILIATES", "").strip()
    if not raw:
        return dict(DEFAULTS)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return dict(DEFAULTS)
    if not isinstance(data, dict):
        return dict(DEFAULTS)
    out = dict(DEFAULTS)
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str) and v.startswith("http"):
            out[k.strip().lower()] = v.strip()
    return out


def _domain_of(url: str) -> str:
    """从 URL 取可注册域（www. 视为同一家）。"""
    m = re.match(r"https?://(?:www\.)?([a-z0-9][a-z0-9\-\.]*)", url or "",
                 re.I)
    return m.group(1).lower().rstrip(".") if m else ""


def rewrite(vendor_url: str | None,
            mapping: dict[str, str] | None = None) -> str | None:
    """如果该厂商配置了推广链接，替换之；否则原样返回。

    匹配顺序：
      1) 完整域名精确匹配（a.b.com）
      2) 去掉子域后匹配（b.com）—— 兼容 my.xxx.com、billing.xxx.com
    """
    if not vendor_url:
        return vendor_url
    table = _load() if mapping is None else mapping
    if not table:
        return vendor_url

    dom = _domain_of(vendor_url)
    if not dom:
        return vendor_url

    # 精确匹配
    if dom in table:
        return table[dom]

    # 去掉子域：a.b.com -> b.com
    parts = dom.split(".")
    for i in range(1, len(parts) - 1):
        cand = ".".join(parts[i:])
        if cand in table:
            return table[cand]

    return vendor_url


def summary(mapping: dict[str, str] | None = None) -> str:
    """返回一行人类可读的配置摘要，便于启动日志确认。"""
    table = _load() if mapping is None else mapping
    if not table:
        return "未配置推广链接（使用原始链接）"
    return "已配置 %d 家厂商的推广链接：%s" % (
        len(table), "、".join(sorted(table)))
