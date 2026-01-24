#!/usr/bin/env python3
"""Standalone test for new ETF fetch functions - no scheduler dependencies"""
import requests
import pandas as pd
from datetime import datetime, timezone
from io import BytesIO, StringIO
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Inline the fetch functions to avoid imports
def fetch_spdr_holdings(etf_ticker, xlsx_url):
    """Download and parse SPDR ETF holdings Excel file."""
    try:
        logger.info(f"📥 Downloading {etf_ticker} holdings from SPDR...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(xlsx_url, timeout=30, headers=headers)
        response.raise_for_status()
        
        df = pd.read_excel(BytesIO(response.content), engine='openpyxl', skiprows=4)
        df.columns = df.columns.str.strip()
        
        column_mapping = {
            'Ticker': 'ticker',
            'Name': 'name',
            'Identifier': 'ticker',
            'Weight': 'weight_percent',
            'Shares': 'shares',
            'Quantity': 'shares',
        }
        
        df = df.rename(columns=column_mapping)
        
        if 'ticker' not in df.columns:
            logger.error(f"❌ Missing ticker column. Found: {df.columns.tolist()}")
            return None
            
        df = df[df['ticker'].notna()]
        df = df[df['ticker'] != '']
        df['ticker'] = df['ticker'].astype(str).str.upper().str.strip()
        
        if 'shares' in df.columns:
            df['shares'] = pd.to_numeric(df['shares'], errors='coerce').fillna(0)
        if 'weight_percent' in df.columns:
            df['weight_percent'] = pd.to_numeric(df['weight_percent'], errors='coerce').fillna(0)
        
        logger.info(f"✅ Parsed {len(df)} holdings for {etf_ticker}")
        return df
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return None

def fetch_globalx_holdings(etf_ticker, csv_url_template):
    """Download and parse Global X ETF holdings CSV."""
    try:
        logger.info(f"📥 Downloading {etf_ticker} holdings from Global X...")
        
        today = datetime.now(timezone.utc)
        date_str = today.strftime('%Y%m%d')
        csv_url = csv_url_template.format(date=date_str)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(csv_url, timeout=30, headers=headers)
        response.raise_for_status()
        
        df = pd.read_csv(StringIO(response.text), skiprows=2)
        df.columns = df.columns.str.strip()
        
        column_mapping = {
            'Ticker': 'ticker',
            'Name': 'name',
            'Shares Held': 'shares',
            '% of Net Assets': 'weight_percent',
        }
        
        df = df.rename(columns=column_mapping)
        
        if 'ticker' not in df.columns:
            logger.error(f"❌ Missing ticker column. Found: {df.columns.tolist()}")
            return None
            
        df = df[df['ticker'].notna()]
        df = df[df['ticker'] != '']
        df['ticker'] = df['ticker'].astype(str).str.upper().str.strip()
        
        if 'shares' in df.columns:
            df['shares'] = df['shares'].astype(str).str.replace(',', '').str.strip()
            df['shares'] = pd.to_numeric(df['shares'], errors='coerce').fillna(0)
        if 'weight_percent' in df.columns:
            df['weight_percent'] = pd.to_numeric(df['weight_percent'], errors='coerce').fillna(0)
        
        logger.info(f"✅ Parsed {len(df)} holdings for {etf_ticker}")
        return df
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return None

# Test all three ETFs
print("\n" + "="*60)
print("Testing XBI (SPDR)")
print("="*60)
xbi_df = fetch_spdr_holdings('XBI', 
    "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xbi.xlsx")
if xbi_df is not None:
    print(f"✅ SUCCESS: {len(xbi_df)} holdings")
    print(f"Sample: {xbi_df[['ticker', 'name']].head(3).to_dict('records')}")

print("\n" + "="*60)
print("Testing BOTZ (Global X)")
print("="*60)
botz_df = fetch_globalx_holdings('BOTZ',
    "https://assets.globalxetfs.com/funds/holdings/botz_full-holdings_{date}.csv")
if botz_df is not None:
    print(f"✅ SUCCESS: {len(botz_df)} holdings")
    print(f"Sample: {botz_df[['ticker', 'name']].head(3).to_dict('records')}")

print("\n" + "="*60)
print("Testing LIT (Global X)")
print("="*60)
lit_df = fetch_globalx_holdings('LIT',
    "https://assets.globalxetfs.com/funds/holdings/lit_full-holdings_{date}.csv")
if lit_df is not None:
    print(f"✅ SUCCESS: {len(lit_df)} holdings")
    print(f"Sample: {lit_df[['ticker', 'name']].head(3).to_dict('records')}")
