#!/usr/bin/env python3
"""
Fund Thesis Update Job
======================

AI-driven weekly job to update fund investment thesis based on actual portfolio composition.

The thesis is a living philosophy that:
- Reflects what the portfolio actually holds
- Is appropriate for the account type (TFSA = aggressive/growth, RRSP = long-term/conservative)
- Provides gentle guidance without rigid rules
- Helps justify and contextualize investment decisions

Runs weekly (Sunday evening recommended).

=== AI PROVIDER CONFIGURATION ===
IMPORTANT: This job uses GLM (Zhipu/Z.AI) instead of Ollama for AI generation.
This allows it to run WITHOUT the global AI lock, so it won't conflict with other
Ollama-based AI jobs (ticker analysis, congress trades, etc.).

If you no longer have a GLM API key, you'll need to:
1. Change generate_thesis() to use Ollama instead of GLM
2. Re-enable the AI lock check in thesis_update_job()
3. Look at how other jobs (e.g., jobs_ticker_analysis.py) call Ollama

GLM API key is loaded from: ZHIPU_API_KEY env var or .secrets/zhipu_api_key file
"""

import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

# Load .env file from project root for local development (ZHIPU_API_KEY, etc.)
# In production (Docker), env vars are set directly via Woodpecker secrets
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # scheduler -> web_dashboard -> project root
load_dotenv(_PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)


def thesis_update_job() -> None:
    """Update fund thesis using AI analysis of actual portfolio composition.

    NOTE: This job uses GLM (not Ollama) and does NOT use the global AI lock.
    This allows it to run concurrently with other Ollama-based AI jobs.
    See module docstring for details on switching back to Ollama if needed.
    """
    job_id = 'thesis_update'
    start_time = time.time()

    # Import dependencies here to avoid circular imports
    from supabase_client import SupabaseClient
    from glm_config import get_zhipu_api_key, ZHIPU_BASE_URL

    # Job tracking imports
    try:
        from utils.job_tracking import (
            mark_job_completed,
            mark_job_failed,
            mark_job_started,
        )
        target_date = datetime.now(timezone.utc).date()
    except ImportError:
        # Fallback for standalone testing
        def mark_job_started(job_id, target_date): pass
        def mark_job_completed(job_id, target_date, *args, **kwargs): pass
        def mark_job_failed(job_id, target_date, *args, **kwargs): pass
        target_date = datetime.now(timezone.utc).date()

    # NOTE: AI lock is DISABLED for this job because we use GLM (not Ollama).
    # GLM is a separate API that doesn't compete with local Ollama resources.
    # If you switch back to Ollama, re-enable this block:
    #
    # from utils.job_tracking import get_running_ai_job
    # running_ai = get_running_ai_job(exclude_job_name=job_id)
    # if running_ai:
    #     logger.info(f"AI lock active: {running_ai} is running. Skipping {job_id}.")
    #     return

    try:
        mark_job_started(job_id, target_date)
    except Exception as e:
        logger.warning(f"Could not mark job started: {e}")

    logger.info("🎯 Starting Fund Thesis Update Job (using GLM API)...")

    # Check GLM API key
    glm_api_key = get_zhipu_api_key()
    if not glm_api_key:
        duration_ms = int((time.time() - start_time) * 1000)
        message = "GLM API key not available. Set ZHIPU_API_KEY or save via AI Settings."
        mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        logger.error(f"❌ {message}")
        return

    # Initialize Supabase client
    try:
        supabase = SupabaseClient(use_service_role=True)
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Failed to initialize Supabase client: {e}"
        mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        logger.error(f"❌ {message}")
        return

    # Get production funds only (not TEST_ funds)
    try:
        funds_result = supabase.supabase.table('funds') \
            .select('name, fund_type, description') \
            .eq('is_production', True) \
            .execute()
        funds = funds_result.data or []
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Failed to fetch funds: {e}"
        mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        logger.error(f"❌ {message}")
        return

    if not funds:
        duration_ms = int((time.time() - start_time) * 1000)
        message = "No funds found"
        mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
        logger.info(f"ℹ️ {message}")
        return

    logger.info(f"Found {len(funds)} funds to process")

    processed = 0
    failed = 0

    for fund_row in funds:
        fund_name = fund_row['name']
        fund_type = fund_row.get('fund_type', 'investment')
        fund_description = fund_row.get('description', '')

        # Skip test funds (TEST_* pattern) to avoid wasting API calls
        # Only process real funds: TFSA, RRSP, Project Chimera, etc.
        if fund_name.startswith('TEST_') or fund_name == 'TEST':
            logger.debug(f"⏭️  Skipping test fund: {fund_name}")
            continue

        try:
            logger.info(f"📝 Processing thesis for fund: {fund_name}")

            # Gather fund data
            fund_data = gather_fund_data(supabase, fund_name, fund_type, fund_description)

            if not fund_data.get('positions'):
                logger.info(f"⏭️  Skipping {fund_name}: no positions")
                continue

            # Generate thesis with AI (uses GLM, not Ollama)
            thesis = generate_thesis(fund_data)

            if thesis:
                # Save to database
                save_thesis(supabase, fund_name, thesis)
                processed += 1
                logger.info(f"✅ Updated thesis for {fund_name}")

                # Rate limit protection: wait 3s between successful API calls
                # GLM has strict rate limits on the coding API
                time.sleep(3)
            else:
                failed += 1
                logger.warning(f"❌ Failed to generate thesis for {fund_name}")

        except Exception as e:
            failed += 1
            logger.error(f"❌ Error processing {fund_name}: {e}", exc_info=True)

    duration_ms = int((time.time() - start_time) * 1000)
    message = f"Processed {processed} funds, {failed} failed"

    try:
        mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
    except Exception:
        pass

    logger.info(f"🎉 Thesis Update Job completed: {message}")


