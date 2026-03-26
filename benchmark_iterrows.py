import pandas as pd
import time
import numpy as np

# Create a sample DataFrame
df = pd.DataFrame({
    'symbol': [f'SYM{i}' for i in range(1000)],
    'quantity': np.random.rand(1000) * 100,
    'cost_basis': np.random.rand(1000) * 1000,
    'market_value': np.random.rand(1000) * 1500,
})

# Benchmark iterrows
start = time.time()
total1 = sum(float(row.get('market_value', 0) or 0) for _, row in df.iterrows())
end = time.time()
time_iterrows_sum = end - start

# Benchmark vectorized sum
start = time.time()
total2 = pd.to_numeric(df['market_value'], errors='coerce').fillna(0).sum() if 'market_value' in df.columns else 0.0
end = time.time()
time_vectorized = end - start

# Benchmark iterrows dict access
start = time.time()
for idx, row in df.iterrows():
    s = row.get('symbol')
    q = row.get('quantity')
    c = row.get('cost_basis')
end = time.time()
time_iterrows_loop = end - start

# Benchmark to_dict records
start = time.time()
for row in df.to_dict('records'):
    s = row.get('symbol')
    q = row.get('quantity')
    c = row.get('cost_basis')
end = time.time()
time_todict = end - start

print(f"Vectorized sum vs iterrows sum: {time_vectorized:.5f}s vs {time_iterrows_sum:.5f}s (Speedup: {time_iterrows_sum/time_vectorized:.1f}x)")
print(f"to_dict vs iterrows loop: {time_todict:.5f}s vs {time_iterrows_loop:.5f}s (Speedup: {time_iterrows_loop/time_todict:.1f}x)")
