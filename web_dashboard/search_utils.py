#!/usr/bin/env python3
"""
Search Utilities
================

Utility functions for formatting and processing SearXNG search results
for use in AI context and display.
"""

from typing import List, Dict, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependencies
def get_company_name_from_db(ticker: str) -> Optional[str]:
    """Get company name from database for a ticker symbol.
    
    Args:
        ticker: Ticker symbol (e.g., "XMA.TO", "AAPL")
        
    Returns:
        Company name if found in database, None otherwise
    """
    try:
        # Import here to avoid circular dependency
        from dashboard_data_clients import get_user_scoped_supabase_client

        client = get_user_scoped_supabase_client()
        if not client:
            logger.debug(f"Supabase client not available for company name lookup: {ticker}")
            return None
        
        # Query securities table for company name
        result = client.supabase.table("securities").select("company_name").eq("ticker", ticker.upper().strip()).execute()
        
        if result.data and len(result.data) > 0:
            company_name = result.data[0].get('company_name')
            if company_name and company_name.strip() and company_name != 'Unknown':
                logger.debug(f"Found company name for {ticker}: {company_name}")
                return company_name.strip()
        
        logger.debug(f"Company name not found in database for {ticker}")
        return None
        
    except Exception as e:
        logger.warning(f"Error fetching company name from database for {ticker}: {e}")
        return None


def format_search_results(search_data: Dict[str, Any], max_results: int = 10) -> str:
    """Format SearXNG search results for AI context.
    
    Args:
        search_data: Dictionary from SearXNG search response
        max_results: Maximum number of results to format
        
    Returns:
        Formatted string with search results
    """
    if 'error' in search_data:
        return f"Search error: {search_data['error']}"
    
    results = search_data.get('results', [])[:max_results]
    
    if not results:
        return "No search results found."
    
    formatted_parts = []
    formatted_parts.append(f"Web Search Results for: {search_data.get('query', 'Unknown query')}")
    total_count = search_data.get('number_of_results') or len(search_data.get('results', []))
    formatted_parts.append(f"Showing {len(results)} of {total_count} results")
    formatted_parts.append("")
    
    for i, result in enumerate(results, 1):
        title = result.get('title', 'No title')
        url = result.get('url', '')
        content = result.get('content', '')
        engine = result.get('engine', '')
        
        formatted_parts.append(f"{i}. {title}")
        if url:
            formatted_parts.append(f"   URL: {url}")
        if engine:
            formatted_parts.append(f"   Source: {engine}")
        if content:
            # Truncate long content
            max_content_length = 300
            if len(content) > max_content_length:
                content = content[:max_content_length] + "..."
            formatted_parts.append(f"   Summary: {content}")
        formatted_parts.append("")
    
    # Add answers if available
    answers = search_data.get('answers', [])
    if answers:
        formatted_parts.append("Quick Answers:")
        for answer in answers[:3]:  # Limit to 3 answers
            formatted_parts.append(f"  - {answer}")
        formatted_parts.append("")
    
    return "\n".join(formatted_parts)


def search_portfolio_tickers(
    searxng_client,
    tickers: List[str],
    search_type: str = "news",
    time_range: Optional[str] = "day",
    max_results_per_ticker: int = 5
) -> Dict[str, Any]:
    """Search for news about specific portfolio tickers.
    
    Args:
        searxng_client: SearXNGClient instance
        tickers: List of ticker symbols to search for
        search_type: Type of search ('news' or 'web')
        time_range: Time range filter ('day', 'week', 'month', 'year')
        max_results_per_ticker: Maximum results per ticker
        
    Returns:
        Dictionary mapping ticker to search results
    """
    if not searxng_client or not searxng_client.enabled:
        logger.warning("SearXNG client not available for ticker search")
        return {}
    
    ticker_results = {}
    
    for ticker in tickers:
        try:
            # Build search query for ticker
            query = f"{ticker} stock news"
            
            if search_type == "news":
                search_data = searxng_client.search_news(
                    query=query,
                    time_range=time_range,
                    max_results=max_results_per_ticker
                )
            else:
                search_data = searxng_client.search_web(
                    query=query,
                    time_range=time_range,
                    max_results=max_results_per_ticker
                )
            
            ticker_results[ticker] = search_data
            logger.info(f"Search completed for {ticker}: {len(search_data.get('results', []))} results")
            
        except Exception as e:
            logger.error(f"Error searching for {ticker}: {e}")
            ticker_results[ticker] = {
                'results': [],
                'query': f"{ticker} stock news",
                'error': str(e)
            }
    
    return ticker_results


