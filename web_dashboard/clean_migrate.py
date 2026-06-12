#!/usr/bin/env python3
"""
Clean migration script that properly migrates CSV data to Supabase
"""

import os
import pandas as pd
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def migrate_portfolio_data():
    """Migrate portfolio data from CSV to Supabase"""
    print("Migrating portfolio data...")
    
    # Read CSV data
    csv_file = r'C:\Users\cream\OneDrive\Documents\LLM-Micro-Cap-trading-bot\trading_data\funds\Project Chimera\llm_portfolio_update.csv'
    df = pd.read_csv(csv_file)
    
    print(f"CSV records: {len(df)}")
    
    # Get the latest record for each ticker (most recent position)
    latest_positions = df.groupby('Ticker').tail(1)
    print(f"Latest positions: {len(latest_positions)}")
    
    # Prepare data for Supabase
    records = []
    for row in latest_positions.to_dict('records'):
        record = {
            "fund": "Project Chimera",
            "ticker": str(row["Ticker"]),
            "company": str(row["Company"]),
            "shares": float(row["Shares"]),
            "price": float(row["Current Price"]),
            "cost_basis": float(row["Cost Basis"]),
            "pnl": float(row["PnL"]),
            "currency": str(row["Currency"]),
            "date": str(row["Date"])
        }
        records.append(record)
    
    # Insert into Supabase
    url = f"{os.getenv('SUPABASE_URL')}/rest/v1/portfolio_positions"
    headers = {
        "apikey": os.getenv("SUPABASE_ANON_KEY"),
        "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
        "Content-Type": "application/json"
    }
    
    # Insert in batches
    batch_size = 50
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        try:
            response = requests.post(url, headers=headers, json=batch)
            if response.status_code == 201:
                print(f"  Inserted batch {i//batch_size + 1}: {len(batch)} records")
            else:
                print(f"  Error inserting batch: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"  Exception inserting batch: {e}")

def migrate_trade_data():
    """Migrate trade data from CSV to Supabase"""
    print("Migrating trade data...")
    
    # Read trade log CSV
    csv_file = r'C:\Users\cream\OneDrive\Documents\LLM-Micro-Cap-trading-bot\trading_data\funds\Project Chimera\llm_trade_log.csv'
    df = pd.read_csv(csv_file)
    
    print(f"Trade records: {len(df)}")
    
    # Prepare data for Supabase
    records = []
    for row in df.to_dict('records'):
        record = {
            "fund": "Project Chimera",
            "ticker": str(row["Ticker"]),
            "shares": float(row["Shares"]),
            "price": float(row["Price"]),
            "cost_basis": float(row["Cost Basis"]),
            "pnl": float(row["PnL"]),
            "reason": str(row["Reason"]),
            "currency": str(row["Currency"]),
            "date": str(row["Date"])
        }
        records.append(record)
    
    # Insert into Supabase
    url = f"{os.getenv('SUPABASE_URL')}/rest/v1/trade_log"
    headers = {
        "apikey": os.getenv("SUPABASE_ANON_KEY"),
        "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
        "Content-Type": "application/json"
    }
    
    # Insert in batches
    batch_size = 50
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        try:
            response = requests.post(url, headers=headers, json=batch)
            if response.status_code == 201:
                print(f"  Inserted batch {i//batch_size + 1}: {len(batch)} records")
            else:
                print(f"  Error inserting batch: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"  Exception inserting batch: {e}")

def verify_migration():
    """Verify the migration was successful"""
    print("Verifying migration...")
    
    # Check portfolio positions
    url = f"{os.getenv('SUPABASE_URL')}/rest/v1/portfolio_positions"
    headers = {
        "apikey": os.getenv("SUPABASE_ANON_KEY"),
        "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            print(f"Portfolio positions: {len(data)} records")
            
            # Calculate total value
            total_value = 0
            for item in data:
                shares = float(item.get('shares', 0))
                price = float(item.get('price', 0))
                total_value += shares * price
            
            print(f"Total portfolio value: ${total_value:,.2f}")
            
            # Check for duplicates
            tickers = {}
            for item in data:
                ticker = item.get('ticker', '')
                tickers[ticker] = tickers.get(ticker, 0) + 1
            
            duplicates = {k: v for k, v in tickers.items() if v > 1}
            if duplicates:
                print(f"Duplicates found: {duplicates}")
            else:
                print("No duplicates found - migration successful!")
                
        else:
            print(f"Error verifying migration: {response.text}")
    except Exception as e:
        print(f"Exception verifying migration: {e}")

if __name__ == "__main__":
    print("Clean Migration Script")
    print("=" * 40)
    
    migrate_portfolio_data()
    migrate_trade_data()
    verify_migration()
    
    print("\nMigration complete!")
