"""回帖解析与库存表态判定测试。

重点是三类误判的防线 + 语义反问题（working on a restock）。
"""

from __future__ import annotations

from letdeals.replies import (
    extract_stock_signals,
    find_max_page,
    is_valid_statement,
    parse_replies,
)


_CID = {"n": 0}


def _reply(body: str, *, vendor: bool = True, author: str = "v"):
    """构造一条回帖。

    每次调用分配**唯一** comment_id —— 否则「同一条回复内取最严格状态」
    的裁决逻辑会把不同回复误当成同一条。
    """
    _CID["n"] += 1
    return {
        "comment_id": str(_CID["n"]), "author": author,
        "datetime": "2026-10-03T12:00:00+00:00",
        "body": body, "is_op": vendor, "is_provider": vendor,
        "is_vendor_reply": vendor,
    }


# --------------------------------------------------------------------------
# HTML 解析
# --------------------------------------------------------------------------

def test_parse_replies_extracts_fields():
    html = (
        '<li class="Item ItemComment Role_Member">'
        '<div id="Comment_12345"></div>'
        '<a href="/profile/alice">alice</a>'
        '<time datetime="2026-10-03T12:22:08+00:00"></time>'
        '<div class="Message userContent">hello world</div>'
        '</li>'
    )
    replies = parse_replies(html)
    assert len(replies) == 1
    r = replies[0]
    assert r["comment_id"] == "12345"
    assert r["author"] == "alice"
    assert r["datetime"].startswith("2026-10-03")
    assert "hello world" in r["body"]
    assert r["is_vendor_reply"] is False


def test_parse_replies_detects_vendor():
    """商家身份靠 isOriginalPoster / Role_PatronProvider 识别。"""
    html = (
        '<li class="Item ItemComment isOriginalPoster Role_Member '
        'Role_PatronProvider">'
        '<div id="Comment_1"></div>'
        '<div class="Message userContent">we restocked</div>'
        '</li>'
    )
    r = parse_replies(html)[0]
    assert r["is_vendor_reply"] is True
    assert r["is_op"] is True
    assert r["is_provider"] is True


def test_parse_replies_strips_nested_quotes():
    """嵌套引用必须被剥离，否则会把别人的话当商家表态。"""
    html = (
        '<li class="Item ItemComment isOriginalPoster Role_PatronProvider">'
        '<div id="Comment_1"></div>'
        '<div class="Message userContent">'
        '<blockquote class="UserQuote"><div class="QuoteText">'
        '<blockquote class="UserQuote"><div class="QuoteText">'
        'is it sold out?'
        '</div></blockquote></div></blockquote>'
        '<p>You will definitely get a server.</p>'
        '</div></li>'
    )
    r = parse_replies(html)[0]
    assert "sold out" not in r["body"]
    assert "definitely get a server" in r["body"]


def test_find_max_page():
    html = '<a href="/x/p2">2</a><a href="/x/p17">17</a>'
    assert find_max_page(html) == 17


def test_find_max_page_defaults_one():
    assert find_max_page("<html>no pages</html>") == 1


# --------------------------------------------------------------------------
# 语境校验（三类误判防线）
# --------------------------------------------------------------------------

def test_reject_question():
    """『BF L Flash sold out ?』是用户在问，不是表态。"""
    assert is_valid_statement("BF L Flash sold out ?", "sold out") is False


def test_reject_non_stock_object():
    """『Free trial is now available』说的是试用，不是库存。"""
    assert is_valid_statement(
        "Free trial is now available for the start tier",
        "now available") is False


def test_reject_eligibility_statement():
    """『promotion ... available only for monthly billing』是促销资格。"""
    assert is_valid_statement(
        "the promotion for Intel-based VPS plans is available only for "
        "packages with a monthly billing cycle",
        "plans is available") is False


def test_reject_negated_statement():
    """『it's always out of stock … it's not like that』商家其实在否认。"""
    assert is_valid_statement(
        "nah, considering that it's always often out of stock unfortunately "
        "it's not like that. what kind of problems do you mean?",
        "out of stock") is False


def test_accept_real_soldout():
    assert is_valid_statement(
        "All plans with IPv4 addresses are currently sold out",
        "sold out") is True


