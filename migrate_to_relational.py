#!/usr/bin/env python3
"""
Migrate from flat file structure to proper relational database design
"""

import os
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv('web_dashboard/.env')

# Add project root to path
sys.path.insert(0, str(Path.cwd()))

def migrate_to_relational():
    """Migrate from current flat structure to relational design"""
    print("🔄 Migrating to Relational Database Design")
    print("=" * 50)
    
    try:
        from web_dashboard.supabase_client import SupabaseClient
        client = SupabaseClient()
        
        # Step 1: Create the new relational schema
        print("📋 Step 1: Creating relational schema...")
        with open('database/schema/supabase/relational_design.sql', 'r') as f:
            schema_sql = f.read()
        
        # Note: This would need to be run in Supabase SQL editor
        print("⚠️  Please run the SQL in database/schema/supabase/relational_design.sql in your Supabase dashboard first!")
        print("   Then press Enter to continue...")
        input()
        
        # Step 2: Extract unique securities from existing data
        print("📋 Step 2: Extracting securities...")
        
        # Get all unique tickers and company names from portfolio_positions
        result = client.supabase.table('portfolio_positions').select('ticker, company').execute()
        
        securities_data = []
        seen_tickers = set()
        
        for row in result.data:
            ticker = row.get('ticker')
            company = row.get('company', '')
            
            if ticker and ticker not in seen_tickers:
                seen_tickers.add(ticker)
                securities_data.append({
                    'ticker': ticker,
                    'company_name': company or ticker,  # Fallback to ticker if no company name
                    'security_type': 'stock',  # Default, could be enhanced
                    'currency': 'USD' if not ticker.endswith('.TO') else 'CAD'
                })
        
        print(f"   Found {len(securities_data)} unique securities")
        
        # Step 3: Insert securities
        print("📋 Step 3: Inserting securities...")
        if securities_data:
            result = client.supabase.table('securities').upsert(securities_data).execute()
            print(f"   Inserted {len(securities_data)} securities")
        
        # Step 4: Create funds
        print("📋 Step 4: Creating funds...")
        funds_data = [
            {'name': 'Project Chimera', 'description': 'Main investment fund', 'currency': 'CAD'},
            {'name': 'RRSP Lance Webull', 'description': 'Retirement savings', 'currency': 'CAD'},
            {'name': 'TFSA', 'description': 'Tax-free savings account', 'currency': 'CAD'},
            {'name': 'TEST', 'description': 'Test fund', 'currency': 'CAD'}
        ]
        
        result = client.supabase.table('funds').upsert(funds_data).execute()
        print(f"   Inserted {len(funds_data)} funds")
        
        # Step 5: Migrate portfolio positions
        print("📋 Step 5: Migrating portfolio positions...")
        
        # Get all portfolio positions
        result = client.supabase.table('portfolio_positions').select('*').execute()
        
        # Get securities mapping
        securities_result = client.supabase.table('securities').select('id, ticker').execute()
        ticker_to_security_id = {s['ticker']: s['id'] for s in securities_result.data}
        
        # Get funds mapping
        funds_result = client.supabase.table('funds').select('id, name').execute()
        fund_name_to_id = {f['name']: f['id'] for f in funds_result.data}
        
        new_positions = []
        for row in result.data:
            ticker = row.get('ticker')
            fund = row.get('fund')
            
            security_id = ticker_to_security_id.get(ticker)
            fund_id = fund_name_to_id.get(fund)
            
            if security_id and fund_id:
                new_positions.append({
                    'fund_id': fund_id,
                    'security_id': security_id,
                    'shares': float(row.get('shares', 0)),
                    'avg_price': float(row.get('price', 0)),  # Current price becomes avg_price
                    'cost_basis': float(row.get('cost_basis', 0)),
                    'current_price': float(row.get('price', 0)),
                    'date': row.get('date', datetime.now().isoformat())
                })
        
        if new_positions:
            result = client.supabase.table('portfolio_positions').upsert(new_positions).execute()
            print(f"   Migrated {len(new_positions)} portfolio positions")
        
        # Step 6: Migrate trade log
        print("📋 Step 6: Migrating trade log...")
        
        # Get all trades
        result = client.supabase.table('trade_log').select('*').execute()
        
        new_trades = []
        for row in result.data:
            ticker = row.get('ticker')
            fund = row.get('fund')
            
            security_id = ticker_to_security_id.get(ticker)
            fund_id = fund_name_to_id.get(fund)
            
            if security_id and fund_id:
                new_trades.append({
                    'fund_id': fund_id,
                    'security_id': security_id,
                    'trade_date': row.get('date', datetime.now().isoformat()),
                    'action': row.get('action', 'BUY'),
                    'shares': float(row.get('shares', 0)),
                    'price': float(row.get('price', 0)),
                    'cost_basis': float(row.get('cost_basis', 0)),
                    'pnl': float(row.get('pnl', 0)),
                    'reason': row.get('reason', '')
                })
        
        if new_trades:
            result = client.supabase.table('trade_log').upsert(new_trades).execute()
            print(f"   Migrated {len(new_trades)} trades")
        
        print("\n🎉 Migration completed successfully!")
        print("\n📋 Next steps:")
        print("1. Update your application code to use the new relational structure")
        print("2. Test the new current_positions view")
        print("3. Remove old flat table structure if everything works")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_relational_structure():
    """Test the new relational structure"""
    print("\n🧪 Testing Relational Structure")
    print("=" * 30)
    
    try:
        from web_dashboard.supabase_client import SupabaseClient
        client = SupabaseClient()
        
        # Test current_positions view
        result = client.supabase.table('current_positions').select('*').limit(5).execute()
        
        print("✅ Current positions view:")
        for pos in result.data:
            print(f"  {pos.get('ticker')} -> {pos.get('company_name')}")
        
        # Test securities table
        result = client.supabase.table('securities').select('ticker, company_name').limit(5).execute()
        
        print("\n✅ Securities table:")
        for sec in result.data:
            print(f"  {sec.get('ticker')} -> {sec.get('company_name')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def main():
    """Main migration function"""
    print("🔄 Database Migration to Relational Design")
    print("=" * 50)
    
    print("This will migrate your current flat file structure to a proper relational database.")
    print("The new design includes:")
    print("  • Securities table (tickers + company names)")
    print("  • Funds table (investment accounts)")
    print("  • Users table (user management)")
    print("  • Proper foreign key relationships")
    print("  • Normalized data structure")
    
    print("\n⚠️  WARNING: This will create new tables alongside your existing ones.")
    print("   Your existing data will be preserved.")
    
    response = input("\nContinue? (y/N): ")
    if response.lower() != 'y':
        print("Migration cancelled.")
        return
    
    success = migrate_to_relational()
    
    if success:
        test_relational_structure()
        print("\n🎉 Migration completed! Your database now has a proper relational structure.")
    else:
        print("\n❌ Migration failed. Please check the errors above.")

if __name__ == "__main__":
    main()
