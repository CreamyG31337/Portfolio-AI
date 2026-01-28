
import logging
import time
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path for utils imports
current_dir = Path(__file__).resolve().parent
if current_dir.name == 'scheduler':
    project_root = current_dir.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

def subreddit_scanner_job() -> None:
    """Scan investment subreddits for deep-dive due diligence opportunities.
    
    Target Subreddits:
    - r/pennystocks
    - r/RobinHoodPennyStocks
    - r/microcap
    - r/Shortsqueeze
    
    Process:
    1. Fetches top posts (score > 20)
    2. Analyzes post + top comments with AI
    3. Extracts tickers with actual reasoning
    4. Saves to research repository
    
    Robots.txt enforcement: Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.
    When enabled, checks robots.txt before accessing Reddit API.
    """
    job_id = 'subreddit_scanner'
    start_time = time.time()
    
    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        from scheduler.scheduler_core import log_job_execution
        from social_service import SocialSentimentService
        from research_repository import ResearchRepository
        
        logger.info("Starting Subreddit Scanner job...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)
        
        # Initialize services
        social_service = SocialSentimentService() # Requires env vars setup (Ollama, etc)
        research_repo = ResearchRepository()
        
        subreddits = [
            'pennystocks', 
            'RobinHoodPennyStocks', 
            'microcap', 
            'Shortsqueeze',
            'biotechplays',       # High risk/reward binary events
            'CanadianPennyStocks', # Relevant for TSX/TSX-V
            'Undervalued',        # Value plays
            'BayStreetBets'       # Canadian momentum
        ]
        total_found = 0
        summary_msg = []
        
        for sub in subreddits:
            try:
                findings = social_service.scan_subreddit_opportunities(sub, limit=15, min_score=20)
                
                if findings:
                    logger.info(f"✅ Found {len(findings)} opportunities in r/{sub}")
                    for item in findings:
                        # Save to repository
                        # We map:
                        # - title -> title
                        # - url -> url
                        # - reasoning -> summary
                        # - confidence -> relevance_score (mapped)
                        
                        confidence = item.get('confidence', 0.5)
                        ticker = item.get('ticker')
                        
                        article_id = research_repo.save_article(
                            tickers=[ticker],
                            sector="Reddit Discovery",
                            article_type="Reddit Discovery",
                            title=f"[{sub}] {item.get('title')}",
                            url=item.get('url'),
                            summary=f"AI Analysis: {item.get('reasoning')}",
                            content=item.get('full_text', f"Full text unavailable. Score: {item.get('score')}"),
                            published_at=datetime.now(timezone.utc),
                            relevance_score=confidence,
                            source="Reddit"
                        )
                        
                        if article_id:
                            total_found += 1
                            logger.info(f"  💾 Saved: {ticker} from r/{sub}")
                    
                    summary_msg.append(f"r/{sub}: {len(findings)}")
                else:
                    logger.info(f"r/{sub}: No opportunities found")
                    summary_msg.append(f"r/{sub}: 0")
                    
                # Sleep between subreddits to be nice
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"Error processing r/{sub}: {e}")
                summary_msg.append(f"r/{sub}: Error")
        
        # Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Scanner finished. Found {total_found} opportunities. Details: {', '.join(summary_msg)}"
        
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
        logger.info(f"✅ {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        from utils.job_tracking import log_job_execution, mark_job_failed
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        mark_job_failed(job_id, target_date, None, str(e), duration_ms=duration_ms)
        logger.error(f"❌ Subreddit Scanner job failed: {e}", exc_info=True)