def search_market_news(
    searxng_client,
    query: str = "stock market news today",
    time_range: Optional[str] = "day",
    max_results: int = 10
) -> Dict[str, Any]:
    """Search for general market news.
    
    Args:
        searxng_client: SearXNGClient instance
        query: Search query string
        time_range: Time range filter
        max_results: Maximum number of results
        
    Returns:
        Dictionary containing market news search results
    """
    if not searxng_client or not searxng_client.enabled:
        logger.warning("SearXNG client not available for market news search")
        return {
            'results': [],
            'query': query,
            'error': 'SearXNG not available'
        }
    
    try:
        return searxng_client.search_news(
            query=query,
            time_range=time_range,
            max_results=max_results
        )
    except Exception as e:
        logger.error(f"Error searching for market news: {e}")
        return {
            'results': [],
            'query': query,
            'error': str(e)
        }


def build_search_query(
    user_query: str, 
    tickers: Optional[List[str]] = None,
    company_name: Optional[str] = None,
    preserve_keywords: bool = True,
    research_intent: Optional[Dict[str, Any]] = None
) -> str:
    """Construct optimized search query from user input.
    
    Args:
        user_query: User's natural language query
        tickers: Optional list of ticker symbols to include
        company_name: Optional company name to include in search
        preserve_keywords: Whether to preserve important keywords from query
        research_intent: Optional research intent dictionary from detect_research_intent()
        
    Returns:
        Optimized search query string
    """
    query = user_query.strip()
    query_lower = query.lower()
    
    # Get intent subtype if available
    intent_subtype = None
    if research_intent:
        intent_subtype = research_intent.get('intent_subtype')
    
    # Extract and preserve important financial keywords
    important_keywords = []
    if preserve_keywords:
        financial_keywords = [
            'earnings', 'revenue', 'profit', 'loss', 'dividend', 'ipo',
            'merger', 'acquisition', 'financial', 'report', 'quarterly',
            'annual', 'guidance', 'forecast', 'analyst', 'rating', 'upgrade',
            'downgrade', 'price target', 'valuation', 'results', 'announcement',
            'outlook', 'performance', 'growth', 'decline'
        ]
        
        for keyword in financial_keywords:
            if keyword in query_lower:
                important_keywords.append(keyword)
    
    # Preserve important context words
    context_words = []
    if 'latest' in query_lower or 'recent' in query_lower:
        if 'latest' in query_lower:
            context_words.append('latest')
        if 'recent' in query_lower:
            context_words.append('recent')
    if 'today' in query_lower:
        context_words.append('today')
    if 'analysis' in query_lower:
        context_words.append('analysis')
    if 'outlook' in query_lower:
        context_words.append('outlook')
    if 'performance' in query_lower:
        context_words.append('performance')
    
    # Build query components
    query_parts = []
    
    # Add tickers first if provided
    if tickers:
        ticker_str = " ".join(tickers)
        query_parts.append(ticker_str)
    
    # Improve company name handling - use first 1-2 significant words
    if company_name and company_name.strip():
        company_words = company_name.strip().split()
        # Filter out common suffixes
        significant_words = [w for w in company_words if w.upper() not in 
                           ['INC', 'CORP', 'CORPORATION', 'LTD', 'LIMITED', 'GROUP', 
                            'HOLDINGS', 'COMPANY', 'CO', 'LLC']]
        if significant_words:
            # Use first 1-2 words max to keep query focused
            company_name_short = " ".join(significant_words[:2])
            # Only add if not already in query
            if company_name_short.lower() not in query_lower:
                query_parts.append(company_name_short)
    
    # Add intent-specific terms
    if intent_subtype == 'earnings':
        query_parts.extend(['earnings', 'report', 'results'])
    elif intent_subtype == 'analysis':
        query_parts.extend(['stock', 'analysis'])
        if 'price target' not in query_lower and 'analyst rating' not in query_lower:
            query_parts.append('price target')
    elif intent_subtype == 'research':
        query_parts.extend(['news', 'analysis'])
        if 'latest' not in query_lower:
            query_parts.append('latest')
    elif intent_subtype == 'compare':
        # For compare, add comparison terms if multiple tickers
        if tickers and len(tickers) >= 2:
            # Don't add "vs" here - it will be handled in the final query building
            query_parts.append('stock')
            query_parts.append('comparison')
    elif intent_subtype == 'market':
        query_parts.append('stock market')
        if 'today' not in query_lower and 'latest' not in query_lower:
            query_parts.append('today')
    
    # Add preserved important keywords (avoid duplicates)
    for keyword in important_keywords:
        if keyword not in [q.lower() for q in query_parts]:
            query_parts.append(keyword)
    
    # Add preserved context words
    for word in context_words:
        if word not in [q.lower() for q in query_parts]:
            query_parts.append(word)
    
    # Build final query based on intent and components
    if query_parts:
        # Remove duplicates while preserving order
        seen = set()
        unique_parts = []
        for part in query_parts:
            part_lower = part.lower()
            if part_lower not in seen:
                seen.add(part_lower)
                unique_parts.append(part)
        
        # Special handling for compare intent with multiple tickers
        if intent_subtype == 'compare' and tickers and len(tickers) >= 2:
            # Build comparison query: "TICKER1 vs TICKER2 stock comparison"
            ticker_str = " vs ".join(tickers)
            final_query = f"{ticker_str} stock comparison"
            # Add company names if available
            if company_name:
                company_words = company_name.strip().split()
                significant_words = [w for w in company_words if w.upper() not in 
                                   ['INC', 'CORP', 'CORPORATION', 'LTD', 'LIMITED', 'GROUP', 
                                    'HOLDINGS', 'COMPANY', 'CO', 'LLC']]
                if significant_words:
                    final_query += f" {' '.join(significant_words[:2])}"
            return final_query
        
        built_query = " ".join(unique_parts)
        
        # Add "news" if not already present and not a compare query
        if intent_subtype != 'compare' and 'news' not in built_query.lower() and 'news' not in query_lower:
            built_query += " news"
        
        return built_query
    
    # Fallback: enhance original query
    query = user_query.strip()
    
    # If tickers are provided, enhance the query
    if tickers:
        ticker_str = " ".join(tickers)
        # Add tickers to query if not already present
        if not any(ticker.lower() in query.lower() for ticker in tickers):
            query = f"{query} {ticker_str}"
    
    # Add company name if provided and not already in query
    if company_name and company_name.strip():
        company_words = company_name.strip().split()
        significant_words = [w for w in company_words if w.upper() not in 
                           ['INC', 'CORP', 'CORPORATION', 'LTD', 'LIMITED', 'GROUP', 
                            'HOLDINGS', 'COMPANY', 'CO', 'LLC']]
        if significant_words:
            company_name_short = " ".join(significant_words[:2])
            if company_name_short.lower() not in query.lower():
                query = f"{query} {company_name_short}"
    
    # Add stock/market context if not present
    market_keywords = ['stock', 'market', 'trading', 'earnings', 'news', 'financial']
    if not any(keyword in query.lower() for keyword in market_keywords):
        if intent_subtype == 'market':
            query = f"{query} stock market"
        else:
            query = f"{query} stock"
    
    return query


