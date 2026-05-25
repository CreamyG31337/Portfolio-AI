#!/usr/bin/env python3
"""
Test Single Article Processing
===============================

Test processing a single article URL through the research job pipeline.
This mimics what the research jobs do but for a single URL.
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_single_article(url: str, save_to_db: bool = False):
    """Test processing a single article through the research pipeline."""
    print(f"\n{'='*80}")
    print(f"Testing Single Article Processing")
    print(f"URL: {url}")
    print(f"Save to DB: {save_to_db}")
    print(f"{'='*80}\n")
    
    try:
        from research_utils import extract_article_content, extract_source_from_url
        from research_repository import ResearchRepository
        from ollama_client import get_ollama_client
        from scheduler.jobs_common import calculate_relevance_score
        from supabase_client import SupabaseClient
        
        # Step 1: Extract content
        print("Step 1: Extracting article content...")
        extracted = extract_article_content(url)
        
        if not extracted.get('success'):
            error = extracted.get('error', 'unknown')
            print(f"❌ Extraction failed: {error}")
            
            if extracted.get('archive_submitted'):
                print("✅ URL was submitted to archive service")
                if save_to_db:
                    print("   Article will be saved for archive retry job")
            
            # If archive was submitted and we want to save, save it
            if save_to_db and extracted.get('archive_submitted'):
                repo = ResearchRepository()
                source = extract_source_from_url(url)
                title = extracted.get('title', 'Paywalled Article')
                
                article_id = repo.save_article(
                    tickers=None,
                    sector=None,
                    article_type="market_news",
                    title=title,
                    url=url,
                    summary="[Paywalled - Submitted to archive for processing]",
                    content="[Paywalled - Submitted to archive for processing]",
                    source=source,
                    published_at=None,
                    relevance_score=0.0,
                    embedding=None
                )
                
                if article_id:
                    repo.mark_archive_submitted(article_id, url)
                    print(f"✅ Saved article to database (ID: {article_id})")
                    print(f"   Archive retry job will process it later")
            
            return
        
        content = extracted.get('content', '')
        title = extracted.get('title', 'Untitled')
        source = extracted.get('source', 'Unknown')
        
        print(f"✅ Content extracted successfully")
        print(f"   Title: {title}")
        print(f"   Source: {source}")
        print(f"   Content length: {len(content)} characters")
        
        if len(content) < 200:
            print(f"⚠️  Content seems too short, may be incomplete")
        
        # Step 2: Generate AI summary (if Ollama available)
        print(f"\nStep 2: Generating AI summary...")
        ollama_client = get_ollama_client()
        
        summary = None
        summary_data = {}
        extracted_tickers = []
        extracted_sector = None
        embedding = None
        
        if ollama_client:
            try:
                summary_data = ollama_client.generate_summary(content)
                
                if isinstance(summary_data, str):
                    summary = summary_data
                elif isinstance(summary_data, dict) and summary_data:
                    summary = summary_data.get("summary", "")
                    
                    # Extract tickers with real-company validation
                    from ticker_validator import extract_and_validate_tickers
                    extracted_tickers = extract_and_validate_tickers(
                        summary_data, title, content,
                    )

                    # Extract sector
                    sectors = summary_data.get("sectors", [])
                    if sectors:
                        extracted_sector = sectors[0]
                
                # Generate embedding
                embedding = ollama_client.generate_embedding(content)
                
                print(f"✅ AI analysis completed")
                if extracted_tickers:
                    print(f"   Tickers: {', '.join(extracted_tickers)}")
                if extracted_sector:
                    print(f"   Sector: {extracted_sector}")
                if summary:
                    print(f"   Summary: {summary[:100]}...")
                
            except Exception as e:
                print(f"⚠️  AI analysis failed: {e}")
        else:
            print(f"ℹ️  Ollama not available, skipping AI analysis")
        
        # Step 3: Calculate relevance score
        print(f"\nStep 3: Calculating relevance score...")
        
        # Get owned tickers for relevance scoring
        owned_tickers = set()
        try:
            client = SupabaseClient(use_service_role=True)
            funds_result = client.supabase.table("funds").select("name").eq("is_production", True).execute()
            
            if funds_result.data:
                prod_funds = [f['name'] for f in funds_result.data]
                positions_result = client.supabase.table("latest_positions").select("ticker").in_("fund", prod_funds).execute()
                if positions_result.data:
                    owned_tickers = set(pos['ticker'] for pos in positions_result.data)
        except Exception as e:
            logger.debug(f"Could not fetch owned tickers: {e}")
        
        relevance_score = calculate_relevance_score(
            extracted_tickers if extracted_tickers else [],
            extracted_sector,
            owned_tickers=list(owned_tickers) if owned_tickers else None
        )
        
        print(f"✅ Relevance score: {relevance_score:.2f}")
        
        # Step 4: Save to database (if requested)
        if save_to_db:
            print(f"\nStep 4: Saving to database...")
            repo = ResearchRepository()
            
            # Check if already exists
            if repo.article_exists(url):
                print(f"⚠️  Article already exists in database (skipping)")
            else:
                article_id = repo.save_article(
                    tickers=extracted_tickers if extracted_tickers else None,
                    sector=extracted_sector,
                    article_type="market_news",
                    title=title,
                    url=url,
                    summary=summary,
                    content=content,
                    source=source,
                    published_at=extracted.get('published_at'),
                    relevance_score=relevance_score,
                    embedding=embedding,
                    claims=summary_data.get("claims") if isinstance(summary_data, dict) else None,
                    fact_check=summary_data.get("fact_check") if isinstance(summary_data, dict) else None,
                    conclusion=summary_data.get("conclusion") if isinstance(summary_data, dict) else None,
                    sentiment=summary_data.get("sentiment") if isinstance(summary_data, dict) else None,
                    sentiment_score=summary_data.get("sentiment_score") if isinstance(summary_data, dict) else None
                )
                
                if article_id:
                    print(f"✅ Article saved to database (ID: {article_id})")
                else:
                    print(f"❌ Failed to save article")
        else:
            print(f"\nStep 4: Skipping database save (use --save to save)")
        
        print(f"\n{'='*80}")
        print("Test completed successfully!")
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Test processing a single article URL')
    parser.add_argument('url', help='URL of article to test')
    parser.add_argument('--save', action='store_true', help='Save article to database')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    test_single_article(args.url, save_to_db=args.save)


if __name__ == "__main__":
    main()

