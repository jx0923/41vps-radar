"""HTTP 层测试：重试、退避、永久失败判定。"""

from __future__ import annotations

import urllib.error

import pytest

from letdeals import http


class _FakeResponse:
    def __init__(self, body: bytes, encoding: str | None = None):
        self._body = body
        self.headers = {}
        if encoding:
            self.headers["Content-Encoding"] = encoding

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_success(monkeypatch):
    monkeypatch.setattr(http.urllib.request, "urlopen",
                        lambda req, timeout: _FakeResponse(b"hello"))
    assert http.fetch("http://x") == "hello"


def test_fetch_permanent_404_returns_none(monkeypatch):
    """404 是永久失败，应返回 None 且不重试。"""
    calls = []

    def boom(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    monkeypatch.setattr(http.urllib.request, "urlopen", boom)
    assert http.fetch("http://x") is None
    assert len(calls) == 1        # 只请求一次


def test_fetch_retries_then_raises(monkeypatch):
    calls = []

    def boom(req, timeout):
        calls.append(1)
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(http.urllib.request, "urlopen", boom)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(http.FetchError):
        http.fetch("http://x", retries=2)
    assert len(calls) == 3        # 首次 + 2 次重试


def test_fetch_recovers_after_retry(monkeypatch):
    state = {"n": 0}

    def flaky(req, timeout):
        state["n"] += 1
        if state["n"] == 1:
            raise urllib.error.URLError("temporary")
        return _FakeResponse(b"ok")

    monkeypatch.setattr(http.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    assert http.fetch("http://x", retries=2) == "ok"


def test_fetch_error_carries_context(monkeypatch):
    monkeypatch.setattr(http.urllib.request, "urlopen",
                        lambda req, timeout: (_ for _ in ()).throw(
                            urllib.error.HTTPError("u", 503, "Unavailable",
                                                   {}, None)))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(http.FetchError) as ei:
        http.fetch("http://x", retries=1)
    assert ei.value.status == 503
