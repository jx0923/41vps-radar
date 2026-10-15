"""渲染层测试：评分、格式化、静态站产物与域名配置。"""

from __future__ import annotations

import json
import os
import re

import pytest

from letdeals import config, render


def _sample_payload():
    return {
        "source": "test", "count": 2, "generated_at": "2026-10-15T00:00:00Z",
        "records": [
            {
                "thread_id": "1", "source": "let", "provider": "BERO HOST",
                "title": "10th Anniversary", "url": "https://example.com/1",
                "author": "berohost", "posted": "", "age_days": 3,
                "age_status": "NEW", "availability": "ENDED",
                "event_type": "anniversary",
                "discount": {"strength": "循环/永久", "percent_max": 10,
                             "recurring": True, "codes": ["LET10"],
                             "extras": []},
                "specs": {"vcpu": 8, "ram_gb": 32, "storage_gb": 300,
                          "storage_type": "unspecified", "bandwidth_tb": 25},
                "specs_all": {}, "plans": [], "cpu_models": ["EPYC 9275F"],
                "flagship_price": {"amount": 129, "currency": "€",
                                   "cycle": "year"},
                "prices": [], "locations": ["Frankfurt"],
                "stock_hints": [], "replies": None, "confidence": 1.0,
            },
            {
                "thread_id": "leb-x", "source": "leb", "provider": "godlike.host",
                "title": "Cheap VPS", "url": "https://example.com/2",
                "author": "editor", "posted": "", "age_days": 40,
                "age_status": "STALE", "availability": "UNVERIFIED",
                "event_type": "sale",
                "discount": {"strength": "", "percent_max": None,
                             "recurring": False, "codes": [], "extras": []},
                "specs": {"vcpu": 1, "ram_gb": 2, "storage_gb": 30,
                          "storage_type": "NVMe", "bandwidth_tb": None},
                "specs_all": {}, "plans": [],
                "cpu_models": ["EPYC 75F3"],
                "flagship_price": {"amount": 21.99, "currency": "$",
                                   "cycle": "year"},
                "prices": [], "locations": [], "stock_hints": [],
                "replies": None, "confidence": 0.83,
            },
        ],
    }


# --------------------------------------------------------------------------
# 评分
# --------------------------------------------------------------------------

def test_deal_score_recurring_is_valuable():
    rec = _sample_payload()["records"][0]
    assert render.deal_score(rec) > 60


def test_deal_score_plain_is_low():
    rec = _sample_payload()["records"][1]
    assert render.deal_score(rec) < 40


def test_deal_score_anniversary_bonus():
    base = {"discount": {}, "confidence": 0.5}
    a = dict(base, event_type="regular")
    b = dict(base, event_type="anniversary")
    assert render.deal_score(b) > render.deal_score(a)


def test_deal_score_empty_record():
    assert render.deal_score({}) >= 0


# --------------------------------------------------------------------------
# 格式化
# --------------------------------------------------------------------------

def test_price_text():
    rec = _sample_payload()["records"][0]
    assert render.price_text(rec) == "€129/年"


def test_price_text_missing():
    assert render.price_text({}) == "—"


def test_spec_text_hides_unspecified_storage():
    rec = _sample_payload()["records"][0]
    out = render.spec_text(rec)
    assert "8C" in out and "32G" in out
    assert "unspecified" not in out


def test_spec_text_shows_typed_storage():
    rec = _sample_payload()["records"][1]
    assert "NVMe" in render.spec_text(rec)


def test_annual_eur_conversion():
    rec = _sample_payload()["records"][1]     # $21.99/year
    v = render.annual_eur(rec)
    assert v == pytest.approx(21.99 * 0.92, rel=0.01)


def test_annual_eur_monthly_multiplies():
    rec = {"flagship_price": {"amount": 10, "currency": "€", "cycle": "month"}}
    assert render.annual_eur(rec) == 120.0


def test_annual_eur_missing():
    assert render.annual_eur({}) is None