def test_accept_still_in_stock():
    """『Budget VPS still in stock! Premium is sold out』主体是有货。"""
    assert is_valid_statement(
        "Budget VPS still in stock! Premium is sold out", "sold out") is True


def test_reject_question_but_accept_statement():
    """含 are 的陈述句不能因疑问词规则被误杀。"""
    assert is_valid_statement("All plans are sold out now", "sold out") is True
    assert is_valid_statement("Are all plans sold out?", "sold out") is False


def test_accept_real_restock():
    assert is_valid_statement(
        "We have restocked the servers", "restocked") is True


# --------------------------------------------------------------------------
# 信号抽取与优先级
# --------------------------------------------------------------------------

def test_vendor_signal_wins_over_user():
    """商家表态优先于用户猜测。"""
    replies = [
        _reply("is it sold out?", vendor=False, author="user1"),
        _reply("We have restocked the servers.", vendor=True, author="vendor"),
    ]
    sig = extract_stock_signals(replies)
    assert sig["reply_source"] == "vendor"
    assert sig["reply_status"] == "ON_SALE"


def test_restocking_means_out_of_stock():
    """『working on a restock』意味着当前缺货，不能判成在售。"""
    sig = extract_stock_signals([_reply("We're already working on a restock")])
    assert sig["reply_status"] == "RESTOCKING"


def test_mixed_availability_is_partial():
    """同一条回复里既有售罄又有在售时，应判为 PARTIAL（部分售罄）。"""
    sig = extract_stock_signals([_reply(
        "Budget VPS still in stock! Premium is sold out")])
    assert sig["reply_status"] == "PARTIAL"


def test_partial_not_reported_as_full_soldout():
    """部分售罄绝不能报成全量售罄。"""
    sig = extract_stock_signals([_reply(
        "Standard storage VPS is sold out, but other plans remain in stock")])
    assert sig["reply_status"] == "PARTIAL"


def test_restocking_with_other_plans_available_is_partial():
    """真实 BERO 案例：IPv4 售罄补货中，但 IPv6 仍有货 -> 部分售罄。

    原文: "All plans with IPv4 addresses are currently sold out. We are
    working on restocking them. IPv6-only plans are still available."
    判成完全售罄或完全在售都是误导，PARTIAL 才准确。
    """
    sig = extract_stock_signals([_reply(
        "All plans with IPv4 addresses are currently sold out. We are "
        "working on restocking them. IPv6-only plans are still available.")])
    assert sig["reply_status"] == "PARTIAL"


def test_restocking_alone_is_restocking():
    """只说在补货、未提有货时，应判 RESTOCKING（= 当前缺货）。"""
    sig = extract_stock_signals([_reply(
        "We are working on restocking our VPS as soon as possible!")])
    assert sig["reply_status"] == "RESTOCKING"


def test_sale_over_means_ended():
    sig = extract_stock_signals([_reply(
        "The sale is over. The Ryzen bundles are back to their regular prices.")])
    assert sig["reply_status"] == "ENDED"


def test_latest_vendor_statement_wins():
    """多条商家表态时取最新的一条。"""
    replies = [
        _reply("Already restocked", author="v"),
        _reply("All plans are sold out now", author="v"),
    ]
    replies[0]["datetime"] = "2026-10-03T10:00:00+00:00"
    replies[1]["datetime"] = "2026-10-03T18:00:00+00:00"
    sig = extract_stock_signals(replies)
    assert sig["reply_status"] == "SOLD_OUT"


def test_user_only_signal_is_flagged():
    sig = extract_stock_signals([_reply("seems sold out", vendor=False)])
    assert sig["reply_source"] == "user"


def test_no_signal():
    sig = extract_stock_signals([_reply("thanks, great deal!")])
    assert sig["reply_status"] is None
    assert sig["reply_source"] is None


def test_counts():
    replies = [
        _reply("a", vendor=True),
        _reply("b", vendor=False),
        _reply("c", vendor=True),
    ]
    sig = extract_stock_signals(replies)
    assert sig["reply_count"] == 3
    assert sig["vendor_reply_count"] == 2


def test_empty_replies():
    sig = extract_stock_signals([])
    assert sig["reply_count"] == 0
    assert sig["reply_status"] is None