def gather_fund_data(
    supabase,
    fund_name: str,
    fund_type: str,
    fund_description: str
) -> Dict[str, Any]:
    """Gather all relevant data for thesis generation.

    Args:
        supabase: Supabase client
        fund_name: Name of the fund
        fund_type: Type of fund (e.g., 'investment', 'tfsa', 'rrsp')
        fund_description: Fund description

    Returns:
        Dict with fund data for AI analysis
    """
    # Detect account type from fund name or type
    account_type = detect_account_type(fund_name, fund_type)

    # Get latest positions with security metadata
    positions = get_positions_with_metadata(supabase, fund_name)

    # Calculate sector/industry breakdown
    sector_breakdown = calculate_sector_breakdown(positions)

    # Get recent performance (30 days)
    performance = get_fund_performance(supabase, fund_name)

    # Get top/bottom performers
    top_performers, bottom_performers = get_position_performance(positions)

    return {
        'fund_name': fund_name,
        'fund_type': fund_type,
        'fund_description': fund_description,
        'account_type': account_type,
        'positions': positions,
        'sector_breakdown': sector_breakdown,
        'performance': performance,
        'top_performers': top_performers,
        'bottom_performers': bottom_performers,
        'total_value': sum(p.get('total_value_base', 0) or 0 for p in positions),
        'position_count': len(positions),
    }


def detect_account_type(fund_name: str, fund_type: str) -> Dict[str, Any]:
    """Detect account type and its characteristics.

    Args:
        fund_name: Name of the fund
        fund_type: Type field from database

    Returns:
        Dict with account type info and investment philosophy hints
    """
    name_lower = fund_name.lower()
    type_lower = fund_type.lower()

    if 'tfsa' in name_lower or 'tfsa' in type_lower:
        return {
            'type': 'TFSA',
            'description': 'Tax-Free Savings Account',
            'philosophy': (
                'TFSA accounts are ideal for aggressive growth strategies. '
                'All gains are completely tax-free, making this the perfect vehicle for '
                'high-growth investments, frequent trading, and capturing quick returns. '
                'Capital gains over dividends are preferred to maximize tax-free appreciation.'
            ),
            'style': 'aggressive',
            'horizon': 'short to medium term',
        }
    elif 'rrsp' in name_lower or 'rrsp' in type_lower:
        return {
            'type': 'RRSP',
            'description': 'Registered Retirement Savings Plan',
            'philosophy': (
                'RRSP accounts are designed for long-term wealth building toward retirement. '
                'The focus should be on steady growth, quality companies, and dividend compounding. '
                'Tax-deferred growth means patience is rewarded. Avoid frequent trading as withdrawals '
                'are taxed as income. Think 10-20+ year horizon.'
            ),
            'style': 'conservative to moderate',
            'horizon': 'long term (10-20+ years)',
        }
    else:
        return {
            'type': 'General Investment',
            'description': 'Non-registered investment account',
            'philosophy': (
                'This is a flexible investment account with no special tax treatment. '
                'Strategy can be tailored to specific goals - growth, income, or balanced. '
                'Consider tax efficiency with capital gains vs dividends.'
            ),
            'style': 'flexible',
            'horizon': 'varies by goal',
        }


