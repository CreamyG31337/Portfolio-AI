import re
_SELL_PATTERN = re.compile(r"\b(sell|sold|limit sell|market sell)\b", re.IGNORECASE)
print(_SELL_PATTERN.search("sold completely due to valuation"))
