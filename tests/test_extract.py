"""抽取层测试：规格/价格/折扣/活动性质/库存判定。"""

from __future__ import annotations

from letdeals.extract import (
    age_status,
    availability,
    build_record,
    extract_cpu_models,
    extract_discount,
    extract_event,
    extract_locations,
    extract_prices,
    extract_provider,
    extract_specs,
)


# --------------------------------------------------------------------------
# 规格
# --------------------------------------------------------------------------

def test_extract_specs_full():
    text = "8 vCores, 32 GB DDR5 RAM, 300 GB NVMe, 25 TB Bandwidth"
    s = extract_specs(text)
    assert s["vcpu"] == 8
    assert s["ram_gb"] == 32
    assert s["storage_gb"] == 300
    assert s["storage_type"] == "NVMe"
    assert s["bandwidth_tb"] == 25


def test_extract_specs_takes_max():
    """多套餐时应取最大值作为旗舰规格。"""
    text = "2 Cores 4 GB RAM 40 GB SSD\n4 Cores 8 GB RAM 80 GB SSD"
    s = extract_specs(text)
    assert s["vcpu"] == 4
    assert s["ram_gb"] == 8
    assert s["storage_gb"] == 80


def test_extract_specs_needs_ram_keyword():
    """裸容量（无 RAM 关键词）不应被 extract_specs 认作内存。

    这正是需要 parse_flat_tables 做位置推断的原因：
    LET 表格拍平后只剩「32 GB」这种裸值。
    """
    s = extract_specs("32 GB 300 GB 25 TB")
    assert s["ram_gb"] is None
    assert s["storage_gb"] is None


def test_extract_specs_missing_returns_none():
    s = extract_specs("just some prose without specs")
    assert s["vcpu"] is None
    assert s["ram_gb"] is None


def test_extract_cpu_models():
    models = extract_cpu_models("Powered by AMD EPYC 9275F and Ryzen 9 9950X")
    assert any("9275F" in m for m in models)
    assert any("9950X" in m for m in models)


def test_extract_cpu_models_no_false_positive():
    assert extract_cpu_models("cheap vps deals for everyone") == []


# --------------------------------------------------------------------------
# 价格
# --------------------------------------------------------------------------

def test_extract_prices_prefix():
    ps = extract_prices("$2.49/month")
    assert ps and ps[0]["amount"] == 2.49
    assert ps[0]["currency"] == "$"
    assert ps[0]["cycle"] == "month"


def test_extract_prices_suffix_eur():
    ps = extract_prices("€129/year")
    assert ps[0]["amount"] == 129
    assert ps[0]["cycle"] == "year"


def test_extract_prices_postfix_symbol():
    ps = extract_prices("7.49€/quarterly")
    assert ps[0]["amount"] == 7.49
    assert ps[0]["currency"] == "€"
    assert ps[0]["cycle"] == "quarter"


def test_extract_prices_sorted_by_annual():
    """应按时长折算排序，而非字面金额。"""
    ps = extract_prices("$10/month and $50/year")
    # 月付年化 120 > 年付 50，故年付应排在前面
    assert ps[0]["cycle"] == "year"


def test_extract_prices_empty():
    assert extract_prices("no prices here") == []


# --------------------------------------------------------------------------
# 折扣
# --------------------------------------------------------------------------

def test_extract_discount_percent():
    d = extract_discount("Get 60% off lifetime")
    assert d["percent_max"] == 60
    assert d["recurring"] is True


def test_extract_discount_code():
    d = extract_discount("Use coupon code LETB25 at checkout")
    assert "LETB25" in d["codes"]


def test_extract_discount_rejects_placeholder_codes():
    """CODE / DISCOUNT / REQUIRED 这类占位词不是真优惠码。"""
    d = extract_discount("Use coupon code CODE and promo code DISCOUNT")
    assert "CODE" not in d["codes"]
    assert "DISCOUNT" not in d["codes"]


def test_extract_discount_extras():
    d = extract_discount("double storage plus 2 months free")
    assert d["extras"]


def test_extract_discount_empty():
    d = extract_discount("nothing special here")
    assert d["strength"] == ""
    assert d["recurring"] is False


# --------------------------------------------------------------------------
# 活动性质
# --------------------------------------------------------------------------

def test_extract_event_anniversary():
    assert extract_event("BERO HOST 10th Anniversary Deals", "") == "anniversary"


def test_extract_event_black_friday():
    assert extract_event("Black Friday 2025 Deals", "") == "black_friday"


def test_extract_event_priority():
    """周年庆优先于泛化的 sale。"""
    assert extract_event("10th Anniversary Sale", "") == "anniversary"


def test_extract_event_regular():
    assert extract_event("Weekly VPS Thread", "hello") == "regular"


# --------------------------------------------------------------------------
# 地点
# --------------------------------------------------------------------------

def test_extract_locations():
    locs = extract_locations("Hosted in Frankfurt, Germany")
    assert "Frankfurt" in locs
    assert "Germany" in locs


