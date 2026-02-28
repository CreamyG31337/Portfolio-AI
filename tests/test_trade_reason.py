from utils.trade_reason import infer_trade_action, is_dividend_reason, is_sell_reason


def test_infer_trade_action_sell_variants() -> None:
    assert infer_trade_action("Limit Sell - Filled") == "SELL"
    assert infer_trade_action("market sell order") == "SELL"


def test_infer_trade_action_dividend_variants() -> None:
    assert infer_trade_action("DRIP") == "DIVIDEND"
    assert infer_trade_action("Cash Dividend Payment") == "DIVIDEND"
    assert is_dividend_reason("monthly dividend")


def test_infer_trade_action_defaults_to_buy_for_unknown() -> None:
    assert infer_trade_action("manual adjustment", default="BUY") == "BUY"
    assert infer_trade_action(None, default="BUY") == "BUY"
    assert not is_sell_reason("quarterly dividend")