def get_positions_with_metadata(supabase, fund_name: str) -> List[Dict[str, Any]]:
    """Get current positions joined with security metadata.

    Args:
        supabase: Supabase client
        fund_name: Name of the fund

    Returns:
        List of position dicts with security metadata
    """
    try:
        # Get latest date for this fund
        date_result = supabase.supabase.table('portfolio_positions') \
            .select('date') \
            .eq('fund', fund_name) \
            .order('date', desc=True) \
            .limit(1) \
            .execute()

        if not date_result.data:
            return []

        latest_date = date_result.data[0]['date']

        # Get positions for latest date
        positions_result = supabase.supabase.table('portfolio_positions') \
            .select('ticker, shares, price, cost_basis, pnl, total_value, currency, '
                    'total_value_base, cost_basis_base, pnl_base') \
            .eq('fund', fund_name) \
            .eq('date', latest_date) \
            .execute()

        positions = positions_result.data or []

        # Get security metadata for all tickers
        tickers = [p['ticker'] for p in positions]
        if tickers:
            securities_result = supabase.supabase.table('securities') \
                .select('ticker, company_name, sector, industry, description') \
                .in_('ticker', tickers) \
                .execute()

            securities_map = {s['ticker']: s for s in (securities_result.data or [])}

            # Merge security data into positions
            for position in positions:
                security = securities_map.get(position['ticker'], {})
                position['company_name'] = security.get('company_name', position['ticker'])
                position['sector'] = security.get('sector', 'Unknown')
                position['industry'] = security.get('industry', 'Unknown')
                position['security_description'] = security.get('description', '')

        return positions

    except Exception as e:
        logger.error(f"Error fetching positions for {fund_name}: {e}")
        return []