def filter_relevant_results(
    results: List[Dict[str, Any]], 
    ticker: str,
    company_name: Optional[str] = None,
    min_relevance_score: float = 0.3
) -> Dict[str, Any]:
    """Filter search results to only include those relevant to the ticker.
    
    Args:
        results: List of search result dictionaries
        ticker: Ticker symbol to match against (e.g., "XMA.TO" or "AAPL")
        company_name: Optional company name to check for
        min_relevance_score: Minimum relevance score (0-1) to include result
        
    Returns:
        Dictionary with:
        - 'relevant': List of relevant results (sorted by relevance score)
        - 'filtered_out': List of filtered-out results with scores
        - 'filtered_count': Number of filtered-out results
        - 'relevant_count': Number of relevant results
    """
    if not results:
        return {
            'relevant': [],
            'filtered_out': [],
            'filtered_count': 0,
            'relevant_count': 0
        }
    
    base_ticker = ticker.split('.')[0].upper()
    ticker_upper = ticker.upper()
    
    # Prepare company name for matching
    company_keywords = []
    if company_name:
        company_name_upper = company_name.upper()
        # Use full company name
        company_keywords.append(company_name_upper)
        # Also split into significant words if it's long
        words = [w for w in company_name_upper.split() if len(w) > 3 and w not in ['CORP', 'CORPORATION', 'INC', 'LTD', 'LIMITED', 'GROUP', 'HOLDINGS']]
        if words:
            company_keywords.extend(words)
            
    relevant_results = []
    filtered_out_results = []
    
    for result in results:
        title = result.get('title', '').upper()
        content = result.get('content', '').upper()
        url = result.get('url', '').upper()
        
        # Combine all text to check
        text_to_check = f"{title} {content} {url}"
        
        relevance_score = 0.0
        
        # Exact ticker match (with or without suffix) - highest priority
        if ticker_upper in text_to_check:
            relevance_score = 1.0
        # Base ticker match in title (high weight)
        elif base_ticker in title:
            relevance_score = 0.8
        # Company name match in title (high weight)
        elif company_name and any(kw in title for kw in company_keywords):
            relevance_score = 0.8
        # Base ticker match in content (medium weight)
        elif base_ticker in content:
            relevance_score = 0.6
        # Company name match in content (medium weight)
        elif company_name and any(kw in content for kw in company_keywords):
            relevance_score = 0.6
        # Base ticker match in URL (lower weight)
        elif base_ticker in url:
            relevance_score = 0.4
        
        # Always add the relevance score to the result
        result['relevance_score'] = relevance_score
        
        # Categorize as relevant or filtered out
        if relevance_score >= min_relevance_score:
            relevant_results.append(result)
        else:
            filtered_out_results.append(result)
    
    # Sort by relevance score descending
    relevant_results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
    filtered_out_results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
    
    return {
        'relevant': relevant_results,
        'filtered_out': filtered_out_results,
        'filtered_count': len(filtered_out_results),
        'relevant_count': len(relevant_results)
    }