def test_extract_locations_dedup():
    locs = extract_locations("Frankfurt and again Frankfurt")
    assert locs.count("Frankfurt") == 1


# --------------------------------------------------------------------------
# 厂商名
# --------------------------------------------------------------------------

def test_extract_provider_from_separator():
    p = extract_provider("HostBrr | BF2025 Deals | AMD VPS", "labze", "")
    assert p == "HostBrr"


def test_extract_provider_skips_descriptive_head():
    """描述性首段不应被当成厂商名，应回退到域名。"""
    p = extract_provider(
        "Free Ryzen 5900XT Server | From $99/mo", "someone",
        "visit https://budgetvm.com/ for details")
    assert p == "budgetvm.com"


def test_extract_provider_strips_subdomain():
    p = extract_provider("Deals", "x", "https://lg.fra.example.com/x")
    assert p == "example.com"


def test_extract_provider_leb_does_not_use_author():
    """LEB 的作者是编辑，绝不能当厂商名。"""
    p = extract_provider(
        "Some Random Headline About VPS", "raindog308",
        "no domains here", source="leb")
    assert p != "raindog308"


def test_extract_provider_leb_brand_from_text():
    p = extract_provider(
        "Velohost Returns With Even Cheaper Prices", "raindog308",
        "Welcome back, Velohost!", source="leb")
    assert "Velohost" in p


def test_extract_provider_let_prefers_domain_over_title_fragment():
    """LET 不应套用 LEB 的标题裁剪规则。

    「BERO HOST 10th Anniversary Deals」若被裁成
    「BERO HOST 10th Anniversary」会丢掉域名这一更精确的结果。
    """
    p = extract_provider(
        "BERO HOST 10th Anniversary Deals – EPYC Turin",
        "berohost",
        "Order: https://bero-host.de/kvm-rootserver",
        source="let")
    assert p == "bero-host.de"


def test_extract_provider_leb_trims_sentence_suffix():
    """LEB 标题里的句式后缀应被裁掉，留下品牌名。"""
    p = extract_provider(
        "Velohost Returns With Even Cheaper Prices! Get a 4GB VPS",
        "raindog308", "no links", source="leb")
    assert p == "Velohost"


# --------------------------------------------------------------------------
# 库存判定
# --------------------------------------------------------------------------

def test_availability_vendor_takes_priority():
    """商家表态优先于帖文关键词。"""
    a = availability(["sold out"], 1, "ON_SALE", "vendor")
    assert a == "ON_SALE"


def test_availability_vendor_restocking():
    a = availability([], 1, "RESTOCKING", "vendor")
    assert a == "RESTOCKING"


def test_availability_from_stock_hints():
    assert availability(["sold out"], 1) == "SOLD_OUT"
    assert availability(["back in stock"], 1) == "ON_SALE"


def test_availability_user_signal_is_weak():
    """用户说的售罄只能算疑似。"""
    a = availability([], 1, "SOLD_OUT", "user")
    assert a == "LIKELY_SOLD_OUT"


def test_availability_stale_fallback():
    assert availability([], 90) == "UNVERIFIED_STALE"
    assert availability([], 1) == "UNVERIFIED"


def test_age_status():
    assert age_status(1) == "NEW"
    assert age_status(15) == "ACTIVE"
    assert age_status(90) == "STALE"
    assert age_status(None) == "UNKNOWN"


# --------------------------------------------------------------------------
# 记录构建
# --------------------------------------------------------------------------

def test_build_record_shape():
    item = {
        "thread_id": "123", "source": "let",
        "title": "TestHost | 8 vCores 32 GB 300 GB NVMe",
        "link": "https://lowendtalk.com/discussion/123/x",
        "pubDate": "Wed, 01 Oct 2026 00:00:00 +0000",
        "author": "tester",
        "description": "<p>8 vCores, 32 GB RAM, 300 GB NVMe, 25 TB</p>",
    }
    r = build_record(item)
    for key in ("thread_id", "provider", "specs", "prices", "discount",
                "event_type", "availability", "confidence", "source"):
        assert key in r, f"缺少字段 {key}"
    assert r["thread_id"] == "123"
    assert r["source"] == "let"
    assert 0.0 <= r["confidence"] <= 1.0


def test_build_record_table_overrides_specs(bero_plan_lines):
    """表格解析成功时应采用表格里的旗舰套餐。"""
    item = {
        "thread_id": "221713", "source": "let",
        "title": "BERO HOST 10th Anniversary Deals",
        "link": "https://lowendtalk.com/discussion/221713/x",
        "pubDate": "Fri, 03 Oct 2026 12:00:00 +0000",
        "author": "berohost",
        "description": "<pre>" + bero_plan_lines + "</pre>",
    }
    r = build_record(item)
    assert r["specs"]["vcpu"] == 8
    assert r["specs"]["ram_gb"] == 32
    assert r["specs"]["storage_gb"] == 300
    assert r["flagship_price"]["amount"] == 129
    assert len(r["plans"]) >= 5
