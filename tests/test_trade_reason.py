from utils.trade_reason import (
    infer_trade_action,
    is_boilerplate_buy_rationale,
    is_dividend_reason,
    is_sell_reason,
    is_trade_sell,
    trade_display_action,
)


def test_infer_trade_action_sell_variants() -> None:
    assert infer_trade_action("Limit Sell - Filled") == "SELL"
    assert infer_trade_action("market sell order") == "SELL"


def test_infer_trade_action_dividend_variants() -> None:
    assert infer_trade_action("DRIP") == "DIVIDEND"
    assert infer_trade_action("Cash Dividend Payment") == "DIVIDEND"
    assert is_dividend_reason("monthly dividend")


def test_infer_trade_action_dividend_growth_thesis_is_buy() -> None:
    """V4: a BUY thesis mentioning dividend growth must not become DIVIDEND."""
    fts = "Wide moat utility with decades of dividend growth and predictable cash flows."
    ko = "KO offers core stability with a wide economic moat and dividend growth."
    pep = "Quality compounder with a long runway of dividend growth."
    assert infer_trade_action(fts) == "BUY"
    assert infer_trade_action(ko) == "BUY"
    assert infer_trade_action(pep) == "BUY"
    assert not is_dividend_reason(fts)
    assert not is_dividend_reason(pep)
    assert is_dividend_reason("Cash Dividend Payment")
    assert is_dividend_reason("DRIP")


def test_infer_trade_action_defaults_to_buy_for_unknown() -> None:
    assert infer_trade_action("manual adjustment", default="BUY") == "BUY"
    assert infer_trade_action(None, default="BUY") == "BUY"
    assert not is_sell_reason("quarterly dividend")


def test_is_trade_sell_uses_action_column() -> None:
    assert is_trade_sell({"action": "SELL", "reason": "Thesis text without sell keyword"})
    assert not is_trade_sell({"action": "BUY", "reason": "Growth thesis"})
    assert is_trade_sell({"action": "BUY", "reason": "Rotate out - SELL"})


def test_trade_display_action_prefers_persisted_action() -> None:
    assert trade_display_action(
        {"action": "BUY", "reason": "After the sell-off, adding WEB.V"}
    ) == "BUY"
    assert trade_display_action(
        {"action": "SELL", "reason": "No keyword in thesis"}
    ) == "SELL"
    assert trade_display_action({"action": "DIVIDEND", "reason": "cash"}) == "DIVIDEND"


def test_trade_display_action_infers_when_action_missing() -> None:
    assert trade_display_action({"reason": "Limit Sell - Filled"}) == "SELL"
    assert trade_display_action({"reason": "DRIP"}) == "DIVIDEND"
    assert trade_display_action({"reason": "manual adjustment"}) == "BUY"


def test_is_boilerplate_buy_rationale() -> None:
    assert is_boilerplate_buy_rationale("EMAIL TRADE - BUY")
    assert is_boilerplate_buy_rationale("MANUAL BUY MOO - Filled")
    assert is_boilerplate_buy_rationale("Market Buy")
    assert is_boilerplate_buy_rationale("Limit Buy - Filled")
    assert is_boilerplate_buy_rationale("buy order")
    assert not is_boilerplate_buy_rationale("")
    assert not is_boilerplate_buy_rationale(
        "Wide moat utility with decades of dividend growth and predictable cash flows."
    )
    assert not is_boilerplate_buy_rationale(
        "KO offers core stability with a wide economic moat despite market-driven softness."
    )