def format_ticker_news_results(ticker_results: Dict[str, Dict[str, Any]]) -> str:
    """Format ticker-specific news search results.
    
    Args:
        ticker_results: Dictionary mapping ticker to search results
        
    Returns:
        Formatted string with ticker news
    """
    if not ticker_results:
        return "No ticker news available."
    
    formatted_parts = []
    formatted_parts.append("Recent News by Ticker:")
    formatted_parts.append("")
    
    for ticker, search_data in ticker_results.items():
        if 'error' in search_data:
            formatted_parts.append(f"{ticker}: Search error - {search_data['error']}")
            continue
        
        results = search_data.get('results', [])
        if not results:
            formatted_parts.append(f"{ticker}: No recent news found")
            continue
        
        formatted_parts.append(f"{ticker}:")
        for i, result in enumerate(results[:3], 1):  # Limit to 3 results per ticker
            title = result.get('title', 'No title')
            url = result.get('url', '')
            content = result.get('content', '')
            
            formatted_parts.append(f"  {i}. {title}")
            if url:
                formatted_parts.append(f"     {url}")
            if content:
                max_length = 200
                if len(content) > max_length:
                    content = content[:max_length] + "..."
                formatted_parts.append(f"     {content}")
        formatted_parts.append("")
    
    return "\n".join(formatted_parts)