def calculate_sector_breakdown(positions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Calculate allocation breakdown by sector.

    Args:
        positions: List of position dicts

    Returns:
        Dict of sector -> {value, percentage, tickers}
    """
    total_value = sum(p.get('total_value_base', 0) or 0 for p in positions)
    if total_value == 0:
        return {}

    sectors: Dict[str, Dict[str, Any]] = {}

    for position in positions:
        sector = position.get('sector', 'Unknown') or 'Unknown'
        value = position.get('total_value_base', 0) or 0
        ticker = position.get('ticker', '')
        company = position.get('company_name', ticker)

        if sector not in sectors:
            sectors[sector] = {
                'value': 0,
                'percentage': 0,
                'tickers': [],
            }

        sectors[sector]['value'] += value
        sectors[sector]['tickers'].append({
            'ticker': ticker,
            'company': company,
            'value': value,
            'pnl_pct': calculate_pnl_percentage(position),
        })

    # Calculate percentages and sort tickers within each sector
    for sector in sectors:
        sectors[sector]['percentage'] = round(sectors[sector]['value'] / total_value * 100, 1)
        sectors[sector]['tickers'].sort(key=lambda x: x['value'], reverse=True)

    return dict(sorted(sectors.items(), key=lambda x: x[1]['value'], reverse=True))


def calculate_pnl_percentage(position: Dict[str, Any]) -> float:
    """Calculate P&L percentage for a position."""
    cost_basis = position.get('cost_basis_base', 0) or position.get('cost_basis', 0) or 0
    pnl = position.get('pnl_base', 0) or position.get('pnl', 0) or 0

    if cost_basis > 0:
        return round(pnl / cost_basis * 100, 1)
    return 0.0


def get_fund_performance(supabase, fund_name: str) -> Dict[str, Any]:
    """Get recent fund performance metrics.

    Args:
        supabase: Supabase client
        fund_name: Name of the fund

    Returns:
        Dict with performance metrics
    """
    try:
        # Get last 30 days of performance from performance_metrics table
        result = supabase.supabase.table('performance_metrics') \
            .select('date, total_value, performance_pct, unrealized_pnl') \
            .eq('fund', fund_name) \
            .order('date', desc=True) \
            .limit(30) \
            .execute()

        data = result.data or []

        if not data:
            return {}

        latest = data[0]
        oldest = data[-1] if len(data) > 1 else data[0]

        # Calculate period return from performance_pct difference
        period_return = 0
        if len(data) > 1:
            latest_pct = float(latest.get('performance_pct', 0) or 0)
            oldest_pct = float(oldest.get('performance_pct', 0) or 0)
            period_return = latest_pct - oldest_pct

        return {
            'current_value': float(latest.get('total_value', 0) or 0),
            'period_return_pct': period_return,
            'unrealized_pnl': float(latest.get('unrealized_pnl', 0) or 0),
            'days_covered': len(data),
        }

    except Exception as e:
        logger.warning(f"Error fetching performance for {fund_name}: {e}")
        return {}


def get_position_performance(positions: List[Dict[str, Any]]) -> tuple:
    """Get top and bottom performers from positions.

    Args:
        positions: List of position dicts

    Returns:
        Tuple of (top_performers, bottom_performers) lists
    """
    # Calculate P&L % for each position
    performers = []
    for p in positions:
        pnl_pct = calculate_pnl_percentage(p)
        performers.append({
            'ticker': p.get('ticker', ''),
            'company': p.get('company_name', p.get('ticker', '')),
            'pnl_pct': pnl_pct,
            'value': p.get('total_value_base', 0) or 0,
        })

    # Sort by P&L %
    performers.sort(key=lambda x: x['pnl_pct'], reverse=True)

    top = performers[:5] if len(performers) >= 5 else performers
    bottom = performers[-5:] if len(performers) >= 5 else []
    bottom.reverse()  # Worst first

    return top, bottom


def generate_thesis(fund_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Generate investment thesis using GLM AI.

    NOTE: This function uses GLM (Zhipu/Z.AI) API instead of Ollama.
    If you need to switch back to Ollama, see the commented-out Ollama version below.

    Args:
        fund_data: Fund data dict from gather_fund_data

    Returns:
        Dict with thesis title, overview, and pillars, or None on failure
    """
    from glm_config import get_zhipu_api_key, ZHIPU_BASE_URL

    # Build context for AI
    context = format_thesis_context(fund_data)

    # Build prompt
    prompt = build_thesis_prompt(fund_data)

    system_prompt = """You are an investment strategist helping to articulate portfolio investment thesis.
Your job is to analyze the current portfolio composition and generate a clear, philosophical investment thesis.

Important guidelines:
- The thesis should DESCRIBE what the portfolio IS, not prescribe rigid rules
- Avoid specific percentages, stop-losses, or technical indicators in rules
- Focus on themes, philosophy, and general guidance
- The tone should be confident but flexible
- Pillars should reflect natural groupings in the actual holdings
- Each pillar should explain WHY these holdings make sense together

You must respond with valid JSON only, no markdown or explanation outside the JSON."""

    # Combine context and prompt
    full_prompt = f"{context}\n\n{prompt}"

    api_key = get_zhipu_api_key()
    if not api_key:
        logger.error("GLM API key not available")
        return None

    # GLM API call (OpenAI-compatible format)
    # Using glm-4-plus for best quality, or glm-4.5-air for faster response
    url = f"{ZHIPU_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "glm-4-plus",  # Best quality model
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
        # GLM doesn't have json_mode, but the system prompt instructs JSON output
    }

    # Retry logic with exponential backoff for rate limiting (429)
    # GLM coding API has strict rate limits - be conservative
    max_retries = 5
    base_delay = 15  # seconds (longer delay for GLM's strict limits)

    for attempt in range(max_retries):
        try:
            logger.info(f"Calling GLM API for thesis generation (attempt {attempt + 1}/{max_retries})...")
            response = requests.post(url, json=payload, headers=headers, timeout=120)

            # Handle rate limiting with retry
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # Exponential backoff: 5s, 10s, 20s
                    logger.warning(f"Rate limited (429). Waiting {delay}s before retry...")
                    time.sleep(delay)
                    continue
                else:
                    logger.error("Rate limited after all retries")
                    return None

            response.raise_for_status()

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                logger.error("GLM returned no choices")
                return None

            content = choices[0].get("message", {}).get("content", "")
            if not content:
                logger.error("GLM returned empty content")
                return None

            logger.info(f"GLM response received ({len(content)} chars)")

            # Parse JSON response
            thesis = parse_thesis_response(content)
            return thesis

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Request failed: {e}. Waiting {delay}s before retry...")
                time.sleep(delay)
            else:
                logger.error(f"GLM API request failed after {max_retries} attempts: {e}", exc_info=True)
                return None
        except Exception as e:
            logger.error(f"Error generating thesis: {e}", exc_info=True)
            return None

    return None


