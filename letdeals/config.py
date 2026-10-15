"""运行配置。

所有可调项集中在此，并支持环境变量覆盖 —— 便于在 GitHub Actions
和自己的服务器上使用不同配置而无需改代码。
"""

from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------

# 项目根目录（本文件在 <root>/letdeals/config.py）
ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(_env("LDR_DATA_DIR", str(ROOT / "data")))
SITE_DIR = Path(_env("LDR_SITE_DIR", str(ROOT / "site")))
REPLY_CACHE_DIR = DATA_DIR / "replies"

DEALS_JSON = DATA_DIR / "deals.json"
DEALS_MD = DATA_DIR / "deals.md"
FEED_CACHE = DATA_DIR / "feed.xml"


# --------------------------------------------------------------------------
# 站点 / 域名
# --------------------------------------------------------------------------
# 部署到自己域名时，改这几个环境变量即可，无需改代码。

SITE_TITLE = _env("LDR_SITE_TITLE", "VPS 活动雷达")
SITE_DESC = _env(
    "LDR_SITE_DESC",
    "自动汇总 LowEndTalk / LowEndBox 的 VPS 优惠活动，"
    "标注折扣力度、循环折扣与库存状态。",
)
# 例：https://deals.example.com  （末尾不要带 /）
SITE_URL = _env("LDR_SITE_URL", "").rstrip("/")
SITE_FOOTER = _env("LDR_SITE_FOOTER", "")


# --------------------------------------------------------------------------
# 数据源
# --------------------------------------------------------------------------

LET_FEED_URL = _env(
    "LDR_LET_FEED",
    "https://lowendtalk.com/categories/offers/feed.rss",
)
LEB_FEED_URL = _env("LDR_LEB_FEED", "https://lowendbox.com/feed/")

USER_AGENT = _env(
    "LDR_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)

HTTP_TIMEOUT = _env_int("LDR_HTTP_TIMEOUT", 30)
HTTP_RETRIES = _env_int("LDR_HTTP_RETRIES", 3)
HTTP_BACKOFF = 1.6          # 重试退避基数（秒）

# 抓取回帖时的页间延迟，对站点友好
REPLY_DELAY = 0.8
REPLY_CACHE_TTL = 3600      # 回帖缓存有效期（秒）
REPLY_MAX_PAGES_HARD = 25   # 硬上限，防异常帖拖爆


# --------------------------------------------------------------------------
# 判定阈值
# --------------------------------------------------------------------------

NEW_DAYS = 7        # < 7 天视为新帖
ACTIVE_DAYS = 30    # <= 30 天视为活跃

# 跨币种排序用的近似汇率（仅用于排序，不用于展示成交价）
FX_TO_EUR = {"€": 1.00, "$": 0.92, "£": 1.17}
FX_NOTE = "跨币种排序按近似汇率折算（€1.00 / $0.92 / £1.17），仅供参考"

CYCLE_TO_YEAR = {"year": 1.0, "quarter": 4.0, "month": 12.0}
