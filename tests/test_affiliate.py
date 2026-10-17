"""联盟推广链接映射测试。

两种模式：
  A. 参数追加（保留具体套餐页，转化率最高）
  B. 整体替换（厂商只给专属入口时）

核心诉求：**默认不配置时完全不改变现有行为**。
"""

from __future__ import annotations

import json

import pytest

from letdeals import affiliate


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """清空环境变量，并清空模块内 DEFAULTS。

    项目里 DEFAULTS 已填入真实推广链接（线上在用），
    但测试需要从「未配置」这个基线开始，因此这里显式清空。
    """
    monkeypatch.delenv("LDR_AFFILIATES", raising=False)
    monkeypatch.setattr(affiliate, "DEFAULTS", {})
    yield


def _set(monkeypatch, mapping):
    monkeypatch.setenv("LDR_AFFILIATES", json.dumps(mapping))


# --------------------------------------------------------------------------
# 默认行为
# --------------------------------------------------------------------------

def test_default_empty_passthrough():
    assert affiliate._load() == {}
    assert affiliate.rewrite("https://a.com/deals") == "https://a.com/deals"


def test_summary_when_empty():
    assert "未配置" in affiliate.summary()


def test_rewrite_none_returns_none():
    assert affiliate.rewrite(None) is None
    assert affiliate.rewrite("") == ""


def test_unmapped_passthrough(monkeypatch):
    _set(monkeypatch, {"a.com": {"param": "ref", "value": "1"}})
    assert affiliate.rewrite("https://b.com/x") == "https://b.com/x"


# --------------------------------------------------------------------------
# 模式 A：追加参数
# --------------------------------------------------------------------------

def test_append_param_keeps_path_and_query(monkeypatch):
    """关键：保留具体套餐页，只追加推广参数。"""
    _set(monkeypatch, {"deluxhost.net": {"param": "ref", "value": "ABC"}})
    out = affiliate.rewrite(
        "https://deluxhost.net/en/cart?add=storage-1&cycle=monthly")
    assert "add=storage-1" in out
    assert "cycle=monthly" in out
    assert "ref=ABC" in out
    assert out.startswith("https://deluxhost.net/en/cart?")


def test_append_param_to_url_without_query(monkeypatch):
    _set(monkeypatch, {"a.com": {"param": "ref", "value": "9"}})
    assert affiliate.rewrite("https://a.com/deals") == \
        "https://a.com/deals?ref=9"


def test_append_param_replaces_existing(monkeypatch):
    """已有同名参数时替换，不重复追加（避免厂商解析歧义）。"""
    _set(monkeypatch, {"a.com": {"param": "ref", "value": "NEW"}})
    out = affiliate.rewrite("https://a.com/x?ref=OLD&y=1")
    assert out.count("ref=") == 1
    assert "ref=NEW" in out
    assert "y=1" in out


def test_append_param_preserves_fragment(monkeypatch):
    _set(monkeypatch, {"a.com": {"param": "ref", "value": "1"}})
    out = affiliate.rewrite("https://a.com/deals#plans")
    assert "#plans" in out
    assert "ref=1" in out


# --------------------------------------------------------------------------
# 模式 B：整体替换
# --------------------------------------------------------------------------

def test_full_url_mode(monkeypatch):
    _set(monkeypatch, {"racknerd.com": "https://my.racknerd.com/aff.php?aff=1"})
    assert affiliate.rewrite("https://racknerd.com/BlackFriday/") == \
        "https://my.racknerd.com/aff.php?aff=1"


# --------------------------------------------------------------------------
# 域名匹配
# --------------------------------------------------------------------------

def test_www_ignored(monkeypatch):
    _set(monkeypatch, {"a.com": {"param": "ref", "value": "1"}})
    assert "ref=1" in affiliate.rewrite("https://www.a.com/deals")


def test_subdomain_matches_parent(monkeypatch):
    _set(monkeypatch, {"a.com": {"param": "ref", "value": "1"}})
    assert "ref=1" in affiliate.rewrite("https://my.a.com/store")
    assert "ref=1" in affiliate.rewrite("https://billing.a.com/cart")


def test_specific_subdomain_wins(monkeypatch):
    _set(monkeypatch, {
        "a.com": {"param": "ref", "value": "generic"},
        "my.a.com": {"param": "ref", "value": "specific"},
    })
    assert "specific" in affiliate.rewrite("https://my.a.com/x")
    assert "generic" in affiliate.rewrite("https://a.com/x")


# --------------------------------------------------------------------------
# 配置容错
# --------------------------------------------------------------------------

def test_bad_json_falls_back(monkeypatch):
    monkeypatch.setenv("LDR_AFFILIATES", "{ bad")
    assert affiliate._load() == {}
    assert affiliate.rewrite("https://a.com/x") == "https://a.com/x"


def test_invalid_entries_filtered(monkeypatch):
    _set(monkeypatch, {
        "ok.com": {"param": "ref", "value": "1"},
        "str.com": "https://aff.test/x",
        "bad.com": "not-a-url",
        "incomplete.com": {"param": "ref"},
        "num.com": 123,
    })
    t = affiliate._load()
    assert "ok.com" in t and "str.com" in t
    assert "bad.com" not in t
    assert "incomplete.com" not in t
    assert "num.com" not in t


def test_keys_lowercased(monkeypatch):
    _set(monkeypatch, {"A.COM": {"param": "ref", "value": "1"}})
    assert "ref=1" in affiliate.rewrite("https://a.com/x")


def test_summary_shows_modes(monkeypatch):
    _set(monkeypatch, {
        "a.com": {"param": "ref", "value": "1"},
        "b.com": "https://aff.test/2",
    })
    s = affiliate.summary()
    assert "追加参数" in s and "整体替换" in s


# --------------------------------------------------------------------------
# 与 build_record 集成
# --------------------------------------------------------------------------

def test_build_record_applies_append_mode(monkeypatch):
    from letdeals.extract import build_record
    _set(monkeypatch, {"dartnode.com": {"param": "ref", "value": "X1"}})
    item = {
        "thread_id": "1", "source": "let",
        "title": "DartNode Black Friday Deals",
        "link": "https://lowendtalk.com/discussion/1/x",
        "pubDate": "Fri, 03 Oct 2026 12:00:00 +0000",
        "author": "dartnode",
        "description": '<a href="https://dartnode.com/warehouse-deals">d</a>',
    }
    r = build_record(item)
    assert r["vendor_url"] == "https://dartnode.com/warehouse-deals?ref=X1"


def test_build_record_without_affiliate_unchanged(monkeypatch):
    from letdeals.extract import build_record
    item = {
        "thread_id": "2", "source": "let",
        "title": "DartNode Black Friday Deals",
        "link": "https://lowendtalk.com/discussion/2/x",
        "pubDate": "Fri, 03 Oct 2026 12:00:00 +0000",
        "author": "dartnode",
        "description": '<a href="https://dartnode.com/warehouse-deals">d</a>',
    }
    r = build_record(item)
    assert r["vendor_url"] == "https://dartnode.com/warehouse-deals"
