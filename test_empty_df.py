import pandas as pd
import numpy as np

# Test empty df crash issue
df = pd.DataFrame(columns=['ticker', 'shares'])
print("Original DF shape:", df.shape)

try:
    print("Filtering with empty list comprehension...")
    result_list = df[[True for _ in range(len(df))]]
    print("Result shape with list:", result_list.shape)
    print("Result columns:", result_list.columns)
except Exception as e:
    print("List comprehension failed:", e)

try:
    print("\nFiltering with numpy boolean array...")
    result_np = df[np.array([True for _ in range(len(df))], dtype=bool)]
    print("Result shape with numpy:", result_np.shape)
    print("Result columns:", result_np.columns)
except Exception as e:
    print("Numpy array failed:", e)