def test_to_markdown_has_header_and_rows():
    md = render.to_markdown(_sample_payload()["records"])
    lines = md.strip().split("\n")
    assert lines[0].startswith("|")
    assert len(lines) == 4                    # 表头 + 分隔 + 2 行
    assert "BERO HOST" in md


# --------------------------------------------------------------------------
# 静态站
# --------------------------------------------------------------------------

def test_build_site_creates_files(tmp_path):
    out = render.build_site(_sample_payload(), str(tmp_path), verbose=False)
    for name in ("index.html", "robots.txt", ".nojekyll", "sitemap.xml",
                 "data/deals.json"):
        assert os.path.exists(os.path.join(out, name)), f"缺少 {name}"


def test_build_site_embeds_data(tmp_path):
    render.build_site(_sample_payload(), str(tmp_path), verbose=False)
    html = open(os.path.join(tmp_path, "index.html"), encoding="utf-8").read()
    m = re.search(
        r'<script type="application/json" id="deals-data">(.*?)</script>',
        html, re.S)
    assert m, "未找到内嵌数据块"
    data = json.loads(m.group(1))
    assert len(data["records"]) == 2


def test_build_site_adds_score(tmp_path):
    payload = _sample_payload()
    render.build_site(payload, str(tmp_path), verbose=False)
    assert all("score" in r for r in payload["records"])


def test_build_site_no_placeholder_left(tmp_path):
    render.build_site(_sample_payload(), str(tmp_path), verbose=False)
    html = open(os.path.join(tmp_path, "index.html"), encoding="utf-8").read()
    assert not re.search(r"@@[A-Z_]+@@", html), "存在未替换的占位符"


def test_build_site_escapes_script_close(tmp_path):
    """记录里若含 </script> 不能逃逸出数据块。"""
    payload = _sample_payload()
    payload["records"][0]["title"] = "evil </script><script>alert(1)</script>"
    render.build_site(payload, str(tmp_path), verbose=False)
    html = open(os.path.join(tmp_path, "index.html"), encoding="utf-8").read()
    m = re.search(
        r'<script type="application/json" id="deals-data">(.*?)</script>',
        html, re.S)
    assert m and "evil" in json.loads(m.group(1))["records"][0]["title"]


def test_site_url_in_sitemap(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITE_URL", "https://deals.example.com")
    render.build_site(_sample_payload(), str(tmp_path), verbose=False)
    sitemap = open(os.path.join(tmp_path, "sitemap.xml"),
                   encoding="utf-8").read()
    assert "https://deals.example.com/" in sitemap
    robots = open(os.path.join(tmp_path, "robots.txt"), encoding="utf-8").read()
    assert "deals.example.com/sitemap.xml" in robots


def test_site_url_absent_uses_relative(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITE_URL", "")
    render.build_site(_sample_payload(), str(tmp_path), verbose=False)
    sitemap = open(os.path.join(tmp_path, "sitemap.xml"),
                   encoding="utf-8").read()
    assert "<loc>/</loc>" in sitemap


def test_custom_title_injected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITE_TITLE", "我的 VPS 雷达")
    render.build_site(_sample_payload(), str(tmp_path), verbose=False)
    html = open(os.path.join(tmp_path, "index.html"), encoding="utf-8").read()
    assert "我的 VPS 雷达" in html


def test_source_badge_present(tmp_path):
    """来源徽章由 JS 渲染，因此检查数据与渲染逻辑是否具备来源信息。"""
    render.build_site(_sample_payload(), str(tmp_path), verbose=False)
    html = open(os.path.join(tmp_path, "index.html"), encoding="utf-8").read()
    # 数据里必须带 source
    m = re.search(
        r'<script type="application/json" id="deals-data">(.*?)</script>',
        html, re.S)
    data = json.loads(m.group(1))
    assert {r["source"] for r in data["records"]} == {"let", "leb"}
    # 渲染模板里必须有来源徽章与下拉筛选
    assert 'class="src"' in html
    assert 'id="src"' in html
