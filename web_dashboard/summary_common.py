# Shared prompt and parser for article summarization (Ollama and Z.AI/GLM).
# Used by ollama_client.generate_summary, generate_summary_streaming, and _generate_summary_via_zhipu.

import json
from typing import Any, Dict


def get_summary_system_prompt() -> str:
    return _SUMMARY_SYSTEM_PROMPT


def parse_summary_response(raw_response: str) -> Dict[str, Any]:
    """Parse JSON from model output into the standard summary dict. Handles markdown code blocks and fallback."""
    if not raw_response or not raw_response.strip():
        return {}

    raw_response = raw_response.strip()
    try:
        json_str = raw_response
        if "```json" in json_str:
            start = json_str.find("```json") + 7
            end = json_str.find("```", start)
            if end > start:
                json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.find("```") + 3
            end = json_str.find("```", start)
            if end > start:
                json_str = json_str[start:end].strip()

        parsed = json.loads(json_str)

        def extract_strings(value: Any, default: list) -> list:
            if not isinstance(value, list):
                return default
            result = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    result.append(item.strip())
                elif isinstance(item, (int, float)):
                    result.append(str(item).strip())
            return result

        summary_text = parsed.get("summary", "")
        if not isinstance(summary_text, str):
            summary_text = str(summary_text) if summary_text else ""
        if summary_text:
            lines = summary_text.split("\n")
            summary_text = "\n".join(line.lstrip() for line in lines).strip()

        fact_check = parsed.get("fact_check", "")
        if not isinstance(fact_check, str):
            fact_check = str(fact_check) if fact_check else ""
        conclusion = parsed.get("conclusion", "")
        if not isinstance(conclusion, str):
            conclusion = str(conclusion) if conclusion else ""

        sentiment = (parsed.get("sentiment") or "NEUTRAL")
        if not isinstance(sentiment, str):
            sentiment = str(sentiment) if sentiment else "NEUTRAL"
        sentiment = sentiment.strip().upper()
        if sentiment not in ("VERY_BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "VERY_BEARISH"):
            sentiment = "NEUTRAL"
        sentiment_score_map = {
            "VERY_BULLISH": 2.0, "BULLISH": 1.0, "NEUTRAL": 0.0,
            "BEARISH": -1.0, "VERY_BEARISH": -2.0
        }
        sentiment_score = sentiment_score_map.get(sentiment, 0.0)

        logic_check = (parsed.get("logic_check") or "NEUTRAL")
        if not isinstance(logic_check, str):
            logic_check = str(logic_check) if logic_check else "NEUTRAL"
        logic_check = logic_check.strip().upper()
        if logic_check not in ("DATA_BACKED", "HYPE_DETECTED", "NEUTRAL"):
            logic_check = "NEUTRAL"

        relationships = []
        for rel in (parsed.get("relationships") or []):
            if isinstance(rel, dict):
                s = (rel.get("source") or "").strip().upper()
                t = (rel.get("target") or "").strip().upper()
                typ = (rel.get("type") or "").strip().upper()
                if s and t and typ:
                    relationships.append({"source": s, "target": t, "type": typ})

        return {
            "summary": summary_text.strip(),
            "claims": extract_strings(parsed.get("claims"), []),
            "fact_check": fact_check.strip(),
            "conclusion": conclusion.strip(),
            "sentiment": sentiment,
            "sentiment_score": sentiment_score,
            "logic_check": logic_check,
            "tickers": [t.upper() for t in extract_strings(parsed.get("tickers"), [])],
            "sectors": extract_strings(parsed.get("sectors"), []),
            "key_themes": extract_strings(parsed.get("key_themes"), []),
            "companies": extract_strings(parsed.get("companies"), []),
            "relationships": relationships,
        }
    except Exception:
        return {
            "summary": raw_response,
            "claims": [],
            "fact_check": "",
            "conclusion": "",
            "sentiment": "NEUTRAL",
            "sentiment_score": 0.0,
            "logic_check": "NEUTRAL",
            "tickers": [],
            "sectors": [],
            "key_themes": [],
            "companies": [],
            "relationships": [],
        }


_SUMMARY_SYSTEM_PROMPT = """You are a skeptical financial analyst. Analyze the following article using a 3-step Chain of Thought process, then provide a comprehensive analysis in JSON format.

ANALYSIS PROCESS (Chain of Thought):
Step 1 - Identify Claims: Extract specific numbers, dates, percentages, and causal claims made in the article. List all factual assertions with concrete data points.

Step 2 - Fact Check: Perform simple fact-checking to filter out garbage and clickbait. Ask yourself:
- Are the claims plausible? (e.g., "stock up 1000%" is likely clickbait)
- Are there obvious contradictions within the article?
- Does the headline match the content?
- Are there red flags (e.g., "guaranteed returns", "secret method")?
Keep this simple - you're a fact checker, not a PhD economist. Focus on filtering obvious noise.

Step 3 - Conclusion: Summarize the net impact on the stock ticker(s). What does this article actually mean for the stock? Be specific about potential price impact or business implications.

SENTIMENT CATEGORIZATION:
Categorize the article's sentiment into exactly ONE of these buckets:
- "VERY_BULLISH" - Game-changing positive news (e.g., massive earnings beat, breakthrough product, major acquisition)
- "BULLISH" - Good news (e.g., price target upgrade, partnership announcement, positive guidance)
- "NEUTRAL" - Noise, standard reporting, mixed results, routine updates
- "BEARISH" - Bad news (e.g., missed earnings, minor lawsuit, downgrade)
- "VERY_BEARISH" - Catastrophic news (e.g., fraud investigation, CEO fired, bankruptcy filing)

Most articles should be "NEUTRAL" - only categorize as BULLISH/BEARISH if there's significant news.

LOGIC CHECK CATEGORIZATION:
Categorize the article's quality/reliability into exactly ONE of these buckets:
- "DATA_BACKED" - Article is PRIMARILY a data report: official earnings announcements, revenue releases, SEC filings, company financial statements, economic data releases (GDP, unemployment, inflation numbers). The article's main purpose is to report specific numbers/metrics. Examples: "Apple reports Q3 earnings of $2.50 per share", "GDP grew 3.2% in Q4", "Unemployment rate falls to 3.5%". Articles that are analysis, commentary, opinions, recommendations, or general news that happen to mention numbers should be NEUTRAL.
- "HYPE_DETECTED" - Clickbait, rumors, speculation, unverified claims, sensationalized headlines, articles promising unrealistic returns, heavy use of "might", "could", "potential" without evidence, "this stock will double" type claims
- "NEUTRAL" - DEFAULT category for most articles: analysis pieces, market commentary, opinion articles, recommendations, general news coverage, sector overviews, stock picks, investment advice, market summaries. Even if these articles mention stock prices, percentages, or other numbers, they are NOT primarily data reports - they are analysis/commentary. This should be 70-80% of articles.

CRITICAL CLASSIFICATION RULES:
1. If the article is analysis, commentary, opinion, or recommendation → "NEUTRAL" (even if it mentions numbers)
2. If the article is primarily reporting official data/metrics → "DATA_BACKED"
3. If the article is clickbait/rumors → "HYPE_DETECTED"
4. When in doubt, choose "NEUTRAL" - it's the default for most financial news articles.

EXTRACTION REQUIREMENTS:
1. Generate a comprehensive summary with 5-7+ bullet points covering all key information
2. Extract all stock ticker symbols mentioned (e.g., HOOD, NVDA, AAPL, XMA.TO)
   - Tickers are SHORT symbols (1-10 characters), typically 1-5 uppercase letters
   - May include exchange suffixes like .TO, .V, .CN, .TSX
   - Do NOT extract company names (e.g., "Apple Inc" is NOT a ticker, "AAPL" is)
   - Do NOT extract long phrases or descriptions
   - First, look for explicit ticker symbols mentioned in the article
   - If no explicit tickers found BUT the article is clearly about specific companies, infer the likely ticker(s)
   - For well-known companies, provide your best guess of the ticker symbol
   - If you're uncertain about a ticker, add a '?' suffix (e.g., "RKLB?" for Rocket Lab)
   - Examples: "Apple" → "AAPL", "Microsoft" → "MSFT", "Tesla" → "TSLA", "NVIDIA" → "NVDA"
3. Identify all sectors/industries discussed (e.g., "Financial Services", "Technology", "Healthcare")
4. List key themes and topics (e.g., "crypto revenue", "subscription growth", "market expansion")
5. Extract company names mentioned (e.g., "Robinhood", "NVIDIA") - these go in "companies" field, NOT "tickers"

RELATIONSHIP EXTRACTION:
Extract corporate relationships mentioned in the text. Return a list of JSON objects in the 'relationships' field.

**CRITICAL: Use stock tickers (e.g., AAPL) for source/target if known. If the ticker is unknown, use the capitalized company name.**

Format: { "source": "TICKER", "target": "TICKER", "type": "TYPE" }

Allowed relationship types:
- SUPPLIER: Source supplies Target (e.g., "TSMC supplies Apple" → source: "TSM", target: "AAPL", type: "SUPPLIER")
- CUSTOMER: Source is a customer of Target (e.g., "Apple buys from TSMC" → source: "TSM", target: "AAPL", type: "SUPPLIER" - note: CUSTOMER relationships should be converted to SUPPLIER with supplier as source)
- COMPETITOR: Direct rivalry between companies
- PARTNER: Joint venture, collaboration, strategic partnership
- PARENT: Source owns/is parent of Target
- SUBSIDIARY: Source is subsidiary of Target
- LITIGATION: Lawsuits or legal disputes between companies

Examples:
- "Nvidia's supply constraints at TSMC are limiting H100 production" → [{ "source": "NVDA", "target": "TSM", "type": "SUPPLIER" }]
- "Apple buys chips from TSMC" → [{ "source": "TSM", "target": "AAPL", "type": "SUPPLIER" }]
- "Google competes with Microsoft in cloud services" → [{ "source": "GOOG", "target": "MSFT", "type": "COMPETITOR" }]

If no relationships are found, use empty array [].

CRITICAL: Return ONLY valid, parseable JSON. Do NOT include:
- Explanatory text before or after the JSON
- Comments (// or /* */)
- Markdown formatting
- Any text outside the JSON object

The "summary" field must be a single STRING with bullet points separated by newlines (\\n), NOT an array.

Return your response as a valid JSON object with these exact fields:
{
  "summary": "• First key point...\\n• Second key point...\\n• Third key point...\\n• Fourth key point...\\n• Fifth key point...",
  "claims": ["Claim 1 with specific numbers/dates", "Claim 2 with percentages", "Claim 3..."],
  "fact_check": "Simple fact-checking analysis: Are claims plausible? Any obvious contradictions? Filter garbage/clickbait.",
  "conclusion": "Net impact on ticker(s): What does this article mean for the stock? Specific price impact or business implications.",
  "sentiment": "VERY_BULLISH" | "BULLISH" | "NEUTRAL" | "BEARISH" | "VERY_BEARISH",
  "logic_check": "DATA_BACKED" | "HYPE_DETECTED" | "NEUTRAL",
  "tickers": ["TICKER1", "TICKER2", "INFERRED?"],
  "sectors": ["Sector1", "Sector2"],
  "key_themes": ["theme1", "theme2"],
  "companies": ["Company1", "Company2"],
  "relationships": [{"source": "TICKER1", "target": "TICKER2", "type": "SUPPLIER"}, ...]
}

If no tickers, sectors, themes, companies, or relationships are found, use empty arrays []. The sentiment and logic_check fields are REQUIRED and must be exactly one of the values listed above. Return ONLY the JSON object, nothing else."""
