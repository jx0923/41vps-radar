"""文本工具测试：HTML 清洗、单位换算、拍平表格重建。

表格重建是最易出错的一环（裸容量凭位置推断），因此重点覆盖。
"""

from __future__ import annotations

from letdeals.textutil import (
    parse_flat_tables,
    strip_html,
    strip_md_markers,
    strip_quotes_depth_aware,
    to_gb,
    to_tb,
)


# --------------------------------------------------------------------------
# HTML 清洗
# --------------------------------------------------------------------------

def test_strip_html_basic():
    assert strip_html("<p>Hello <b>World</b></p>") == "Hello World"


def test_strip_html_entities():
    assert strip_html("a &amp; b &lt;c&gt;") == "a & b <c>"


def test_strip_html_keeps_table_cells_on_own_lines():
    """表格拍平后每个单元格独占一行 —— 这是表格重建的前提。"""
    html = "<table><tr><td>A</td><td>8 Cores</td></tr></table>"
    out = strip_html(html)
    assert "A" in out and "8 Cores" in out


def test_strip_html_drops_script_and_style():
    html = "<style>x{}</style><script>bad()</script><p>ok</p>"
    out = strip_html(html)
    assert "ok" in out
    assert "bad" not in out


# --------------------------------------------------------------------------
# 嵌套引用剥离
# --------------------------------------------------------------------------

def test_strip_quotes_simple():
    html = "<blockquote>quoted</blockquote>real reply"
    out = strip_quotes_depth_aware(html)
    assert "quoted" not in out
    assert "real reply" in out


def test_strip_quotes_nested():
    """嵌套引用必须整体剥离 —— 否则会把别人的话当成本人表态。"""
    html = (
        "<blockquote>level1 "
        "<blockquote>level2 <blockquote>level3</blockquote></blockquote>"
        "</blockquote>MY REPLY"
    )
    out = strip_quotes_depth_aware(html)
    assert "level1" not in out
    assert "level2" not in out
    assert "level3" not in out
    assert "MY REPLY" in out


def test_strip_quotes_preserves_text_between_quotes():
    html = "first <blockquote>q</blockquote> second"
    out = strip_quotes_depth_aware(html)
    assert "first" in out and "second" in out and "q" not in out


# --------------------------------------------------------------------------
# 单位换算
# --------------------------------------------------------------------------

def test_to_gb():
    assert to_gb(1, "TB") == 1024
    assert to_gb(1024, "MB") == 1
    assert to_gb(32, "GB") == 32


def test_to_tb():
    assert to_tb(1024, "GB") == 1.0
    assert to_tb(25, "TB") == 25.0


# --------------------------------------------------------------------------
# 拍平表格重建
# --------------------------------------------------------------------------

def test_parse_flat_tables_bero(bero_plan_lines, bero_expected_plans):
    """BERO 十周年的套餐表必须完整还原（黄金样本）。"""
    plans = parse_flat_tables(bero_plan_lines)
    assert len(plans) >= len(bero_expected_plans), (
        f"应至少解析出 {len(bero_expected_plans)} 个套餐，实际 {len(plans)}")

    by_name = {}
    for p in plans:
        by_name.setdefault(p["name"], []).append(p)

    for name, vcpu, ram, storage, price in bero_expected_plans:
        assert name in by_name, f"缺少套餐 {name}"
        p = by_name[name][0]
        assert p["vcpu"] == vcpu, f"{name} vcpu 应为 {vcpu}，实际 {p['vcpu']}"
        assert p["ram_gb"] == ram, f"{name} RAM 应为 {ram}，实际 {p['ram_gb']}"
        assert p["storage_gb"] == storage, (
            f"{name} 存储应为 {storage}，实际 {p['storage_gb']}")
        assert p["price"]["amount"] == price, (
            f"{name} 价格应为 {price}，实际 {p['price']}")


