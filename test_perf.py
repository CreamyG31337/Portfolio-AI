import time
import pandas as pd
import numpy as np

# Generate a large DataFrame
N = 10000
df = pd.DataFrame({
    'symbol': [f'SYM{i}' for i in range(N)],
    'market_value': np.random.rand(N) * 1000,
    'quantity': np.random.rand(N) * 100,
    'cost_basis': np.random.rand(N) * 1000,
    'unrealized_pnl': np.random.rand(N) * 100,
    'unrealized_pnl_pct': np.random.rand(N) * 10,
    'current_price': np.random.rand(N) * 100,
    'daily_pnl': np.random.rand(N) * 10,
    'daily_pnl_pct': np.random.rand(N) * 5,
    'five_day_pnl': np.random.rand(N) * 20,
    'five_day_pnl_pct': np.random.rand(N) * 10,
    'company': [f'Company {i}' for i in range(N)],
    'currency': ['CAD'] * N,
})

# Test iterrows
start = time.time()
for idx, row in df.iterrows():
    symbol = row.get('symbol', 'N/A')
    market_value = float(row.get('market_value', 0) or 0)
    current_price = float(row.get('current_price', 0) or 0)
    quantity = float(row.get('quantity', 0) or 0)
time_iterrows = time.time() - start

# Test itertuples
start = time.time()
for row in df.itertuples(index=False):
    symbol = getattr(row, 'symbol', 'N/A')

    val1 = getattr(row, 'market_value', None)
    market_value = float(val1) if val1 is not None else 0.0

    val2 = getattr(row, 'current_price', None)
    current_price = float(val2) if val2 is not None else 0.0

    val3 = getattr(row, 'quantity', None)
    quantity = float(val3) if val3 is not None else 0.0
time_itertuples = time.time() - start

print(f"iterrows: {time_iterrows:.4f}s")
print(f"itertuples: {time_itertuples:.4f}s")
print(f"Speedup: {time_iterrows / time_itertuples:.2f}x")
