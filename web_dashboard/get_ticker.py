import os
from supabase import create_client
from dotenv import load_dotenv

# Load .env from parent directory
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

def get_ticker():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Error: Missing credentials")
        return

    supabase = create_client(url, key)
    # Get a ticker from portfolio_positions for TFSA
    res = supabase.table("portfolio_positions").select("ticker").eq("fund", "TFSA").limit(1).execute()
    if res.data:
        print(f"Ticker in TFSA: {res.data[0]['ticker']}")
    else:
        print("No ticker found in TFSA")

if __name__ == "__main__":
    get_ticker()
