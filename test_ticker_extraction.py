
import re

def extract_tickers(text):
    pattern = r'\b([A-Z]{1,5})\b'
    exclude_words = {
        'A', 'I', 'AT', 'TO', 'IN', 'ON', 'IT', 'IS', 'BE', 'OR', 'AN',
        'AS', 'BY', 'FOR', 'THE', 'AND', 'BUT', 'NOT', 'YOU', 'ALL',
        'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'ARE', 'FROM', 'THAT',
        'THIS', 'WITH', 'HAVE', 'WILL', 'YOUR', 'MAY', 'NEW', 'US', 'IF',
        'WOULD', 'BEEN', 'WHICH', 'THEIR', 'ABOUT', 'MORE', 'THAN', 'ALSO',
        'CEO', 'CFO', 'IPO', 'ETF', 'GDP', 'CPI', 'FED', 'SEC', 'API',
        'USA', 'UK', 'EU', 'AI', 'ML', 'AR', 'VR', 'IT', 'HR', 'PR',
        'USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'CNY', 'HKD'
    }

    matches = re.findall(pattern, text)
    tickers = [
        ticker for ticker in set(matches)
        if ticker not in exclude_words and 2 <= len(ticker) <= 5
    ]
    return sorted(tickers)

sample_text = """
The Stock Market is UP today. NVDA and AMD are leading the charge.
BUT the FED is watching inflation. GDP growth is strong.
WE expect MORE volatility in the COMING weeks.
ALSO, verify your API keys.
"""

print(extract_tickers(sample_text))
