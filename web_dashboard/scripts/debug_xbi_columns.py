#!/usr/bin/env python3
"""Debug SPDR Excel file structure"""
import requests
import pandas as pd
from io import BytesIO

url = "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xbi.xlsx"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

print("Downloading XBI file...")
response = requests.get(url, headers=headers, timeout=30)

print(f"Status: {response.status_code}")
print(f"Content-Type: {response.headers.get('Content-Type')}")

print("\nParsing Excel (skiprows=4)...")
df = pd.read_excel(BytesIO(response.content), engine='openpyxl', skiprows=4)

print(f"\nOriginal columns ({len(df.columns)} total):")
for i, col in enumerate(df.columns):
    print(f"  {i}: '{col}'")

print(f"\nAfter strip:")
df.columns = df.columns.str.strip()
for i, col in enumerate(df.columns):
    print(f"  {i}: '{col}'")

print(f"\nDuplicates:")
duplicates = df.columns[df.columns.duplicated()].tolist()
print(f"  {duplicates}")

print(f"\nValue counts:")
print(df.columns.value_counts())

print("\nFirst 3 rows:")
print(df.head(3))
