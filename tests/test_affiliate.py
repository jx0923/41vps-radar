"""联盟推广链接映射测试。

核心诉求：**默认不配置时完全不改变现有行为**，配置后按域名精确替换。
"""

from __future__ import annotations

import json

import pytest

from letdeals import affiliate


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个用例前清空环境变量，避免互相污染。"""
    monkeypatch.delenv("LDR_AFFILIATES", raising=False)
    yield


# --------------------------------------------------------------------------
# 默认行为：不配置就等于不启用
# --------------------------------------------------------------------------

def test_default_is_empty_and_passthrough():
    assert affiliate._load() == {}
    assert affiliate.rewrite("https://example.com/deals") == \
        "https://example.com/deals"


def test_summary_when_empty():
    assert "未配置" in affiliate.summary()


def test_rewrite_none_returns_none():
    """没有厂商链接时不能崩，也不能凭空造一个。"""
    assert affiliate.rewrite(None) is None
    assert affiliate.rewrite("") == ""


def test_rewrite_unmapped_domain_passthrough(monkeypatch):
    monkeypatch.setenv("LDR_AFFILIATES",
                       json.dumps({"a.com": "https://aff.test/?id=1"}))
    assert affiliate.rewrite("https://b.com/deals") == "https://b.com/deals"


# --------------------------------------------------------------------------
# 命中替换
# --------------------------------------------------------------------------

def test_rewrite_exact_domain(monkeypatch):
    monkeypatch.setenv("LDR_AFFILIATES",
                       json.dumps({"a.com": "https://aff.test/?id=1"}))
    assert affiliate.rewrite("https://a.com/deals") == "https://aff.test/?id=1"


def test_rewrite_ignores_www(monkeypatch):
    monkeypatch.setenv("LDR_AFFILIATES",
                       json.dumps({"a.com": "https://aff.test/?id=1"}))
    assert affiliate.rewrite("https://www.a.com/deals") == \
        "https://aff.test/?id=1"


def test_rewrite_matches_parent_domain_of_subdomain(monkeypatch):
    """my./billing. 这类购买子域也应命中厂商规则。"""
    monkeypatch.setenv("LDR_AFFILIATES",
                       json.dumps({"a.com": "https://aff.test/?id=1"}))
    assert affiliate.rewrite("https://my.a.com/store/vps") == \
        "https://aff.test/?id=1"
    assert affiliate.rewrite("https://billing.a.com/cart") == \
        "https://aff.test/?id=1"


def test_rewrite_subdomain_specific_rule_wins(monkeypatch):
    """同时配了子域和父域时，更具体的子域规则优先。"""
    monkeypatch.setenv("LDR_AFFILIATES", json.dumps({
        "a.com": "https://aff.test/generic",
        "my.a.com": "https://aff.test/specific",
    }))
    assert affiliate.rewrite("https://my.a.com/store") == \
        "https://aff.test/specific"
    assert affiliate.rewrite("https://a.com/deals") == \
        "https://aff.test/generic"


# --------------------------------------------------------------------------
# 配置容错
# --------------------------------------------------------------------------

def test_bad_json_falls_back_to_default(monkeypatch):
    """配置写错不能让抓取挂掉 —— 最坏只是没有推广链接。"""
    monkeypatch.setenv("LDR_AFFILIATES", "{ not json")
    assert affiliate._load() == {}
    assert affiliate.rewrite("https://a.com/x") == "https://a.com/x"


def test_non_dict_json_ignored(monkeypatch):
    monkeypatch.setenv("LDR_AFFILIATES", '["https://a.com"]')
    assert affiliate._load() == {}


def test_invalid_values_filtered(monkeypatch):
    """只接受以 http 开头的字符串值。"""
    monkeypatch.setenv("LDR_AFFILIATES", json.dumps({
        "good.com": "https://aff.test/?id=1",
        "bad.com": "not-a-url",
        "num.com": 123,
    }))
    table = affiliate._load()
    assert "good.com" in table
    assert "bad.com" not in table
    assert "num.com" not in table


def test_keys_are_lowercased(monkeypatch):
    monkeypatch.setenv("LDR_AFFILIATES",
                       json.dumps({"A.COM": "https://aff.test/?id=1"}))
    assert affiliate.rewrite("https://a.com/x") == "https://aff.test/?id=1"


def test_summary_lists_configured_vendors(monkeypatch):
    monkeypatch.setenv("LDR_AFFILIATES", json.dumps({
        "a.com": "https://aff.test/1",
        "b.com": "https://aff.test/2",
    }))
    s = affiliate.summary()
    assert "2 家" in s
    assert "a.com" in s and "b.com" in s


# --------------------------------------------------------------------------
# 与 build_record 的集成
# --------------------------------------------------------------------------

def test_build_record_applies_affiliate(monkeypatch):
    """配置推广链接后，记录里的 vendor_url 应被替换。"""
    from letdeals.extract import build_record

    monkeypatch.setenv("LDR_AFFILIATES",
                       json.dumps({"dartnode.com":
                                   "https://aff.test/?id=dart"}))
    item = {
        "thread_id": "1", "source": "let",
        "title": "DartNode Black Friday Deals",
        "link": "https://lowendtalk.com/discussion/1/x",
        "pubDate": "Fri, 03 Oct 2026 12:00:00 +0000",
        "author": "dartnode",
        "description": '<a href="https://dartnode.com/warehouse-deals">'
                       'deals</a>',
    }
    r = build_record(item)
    assert r["vendor_url"] == "https://aff.test/?id=dart"


def test_build_record_without_affiliate_uses_original(monkeypatch):
    """没配置时保持原链接（不改变现有行为）。"""
    from letdeals.extract import build_record

    item = {
        "thread_id": "2", "source": "let",
        "title": "DartNode Black Friday Deals",
        "link": "https://lowendtalk.com/discussion/2/x",
        "pubDate": "Fri, 03 Oct 2026 12:00:00 +0000",
        "author": "dartnode",
        "description": '<a href="https://dartnode.com/warehouse-deals">'
                       'deals</a>',
    }
    r = build_record(item)
    assert r["vendor_url"] == "https://dartnode.com/warehouse-deals"
