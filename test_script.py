import json

from utils.trade_reason import trade_display_action

trade1 = {"reason": "sold to buy something else", "action": ""}
print(trade_display_action(trade1))

trade2 = {"reason": "Sold completely due to valuation", "action": ""}
print(trade_display_action(trade2))

trade3 = {"reason": "Took profits after massive run-up, anticipating a pullback.", "action": ""}
print(trade_display_action(trade3))