def extract_tickers_from_query(query: str) -> List[str]:
    """Extract ticker symbols from a query string, including exchange suffixes.
    
    Looks for ticker symbols with patterns like:
    - XMA.TO, AAPL, TSLA (with or without exchange suffixes)
    - $XMA.TO, $AAPL (with $ prefix)
    - XMA.TO stock, AAPL earnings (in context)
    
    Args:
        query: User query string
        
    Returns:
        List of potential ticker symbols found (with suffixes preserved)
    """
    # Pattern for ticker symbols with optional exchange suffixes
    # Matches: 1-5 uppercase letters, optionally followed by .TO, .V, .CN, .NE, .TSX
    # Also handles $ prefix
    ticker_pattern = r'\$?([A-Z]{1,5}(?:\.(?:TO|V|CN|NE|TSX))?)\b'
    
    # Find all potential matches
    matches = re.findall(ticker_pattern, query)
    
    # Filter out common false positives (common words that look like tickers)
    false_positives = {
        'I', 'A', 'AN', 'THE', 'IS', 'IT', 'TO', 'BE', 'OR', 'OF', 'IN',
        'ON', 'AT', 'BY', 'FOR', 'AS', 'WE', 'HE', 'MY', 'ME', 'US', 'SO',
        'DO', 'GO', 'NO', 'UP', 'IF', 'AM', 'PM', 'OK', 'TV', 'PC', 'AI',
        'API', 'URL', 'HTTP', 'HTTPS', 'PDF', 'CSV', 'JSON', 'XML', 'HTML'
    }
    
    # Extract unique tickers, filtering false positives
    tickers = []
    for match in matches:
        # Extract base ticker (before .) for false positive check
        base_ticker = match.split('.')[0]
        if base_ticker not in false_positives and match not in tickers:
            tickers.append(match)
    
    return tickers


