"""带重试与退避的 HTTP 抓取。

比原型的裸 urlopen 多了：
  · 自动重试（网络抖动 / 5xx / Cloudflare 偶发 403）
  · 指数退避，避免被当成攻击
  · gzip 解压
  · 明确区分「永久失败(404)」和「可重试失败」
"""

from __future__ import annotations

import gzip
import time
import urllib.error
import urllib.request

from . import config

# 这些状态码重试无意义
PERMANENT = {400, 401, 404, 410, 451}


class FetchError(Exception):
    """抓取失败（已耗尽重试）。"""

    def __init__(self, url: str, reason: str, status: int | None = None):
        self.url = url
        self.reason = reason
        self.status = status
        super().__init__(f"{url}: {reason}" + (f" (HTTP {status})" if status else ""))


def _decode(raw: bytes, encoding_header: str | None) -> str:
    if encoding_header == "gzip":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def fetch(
    url: str,
    *,
    accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    timeout: int | None = None,
    retries: int | None = None,
    verbose: bool = False,
) -> str | None:
    """抓取 URL 并返回文本。

    返回 None 表示**永久失败**（如 404）——调用方应据此跳过而非重试。
    抛 FetchError 表示**可重试失败已耗尽**。
    """
    timeout = timeout or config.HTTP_TIMEOUT
    retries = config.HTTP_RETRIES if retries is None else retries

    last_reason = "unknown"
    last_status: int | None = None

    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": config.USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return _decode(raw, resp.headers.get("Content-Encoding"))
        except urllib.error.HTTPError as e:
            last_status = e.code
            last_reason = f"HTTP {e.code} {e.reason}"
            if e.code in PERMANENT:
                return None                      # 永久失败，不重试
        except urllib.error.URLError as e:
            last_reason = f"URLError {e.reason}"
        except Exception as e:                   # noqa: BLE001 - 网络层兜底
            last_reason = f"{type(e).__name__} {e}"

        if attempt < retries:
            delay = config.HTTP_BACKOFF ** attempt
            if verbose:
                print(f"    [retry {attempt + 1}/{retries}] {last_reason} -> "
                      f"{delay:.1f}s 后重试")
            time.sleep(delay)

    raise FetchError(url, last_reason, last_status)