# =============================================================================
# OLLAMA VERSION (commented out - use if GLM API key is no longer available)
# =============================================================================
# def generate_thesis_ollama(ollama, fund_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
#     """Generate investment thesis using Ollama (local LLM).
#
#     To use this instead of GLM:
#     1. Rename this function to generate_thesis()
#     2. Update thesis_update_job() to pass ollama client
#     3. Re-enable the AI lock in thesis_update_job()
#     """
#     context = format_thesis_context(fund_data)
#     prompt = build_thesis_prompt(fund_data)
#     system_prompt = "..."  # Same as above
#
#     full_response = ""
#     for chunk in ollama.query_ollama(
#         prompt=prompt,
#         context=context,
#         model="granite3.3:8b",
#         stream=True,
#         temperature=0.3,
#         json_mode=True,
#         system_prompt=system_prompt,
#         streaming_timeout=120
#     ):
#         full_response += chunk
#
#     return parse_thesis_response(full_response)


def format_thesis_context(fund_data: Dict[str, Any]) -> str:
    """Format fund data as context for AI.

    Args:
        fund_data: Fund data dict

    Returns:
        Formatted context string
    """
    lines = []

    # Fund overview
    lines.append(f"# Fund: {fund_data['fund_name']}")
    lines.append(f"Account Type: {fund_data['account_type']['type']} ({fund_data['account_type']['description']})")
    lines.append(f"Investment Style: {fund_data['account_type']['style']}")
    lines.append(f"Time Horizon: {fund_data['account_type']['horizon']}")
    lines.append("")
    lines.append("## Account Type Philosophy")
    lines.append(fund_data['account_type']['philosophy'])
    lines.append("")

    # Portfolio summary
    total = fund_data.get('total_value', 0)
    lines.append(f"## Portfolio Summary")
    lines.append(f"Total Value: ${total:,.2f}")
    lines.append(f"Number of Positions: {fund_data['position_count']}")
    lines.append("")

    # Sector breakdown
    lines.append("## Sector Breakdown")
    for sector, data in fund_data.get('sector_breakdown', {}).items():
        lines.append(f"\n### {sector} ({data['percentage']}%)")
        for t in data['tickers'][:5]:  # Top 5 per sector
            pnl_str = f"+{t['pnl_pct']}%" if t['pnl_pct'] >= 0 else f"{t['pnl_pct']}%"
            lines.append(f"  - {t['ticker']}: {t['company'][:30]} (P&L: {pnl_str})")
    lines.append("")

    # Top performers
    if fund_data.get('top_performers'):
        lines.append("## Top Performers")
        for p in fund_data['top_performers']:
            lines.append(f"  - {p['ticker']}: +{p['pnl_pct']}%")
        lines.append("")

    # Bottom performers
    if fund_data.get('bottom_performers'):
        lines.append("## Bottom Performers")
        for p in fund_data['bottom_performers']:
            lines.append(f"  - {p['ticker']}: {p['pnl_pct']}%")
        lines.append("")

    return "\n".join(lines)


