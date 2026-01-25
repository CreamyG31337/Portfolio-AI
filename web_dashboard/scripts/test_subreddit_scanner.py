
import sys
import os
from pathlib import Path
import logging

# Add project root to path
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

def list_ollama_models():
    try:
        import requests
        # Assume default URL or get from env
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        print(f"📡 Checking Ollama at {base_url}...")
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m['name'] for m in resp.json().get('models', [])]
            print(f"✅ Available Models: {models}")
            return models
        else:
            print(f"❌ Failed to list models: {resp.status_code}")
            return []
    except Exception as e:
        print(f"❌ Ollama list error: {e}")
        return []

def test_scanner():
    print("🚀 Starting Subreddit Scanner Test...")
    
    # Check models first
    list_ollama_models()
    
    try:
        from social_service import SocialSentimentService
        
        service = SocialSentimentService()

        
        # Test just one subreddit
        subreddit = "pennystocks"
        print(f"🔎 Scanning r/{subreddit} (limit=5)...")
        
        # Call the method directly
        opportunities = service.scan_subreddit_opportunities(
            subreddit=subreddit, 
            limit=5,    # Small limit for testing
            min_score=10 # Lower score threshold for testing
        )
        
        print(f"\n✅ Scan Complete. Found {len(opportunities)} opportunities:")
        print("="*50)
        
        for op in opportunities:
            print(f"🎫 Ticker: {op['ticker']}")
            print(f"📈 Confidence: {op['confidence']}")
            print(f"📝 Title: {op['title']}")
            print(f"🔗 URL: {op['url']}")
            print(f"💡 Reasoning: {op['reasoning'][:150]}...")
            print("-" * 30)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_scanner()