def detect_research_intent(query: str) -> Dict[str, Any]:
    """Detect research intent and classify the type of research needed.
    
    Args:
        query: User query string
        
    Returns:
        Dictionary with:
        - 'needs_search': bool - Whether search should be triggered
        - 'research_type': str - Type of research ('ticker', 'market', 'general', 'none')
        - 'intent_subtype': str - Specific intent subtype ('research', 'analysis', 'earnings', 'compare', 'market', None)
        - 'tickers': List[str] - Extracted ticker symbols
        - 'keywords': Dict[str, List[str]] - Relevant keywords found
    """
    query_lower = query.lower()
    
    # Check if query references existing context (don't search for these)
    context_reference_phrases = [
        'provided above',
        'based on the',
        'in the portfolio',
        'current holdings',
        'these holdings',
        'this portfolio',
        'from the data',
        'given the',
        'according to',
        'as shown',
        'in my portfolio',
        'my holdings',
        'the portfolio',
        'the holdings'
    ]
    
    # If query clearly references existing context, don't trigger search
    if any(phrase in query_lower for phrase in context_reference_phrases):
        return {
            'needs_search': False,
            'research_type': 'none',
            'intent_subtype': None,
            'tickers': [],
            'keywords': {
                'research': [],
                'market': [],
                'time': []
            }
        }
    
    # Extract tickers
    tickers = extract_tickers_from_query(query)
    
    # Detect specific intent subtypes
    intent_subtype = None
    
    # Compare intent: keywords "compare", "better investment", "vs", "versus"
    if any(word in query_lower for word in ['compare', 'better investment', ' vs ', ' versus ', 'comparison']):
        intent_subtype = 'compare'
    # Earnings intent: keywords "earnings", "earnings report", "quarterly"
    elif any(word in query_lower for word in ['earnings', 'earnings report', 'quarterly', 'financial results', 'q1', 'q2', 'q3', 'q4']):
        intent_subtype = 'earnings'
    # Analysis intent: keywords "analyze", "performance", "outlook"
    elif any(word in query_lower for word in ['analyze', 'analysis', 'performance', 'outlook', 'price target', 'analyst rating']):
        intent_subtype = 'analysis'
    # Research intent: keywords "research", "latest news and analysis"
    elif 'research' in query_lower or ('latest news' in query_lower and 'analysis' in query_lower):
        intent_subtype = 'research'
    # Market intent: keywords "market", "stock market", "financial markets"
    elif any(word in query_lower for word in ['market news', 'stock market', 'financial markets', 'market today']):
        intent_subtype = 'market'
    
    # Research keywords that indicate need for web search
    research_keywords = [
        'research', 'news', 'latest', 'recent', 'today', 'analysis',
        'analyze', 'information', 'find', 'search', 'what', 'how',
        'why', 'when', 'where', 'who', 'update', 'current', 'happening'
    ]
    
    # Market-related keywords
    market_keywords = [
        'market', 'stocks', 'trading', 'earnings', 'ipo', 'dividend',
        'sector', 'industry', 'company', 'corporation', 'financial',
        'investor', 'investment', 'portfolio', 'equity', 'shares'
    ]
    
    # Time-sensitive keywords
    time_keywords = [
        'today', 'this week', 'this month', 'recent', 'latest',
        'current', 'now', 'yesterday', 'last week', 'last month'
    ]
    
    # Find matching keywords
    found_research_keywords = [kw for kw in research_keywords if kw in query_lower]
    found_market_keywords = [kw for kw in market_keywords if kw in query_lower]
    found_time_keywords = [kw for kw in time_keywords if kw in query_lower]
    
    # Determine if search is needed
    needs_search = False
    research_type = 'none'
    
    # Always search if explicit research keywords
    if found_research_keywords:
        needs_search = True
        if tickers:
            research_type = 'ticker'
        elif found_market_keywords:
            research_type = 'market'
        else:
            research_type = 'general'
    
    # Search if tickers mentioned (likely asking about specific stocks)
    elif tickers:
        needs_search = True
        research_type = 'ticker'
    
    # Search for market/time-sensitive queries
    elif found_market_keywords and found_time_keywords:
        needs_search = True
        research_type = 'market'
    
    # Search for general market queries
    elif found_market_keywords:
        needs_search = True
        research_type = 'market'
    
    return {
        'needs_search': needs_search,
        'research_type': research_type,
        'intent_subtype': intent_subtype,
        'tickers': tickers,
        'keywords': {
            'research': found_research_keywords,
            'market': found_market_keywords,
            'time': found_time_keywords
        }
    }


def should_trigger_search(query: str, portfolio_tickers: Optional[List[str]] = None) -> bool:
    """Determine if a search should be triggered automatically based on query content.
    
    Args:
        query: User query string
        portfolio_tickers: Optional list of tickers in user's portfolio
        
    Returns:
        True if search should be triggered, False otherwise
    """
    intent = detect_research_intent(query)
    
    if not intent['needs_search']:
        return False
    
    # If tickers are mentioned, check if they're in portfolio
    if intent['tickers'] and portfolio_tickers:
        # If all mentioned tickers are in portfolio, might not need external search
        # But still search if research keywords are present
        all_in_portfolio = all(ticker in portfolio_tickers for ticker in intent['tickers'])
        if all_in_portfolio and not intent['keywords']['research']:
            # Only skip if no research keywords and all tickers in portfolio
            return False
    
    return True