def build_thesis_prompt(fund_data: Dict[str, Any]) -> str:
    """Build the AI prompt for thesis generation.

    Args:
        fund_data: Fund data dict

    Returns:
        Prompt string
    """
    account_type = fund_data['account_type']['type']
    style = fund_data['account_type']['style']

    return f"""Based on the portfolio data above, generate an investment thesis for this {account_type} account.

Requirements:
1. The thesis should reflect the ACTUAL portfolio composition, not an ideal
2. Create 2-4 pillars that naturally group the holdings by theme/strategy
3. Each pillar should have:
   - A descriptive name
   - An approximate allocation (based on actual holdings)
   - A philosophical thesis explaining the rationale (NOT rigid rules)
4. The overall tone should match the account type ({style})
5. Focus on themes like: growth sectors, value opportunities, income generation, defensive positions, thematic bets

DO NOT include:
- Specific stop-loss percentages
- Technical indicator thresholds (RSI, SMA, etc.)
- Rigid buy/sell rules with numbers
- Position size limits

Instead, describe:
- WHY these holdings make sense together
- What market conditions favor this pillar
- General guidance on when to add or reduce exposure

Respond with this exact JSON structure:
{{
    "title": "Fund Name Investment Thesis",
    "overview": "2-3 sentence overview of the portfolio strategy",
    "pillars": [
        {{
            "name": "Pillar Name",
            "allocation": "~XX%",
            "thesis": "Philosophical description of this pillar's purpose and holdings..."
        }}
    ]
}}"""


def parse_thesis_response(response: str) -> Optional[Dict[str, Any]]:
    """Parse AI response into thesis dict.

    Args:
        response: Raw AI response string

    Returns:
        Parsed thesis dict or None
    """
    try:
        # Try direct JSON parse
        thesis = json.loads(response)

        # Validate structure
        if not isinstance(thesis, dict):
            raise ValueError("Response is not a dict")

        if 'title' not in thesis or 'overview' not in thesis or 'pillars' not in thesis:
            raise ValueError("Missing required fields")

        if not isinstance(thesis['pillars'], list) or len(thesis['pillars']) == 0:
            raise ValueError("Pillars must be a non-empty list")

        return thesis

    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error: {e}")

        # Try to extract JSON from response
        import re
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.error(f"Could not parse thesis response: {response[:500]}")
        return None

    except ValueError as e:
        logger.error(f"Invalid thesis structure: {e}")
        return None


def save_thesis(supabase, fund_name: str, thesis: Dict[str, Any]) -> bool:
    """Save thesis to database.

    Args:
        supabase: Supabase client
        fund_name: Name of the fund
        thesis: Thesis dict with title, overview, pillars

    Returns:
        True on success, False on failure
    """
    try:
        # Check if thesis exists
        existing = supabase.supabase.table('fund_thesis') \
            .select('id') \
            .eq('fund', fund_name) \
            .execute()

        if existing.data:
            # Update existing thesis
            thesis_id = existing.data[0]['id']

            supabase.supabase.table('fund_thesis') \
                .update({
                    'title': thesis['title'],
                    'overview': thesis['overview'],
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                }) \
                .eq('id', thesis_id) \
                .execute()

            # Delete existing pillars
            supabase.supabase.table('fund_thesis_pillars') \
                .delete() \
                .eq('thesis_id', thesis_id) \
                .execute()
        else:
            # Insert new thesis
            result = supabase.supabase.table('fund_thesis') \
                .insert({
                    'fund': fund_name,
                    'title': thesis['title'],
                    'overview': thesis['overview'],
                }) \
                .execute()

            thesis_id = result.data[0]['id']

        # Insert pillars
        for i, pillar in enumerate(thesis.get('pillars', [])):
            supabase.supabase.table('fund_thesis_pillars') \
                .insert({
                    'thesis_id': thesis_id,
                    'name': pillar.get('name', f'Pillar {i+1}'),
                    'allocation': pillar.get('allocation', ''),
                    'thesis': pillar.get('thesis', ''),
                    'pillar_order': i + 1,
                }) \
                .execute()

        logger.info(f"Saved thesis for {fund_name} with {len(thesis.get('pillars', []))} pillars")
        return True

    except Exception as e:
        logger.error(f"Error saving thesis for {fund_name}: {e}", exc_info=True)
        return False


# Entry point for standalone execution
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__file__).rsplit('scheduler', 1)[0])

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    thesis_update_job()