def test_parse_flat_tables_positional_semantics():
    """裸容量必须按出现顺序推断：第1个GB=RAM，第2个=存储，TB=流量。

    这是最容易写错的地方 —— 曾把 300 GB 误判成带宽（25600）。
    """
    body = "\n".join([
        "Plan XXL", "8 Cores", "32 GB", "300 GB", "25 TB", "€129",
    ])
    plans = parse_flat_tables(body)
    assert len(plans) == 1
    p = plans[0]
    assert p["ram_gb"] == 32, f"RAM 应为 32，实际 {p['ram_gb']}"
    assert p["storage_gb"] == 300, f"存储应为 300，实际 {p['storage_gb']}"
    assert p["bandwidth_tb"] == 25, f"流量应为 25，实际 {p['bandwidth_tb']}"


def test_parse_flat_tables_typed_storage():
    """带介质关键词时，存储类型应被记录，且不干扰 RAM 推断。"""
    body = "\n".join([
        "Starter", "2 vCores", "4 GB", "80 GB NVMe", "$5/mo",
    ])
    plans = parse_flat_tables(body)
    assert len(plans) == 1
    p = plans[0]
    assert p["ram_gb"] == 4
    assert p["storage_gb"] == 80
    assert p["storage_type"] == "NVMe"


def test_parse_flat_tables_handles_multiple_blocks():
    body = "\n".join([
        "Plan A", "2 Cores", "4 GB", "40 GB", "€19",
        "Plan B", "4 Cores", "8 GB", "80 GB", "€39",
    ])
    plans = parse_flat_tables(body)
    assert len(plans) == 2
    assert [p["name"] for p in plans] == ["Plan A", "Plan B"]
    assert plans[0]["ram_gb"] == 4
    assert plans[1]["ram_gb"] == 8


def test_parse_flat_tables_empty_on_prose():
    """普通散文不应被误判为套餐表。"""
    body = "We are happy to announce our new sale this week.\nThanks for reading!"
    assert parse_flat_tables(body) == []


def test_parse_flat_tables_requires_vcpu_and_size():
    """只有名字没有规格时不应产出套餐。"""
    body = "\n".join(["Just A Name", "Some text here", "More text"])
    assert parse_flat_tables(body) == []


# --------------------------------------------------------------------------
# Markdown 标记清理
# --------------------------------------------------------------------------

def test_strip_md_markers_bold():
    """商家把 Markdown 写进标题，标记应被去掉但保留文字。

    实测来自 LowEndTalk 的真实标题：
    "**25G Unmetered** 30% lifetime discount - Dedicated Servers"
    """
    assert strip_md_markers(
        "**25G Unmetered** 30% lifetime discount"
    ) == "25G Unmetered 30% lifetime discount"


def test_strip_md_markers_unpaired_trailing():
    """未配对的裸标记也要清掉（如结尾多一个 **）。"""
    assert strip_md_markers(
        "**10G FULL UNMETERED ** - 3 Months Half Price!"
    ) == "10G FULL UNMETERED - 3 Months Half Price!"


def test_strip_md_markers_other_forms():
    assert strip_md_markers("__bold__ text") == "bold text"
    assert strip_md_markers("~~strike~~ here") == "strike here"
    assert strip_md_markers("a **b** c __d__ e") == "a b c d e"


def test_strip_md_markers_keeps_single_asterisk():
    """单个 * 可能是正常内容（通配符、乘法），不能动。"""
    assert strip_md_markers("2 * 4 = 8") == "2 * 4 = 8"
    assert strip_md_markers("plan*") == "plan*"


def test_strip_md_markers_keeps_underscores_in_words():
    """下划线可能是型号或变量名的一部分，单个不能动。"""
    assert strip_md_markers("servers_guru deals") == "servers_guru deals"
    assert strip_md_markers("Xeon_E5_2680") == "Xeon_E5_2680"


def test_strip_md_markers_noop_on_plain_text():
    plain = "Normal Title Without Markers"
    assert strip_md_markers(plain) == plain


def test_strip_md_markers_empty():
    assert strip_md_markers("") == ""
    assert strip_md_markers(None) == ""


def test_strip_md_markers_collapses_extra_spaces():
    """去掉标记后不应留下多余空格。"""
    assert strip_md_markers("**A**  **B**") == "A B"
