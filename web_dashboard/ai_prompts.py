#!/usr/bin/env python3
"""
AI Prompt Templates
===================

System prompts and prompt templates for different investigation types.
"""

from typing import Optional

# Version for portfolio assistant Gem
# Bump this version when the system prompt changes to create a new Gem
PORTFOLIO_ASSISTANT_VERSION = "v1"

# Base system prompt for financial analysis
BASE_SYSTEM_PROMPT = """You are an expert financial analyst AI assistant helping users investigate their trading portfolio. 
You have access to their portfolio data including positions, trades, performance metrics, and cash balances.

IMPORTANT: You also have access to web search capabilities via SearXNG. When users ask about:
- Current news or recent events
- Stock tickers not in their portfolio
- Market trends and analysis
- Time-sensitive information (today, this week, recent)
- Research requests

The system will automatically search the web and provide you with relevant search results. Use these search results to provide informed, up-to-date answers. When citing information from search results, reference the sources when possible.

Provide clear, actionable insights based on the data provided. Be specific and reference the data when making points.
Use professional financial terminology but explain complex concepts when helpful.
Focus on actionable insights and avoid generic advice.

When search results are provided, integrate them naturally into your response and cite sources when relevant."""

# System prompt for WebAI (no SearXNG access)
WEBAI_SYSTEM_PROMPT = """You are an expert financial analyst AI assistant helping users investigate their trading portfolio. 
You have access to their portfolio data including positions, trades, performance metrics, and cash balances.

Provide clear, actionable insights based on the data provided. Be specific and reference the data when making points.
Use professional financial terminology but explain complex concepts when helpful.
Focus on actionable insights and avoid generic advice.

When analyzing the portfolio, consider:
- Current market conditions and trends
- Risk management and diversification
- Performance relative to investment goals
- Opportunities for optimization"""

# Prompt templates for different analysis types
PROMPT_TEMPLATES = {
    "holdings_analysis": """Provide a comprehensive analysis of the current portfolio holdings. 
Include insights on:
- Diversification and concentration risk
- Sector allocation and balance
- Individual position performance
- Risk assessment
- Recommendations for optimization""",

    "thesis_alignment": """Analyze how the current portfolio holdings align with the investment thesis. 
Evaluate:
- Whether positions support the stated investment strategy
- Alignment with investment pillars
- Areas where the portfolio diverges from the thesis
- Recommendations to better align with the thesis""",

    "trade_analysis": """Analyze the recent trading activity. Review:
- Trade patterns and frequency
- Win rate and profitability
- Best and worst performing trades
- Trading behavior patterns
- Areas for improvement""",

    "performance_analysis": """Analyze the performance trends over time along with key performance metrics. 
Provide insights on:
- Portfolio performance trajectory
- Risk-adjusted returns
- Drawdowns and recovery periods
- Areas of strength or concern
- Comparison to benchmarks if available""",

    "comparison": """Compare and analyze the relationship between the selected data elements. 
Provide insights on:
- How these elements interact
- What they reveal about portfolio performance
- Patterns and correlations
- Actionable recommendations based on the comparison""",

    "risk_assessment": """Assess the portfolio risk profile. Analyze:
- Concentration risk
- Sector exposure
- Individual position risks
- Overall portfolio risk level
- Recommendations for risk management""",

    "custom": """Based on the provided portfolio data, answer the user's question with specific insights and recommendations."""
}


def get_system_prompt(model: str = None) -> str:
    """Get the appropriate system prompt based on the model.
    
    Args:
        model: Model name (e.g., 'gemini-2.0-flash-exp', 'llama3.2:3b')
        
    Returns:
        System prompt string
    """
    # Check if it's a WebAI model (Gemini models)
    if model and ('gemini' in model.lower() or 'glm' in model.lower()):
        return WEBAI_SYSTEM_PROMPT
    return BASE_SYSTEM_PROMPT


def get_prompt_template(template_name: str) -> str:
    """Get a prompt template by name.
    
    Args:
        template_name: Name of the template
        
    Returns:
        Template string or default template
    """
    return PROMPT_TEMPLATES.get(template_name, PROMPT_TEMPLATES["custom"])


def build_analysis_prompt(
    template_name: str,
    context: str,
    user_query: Optional[str] = None
) -> str:
    """Build a complete analysis prompt.
    
    Args:
        template_name: Name of the template to use
        context: Formatted context data
        user_query: Optional user query
        
    Returns:
        Complete prompt string
    """
    template = get_prompt_template(template_name)
    
    prompt_parts = [
        "Portfolio Data:",
        context,
        "",
        "Analysis Request:",
        template
    ]
    
    if user_query:
        prompt_parts.append("")
        prompt_parts.append(f"Additional Question: {user_query}")
    
    return "\n".join(prompt_parts)

