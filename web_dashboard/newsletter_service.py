#!/usr/bin/env python3
"""
Newsletter Service
Handles email newsletter processing from Mailgun webhooks
"""

import os
import re
import hmac
import hashlib
import logging
import time
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class NewsletterService:
    """Service for processing newsletter emails from Mailgun"""

    _KNOWN_TICKERS_CACHE_TTL_SECONDS = 3600
    _known_tickers_cache: Optional[Set[str]] = None
    _known_tickers_cache_at: float = 0.0
    
    def __init__(self):
        """Initialize newsletter service"""
        self.mailgun_signing_key = os.getenv("MAILGUN_WEBHOOK_SIGNING_KEY")
        if not self.mailgun_signing_key:
            logger.warning("MAILGUN_WEBHOOK_SIGNING_KEY not set - webhook verification will fail")
    
    def verify_webhook_signature(
        self,
        token: str,
        timestamp: str,
        signature: str
    ) -> bool:
        """Verify Mailgun webhook signature using HMAC-SHA256
        
        Args:
            token: Random token from Mailgun
            timestamp: Unix timestamp from Mailgun
            signature: HMAC signature from Mailgun
            
        Returns:
            True if signature is valid, False otherwise
        """
        if not self.mailgun_signing_key:
            logger.error("Cannot verify signature - MAILGUN_WEBHOOK_SIGNING_KEY not configured")
            return False
        
        try:
            # Compute HMAC-SHA256
            message = f"{timestamp}{token}".encode('utf-8')
            key = self.mailgun_signing_key.encode('utf-8')
            
            computed_signature = hmac.new(
                key=key,
                msg=message,
                digestmod=hashlib.sha256
            ).hexdigest()
            
            # Compare signatures (constant time comparison to prevent timing attacks)
            is_valid = hmac.compare_digest(computed_signature, signature)
            
            if not is_valid:
                logger.warning(f"Invalid Mailgun signature - computed: {computed_signature[:10]}..., received: {signature[:10]}...")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error verifying Mailgun signature: {e}")
            return False
    
    @staticmethod
    def clean_subject(subject: str) -> str:
        """Strip forwarding/reply prefixes from email subjects.

        Removes repeated Fwd:, Fw:, Re: prefixes (case-insensitive), including
        variants with extra whitespace and delimiter variants (``:``, ``：``,
        ``-``). Also supports subjects where these prefixes appear after
        leading bracket tags such as ``[External]``.

        Args:
            subject: Raw email subject line

        Returns:
            Cleaned subject with prefixes removed
        """
        if not subject:
            return subject

        cleaned = subject.strip()

        # Preserve any leading bracket tags while stripping forwarding prefixes
        # that appear after them (e.g., "[External] Fwd: ...").
        leading_tags_match = re.match(r"^(?P<tags>(?:\[[^\]]+\]\s*)+)", cleaned)
        leading_tags = ""
        if leading_tags_match:
            leading_tags = leading_tags_match.group("tags")
            cleaned = cleaned[len(leading_tags):]

        cleaned = re.sub(
            r"^(?:(?:FWD?|RE)\s*(?::|：|-)\s*)+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()

        return f"{leading_tags}{cleaned}".strip()

    @staticmethod
    def clean_forwarded_body(text: str) -> str:
        """Strip forwarded-message header blocks and invisible whitespace.

        Removes the ``---------- Forwarded message ---------`` header block
        (through the blank line after the last header like To:/Subject:),
        leading/trailing zero-width characters, and collapses excessive blank
        lines.

        Args:
            text: Raw plain-text email body

        Returns:
            Cleaned body text
        """
        if not text:
            return text

        # Remove forwarded-message header block
        # Pattern: "---------- Forwarded message ---------" followed by
        # header lines (From:, Date:, Subject:, To:) until a blank line
        text = re.sub(
            r'-{5,}\s*Forwarded message\s*-{5,}\s*\n'
            r'(?:(?:From|Date|Subject|To|Cc|Bcc):.*\n)*'
            r'\s*\n?',
            '',
            text,
            flags=re.IGNORECASE,
        )

        # Strip zero-width / invisible Unicode whitespace characters
        text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeff]+', '', text)

        # Collapse 3+ consecutive newlines down to 2
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    def extract_text_from_html(self, html: str) -> str:
        """Extract clean text from HTML email body
        
        Args:
            html: HTML email content
            
        Returns:
            Clean text content
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get text
            text = soup.get_text()
            
            # Break into lines and remove leading/trailing space
            lines = (line.strip() for line in text.splitlines())
            
            # Break multi-headlines into a line each
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            
            # Drop blank lines
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            return text
            
        except Exception as e:
            logger.error(f"Error extracting text from HTML: {e}")
            return html  # Return raw HTML as fallback
    
    def extract_article_url(
        self,
        body_html: Optional[str] = None,
        body_plain: Optional[str] = None
    ) -> Optional[str]:
        """Extract the most likely 'read on web' / 'read the article' link from an email
        
        Searches for links whose visible text or href indicate a 'read online'
        action. Falls back to plain-text URL extraction when HTML yields no
        results.
        
        Args:
            body_html: HTML email body
            body_plain: Plain text email body
            
        Returns:
            Best article URL found, or None
        """
        # Patterns for link visible text (case-insensitive)
        _TEXT_PATTERNS = [
            r"read\s+(this\s+)?(on\s+the\s+web|online|in\s+browser|the\s+full\s+article|the\s+article|more)",
            r"view\s+(this\s+)?(in\s+browser|online|on\s+the\s+web|email\s+in\s+browser)",
            r"open\s+in\s+browser",
            r"continue\s+reading",
            r"read\s+on\s+web",
        ]
        _text_re = re.compile(
            "|".join(f"(?:{p})" for p in _TEXT_PATTERNS),
            re.IGNORECASE,
        )

        # Patterns for href substrings
        _HREF_PATTERNS = [
            "view-in-browser",
            "read-online",
            "view-online",
            "open-in-browser",
            "read-in-browser",
            "view-email",
            "webversion",
            "web-version",
            "browser-view",
            "emailview",
        ]

        def _is_bad_url(url: str) -> bool:
            """Return True if the URL should be excluded."""
            if not url:
                return True
            low = url.strip().lower()
            if low.startswith(("mailto:", "javascript:", "#", "tel:")):
                return True
            bad_keywords = [
                "unsubscribe", "opt-out", "optout", "manage-preferences",
                "email-preferences", "notification-settings",
                "tracking-pixel", "open-tracking", "/track/",
                "share/facebook", "share/twitter", "share/linkedin",
                "share/email", "sharer.php", "intent/tweet",
            ]
            return any(kw in low for kw in bad_keywords)

        try:
            if body_html:
                soup = BeautifulSoup(body_html, 'html.parser')

                # Strategy 1: match visible link text
                for tag in soup.find_all("a", href=True):
                    link_text = tag.get_text(strip=True)
                    if link_text and _text_re.search(link_text):
                        href = tag["href"].strip()
                        if not _is_bad_url(href):
                            logger.debug(f"Extracted article URL via link text: {href}")
                            return href

                # Strategy 2: match href patterns
                for tag in soup.find_all("a", href=True):
                    href = tag["href"].strip()
                    href_lower = href.lower()
                    if any(pat in href_lower for pat in _HREF_PATTERNS):
                        if not _is_bad_url(href):
                            logger.debug(f"Extracted article URL via href pattern: {href}")
                            return href

            # Strategy 3: fall back to plain text
            if body_plain:
                url_re = re.compile(r"https?://\S+", re.IGNORECASE)
                for match in url_re.finditer(body_plain):
                    url = match.group(0).rstrip(".,;:!?)>\"'")
                    url_lower = url.lower()
                    if any(pat in url_lower for pat in _HREF_PATTERNS):
                        if not _is_bad_url(url):
                            logger.debug(f"Extracted article URL from plain text: {url}")
                            return url

            logger.debug("No article URL found in email body")
            return None

        except Exception as e:
            logger.error(f"Error extracting article URL: {e}")
            return None
    
    @classmethod
    def get_known_tickers_for_validation(cls) -> Set[str]:
        """Return cached known tickers used for newsletter extraction filtering.

        The known list comes from the application's aggregated ticker universe
        (securities + watched + research/social sources). This is cached to
        avoid repeated DB/network lookups during webhook processing.
        """
        now = time.time()
        if (
            cls._known_tickers_cache is not None
            and (now - cls._known_tickers_cache_at) < cls._KNOWN_TICKERS_CACHE_TTL_SECONDS
        ):
            return cls._known_tickers_cache

        try:
            from ticker_utils import get_all_unique_tickers

            tickers = get_all_unique_tickers()
            normalized = {
                str(ticker).upper().strip()
                for ticker in (tickers or [])
                if isinstance(ticker, str) and str(ticker).strip()
            }
            cls._known_tickers_cache = normalized
            cls._known_tickers_cache_at = now
            logger.info(f"Loaded {len(normalized)} known tickers for newsletter validation")
            return normalized
        except Exception as e:
            logger.warning(f"Failed to load known tickers for newsletter validation: {e}")
            return set()

    def extract_tickers(
        self,
        text: str,
        validate_known_tickers: bool = False,
        known_tickers: Optional[Set[str]] = None
    ) -> List[str]:
        """Extract stock ticker symbols from text
        
        Args:
            text: Text to search for tickers
            
        Returns:
            List of unique ticker symbols found
        """
        try:
            # Common words/abbreviations to exclude (not stock tickers)
            exclude_words = {
                # Single-letter & short common words
                'A', 'I', 'AT', 'TO', 'IN', 'ON', 'IT', 'IS', 'BE', 'OR', 'AN',
                'AS', 'BY', 'FOR', 'THE', 'AND', 'BUT', 'NOT', 'YOU', 'ALL',
                'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'ARE', 'FROM', 'THAT',
                'THIS', 'WITH', 'HAVE', 'WILL', 'YOUR', 'MAY', 'NEW', 'US', 'IF',
                'WOULD', 'BEEN', 'WHICH', 'THEIR', 'ABOUT', 'MORE', 'THAN', 'ALSO',
                'SO', 'DO', 'NO', 'UP', 'GO', 'HE', 'WE', 'MY', 'ME', 'OF',
                # C-suite / corporate titles
                'CEO', 'CFO', 'COO', 'CTO', 'VP', 'SVP', 'EVP',
                # Financial / economic terms
                'IPO', 'ETF', 'GDP', 'CPI', 'FED', 'SEC', 'API',
                'IRA', 'JOLTS', 'FOMC', 'FDIC', 'FINRA', 'GAAP', 'EBIT',
                'EBITA', 'YTD', 'QOQ', 'YOY', 'ROI', 'ROE', 'ROA', 'PE',
                'EPS', 'NAV', 'AUM', 'SPAC', 'OTC',
                # Currencies
                'USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'CNY', 'HKD',
                # Countries / regions
                'USA', 'UK', 'EU',
                # Tech abbreviations
                'AI', 'ML', 'AR', 'VR', 'IT', 'HR', 'PR',
                'FAQ', 'PDF', 'URL', 'HTML', 'CSS', 'HTTP', 'API',
                # News / media networks
                'CNBC', 'WSJ', 'BBC', 'CNN', 'NBC', 'CBS', 'ABC', 'PBS', 'NPR',
                'FOX',
                # Time / date words
                'AM', 'PM',
                'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN',
                'JAN', 'FEB', 'MAR', 'APR', 'JUN', 'JUL', 'AUG', 'SEP',
                'OCT', 'NOV', 'DEC',
                # Business entity types
                'LLC', 'INC', 'LTD', 'CORP', 'PLC',
                # Email / misc abbreviations
                'FWD', 'RE', 'CC', 'BCC', 'FYI', 'ASAP', 'RIP', 'DIY',
                'PSA', 'TBD', 'ETC', 'VS', 'NA', 'TBA',
            }

            # Candidate extraction:
            # - "$AAPL" style (high confidence)
            # - "NASDAQ: AAPL" style (high confidence)
            # - "(AAPL)" style (medium confidence)
            # - generic uppercase tokens (lower confidence)
            dollar_pattern = re.compile(
                r"(?<![A-Za-z0-9])\$([A-Z][A-Z0-9]{0,4}(?:[.-][A-Z]{1,3})?)\b"
            )
            exchange_pattern = re.compile(
                r"\b(?:NYSE|NASDAQ|AMEX|TSX|TSXV|CSE|OTC|NYSEARCA|NYSEAMERICAN)"
                r"\s*[:\-]\s*([A-Z][A-Z0-9]{0,4}(?:[.-][A-Z]{1,3})?)\b"
            )
            parenthetical_pattern = re.compile(
                r"\(([A-Z][A-Z0-9]{0,4}(?:[.-][A-Z]{1,3})?)\)"
            )
            generic_pattern = re.compile(
                r"\b([A-Z][A-Z0-9]{1,4}(?:[.-][A-Z]{1,3})?)\b"
            )

            candidate_count: Dict[str, int] = {}
            candidate_score: Dict[str, int] = {}
            explicit_candidates: Set[str] = set()

            def add_candidate(ticker: str, score: int, is_explicit: bool = False) -> None:
                normalized = ticker.upper().strip()
                if not normalized:
                    return
                candidate_count[normalized] = candidate_count.get(normalized, 0) + 1
                candidate_score[normalized] = max(score, candidate_score.get(normalized, 0))
                if is_explicit:
                    explicit_candidates.add(normalized)

            for match in dollar_pattern.findall(text):
                add_candidate(match, score=3, is_explicit=True)
            for match in exchange_pattern.findall(text):
                add_candidate(match, score=3, is_explicit=True)
            for match in parenthetical_pattern.findall(text):
                add_candidate(match, score=2, is_explicit=True)
            for match in generic_pattern.findall(text):
                add_candidate(match, score=1, is_explicit=False)

            validated_known_tickers: Set[str] = set()
            if validate_known_tickers:
                validated_known_tickers = known_tickers or self.get_known_tickers_for_validation()

            filtered: List[str] = []
            for ticker in sorted(candidate_count.keys()):
                if ticker in exclude_words:
                    continue

                # Allow common ticker shapes:
                # AAPL, BRK.B, BRK-B, SHOP.TO
                if not re.fullmatch(r"[A-Z][A-Z0-9]{1,4}(?:[.-][A-Z]{1,3})?", ticker):
                    continue

                if validate_known_tickers and validated_known_tickers:
                    if ticker in validated_known_tickers:
                        filtered.append(ticker)
                        continue

                    # Keep high-confidence unknown symbols to avoid false negatives.
                    if ticker in explicit_candidates:
                        filtered.append(ticker)
                        continue

                    # Keep repeated unknown symbols (mentioned multiple times).
                    if candidate_count.get(ticker, 0) >= 2:
                        filtered.append(ticker)
                        continue

                    # Otherwise drop as likely noise.
                    continue

                filtered.append(ticker)

            return filtered
            
        except Exception as e:
            logger.error(f"Error extracting tickers: {e}")
            return []

    @staticmethod
    def sanitize_ai_tickers(raw_tickers: Any) -> List[str]:
        """Normalize and validate AI-extracted ticker candidates.

        AI output can include uncertain/noisy values (e.g., ``"$?"``). This
        helper keeps only valid ticker-like symbols and removes markers.

        Args:
            raw_tickers: Arbitrary AI output, typically a list of ticker strings

        Returns:
            Deduplicated list of normalized ticker symbols
        """
        if isinstance(raw_tickers, str):
            # Accept common AI formats:
            # "$BTCS, $NTRB" or "['$BTCS', '$NTRB']" or "$BTCS $NTRB"
            normalized = raw_tickers.strip()
            if normalized.startswith("[") and normalized.endswith("]"):
                normalized = normalized[1:-1]
            tokens = re.split(r"[\s,;|]+", normalized)
            raw_items: List[Any] = [t.strip("'\"") for t in tokens if t.strip()]
        elif isinstance(raw_tickers, list):
            raw_items = raw_tickers
        else:
            return []

        cleaned: List[str] = []
        seen: set[str] = set()
        invalid_tokens = {"", "?", "$", "$?", "N/A", "NONE", "UNKNOWN", "NULL"}

        for item in raw_items:
            if not isinstance(item, str):
                continue

            ticker = item.strip().upper()
            if not ticker:
                continue

            # Common AI formatting artifacts
            if ticker.startswith("$"):
                ticker = ticker[1:]
            if ticker.endswith("?"):
                ticker = ticker[:-1]
            ticker = ticker.strip()

            if ticker in invalid_tokens:
                continue

            # Match common ticker formats (US + common global forms)
            if not re.fullmatch(r"[A-Z][A-Z0-9\.-]{0,19}", ticker):
                continue

            if ticker not in seen:
                seen.add(ticker)
                cleaned.append(ticker)

        return cleaned
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate vector embedding for text using Ollama
        
        Args:
            text: Text to generate embedding for (will be truncated if too long)
            
        Returns:
            List of floats (768 dimensions) or None if failed
        """
        try:
            from ollama_client import get_ollama_client
            
            ollama = get_ollama_client()
            if not ollama:
                logger.warning("Ollama client not available - skipping embedding generation")
                return None
            
            # Truncate text to avoid token limits (keep first ~6000 chars)
            max_chars = 6000
            if len(text) > max_chars:
                text = text[:max_chars]
                logger.debug(f"Truncated text to {max_chars} characters for embedding")
            
            # Generate embedding using nomic-embed-text model
            embedding = ollama.generate_embedding(text, model="nomic-embed-text")
            
            if not embedding:
                logger.warning("Failed to generate embedding")
                return None
            
            if len(embedding) != 768:
                logger.warning(f"Unexpected embedding dimension: {len(embedding)} (expected 768)")
                return None

            logger.debug(f"Generated {len(embedding)}-dimension embedding")
            return embedding
            
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None
    
    def process_newsletter(
        self,
        sender: str,
        recipient: str,
        subject: str,
        body_plain: Optional[str] = None,
        body_html: Optional[str] = None,
        sender_name: Optional[str] = None,
        message_id: Optional[str] = None,
        timestamp: Optional[int] = None,
        skip_embedding: bool = False
    ) -> Dict[str, Any]:
        """Process newsletter email and prepare for storage
        
        Args:
            sender: Sender email address
            recipient: Recipient email address
            subject: Email subject
            body_plain: Plain text email body
            body_html: HTML email body
            sender_name: Sender display name
            message_id: Mailgun message ID
            timestamp: Unix timestamp when email was received
            skip_embedding: If True, skip embedding generation (save first, embed later)
            
        Returns:
            Dictionary with processed newsletter data ready for storage
        """
        try:
            # Clean subject (strip Fwd:/Re: prefixes)
            clean_subj = self.clean_subject(subject)

            # Use plain text if available, otherwise extract from HTML
            if body_plain:
                text_content = self.clean_forwarded_body(body_plain)
            elif body_html:
                text_content = self.extract_text_from_html(body_html)
            else:
                text_content = ""
                logger.warning("Newsletter has no body content")
            
            # Extract article URL from email body
            article_url = self.extract_article_url(body_html, body_plain)
            
            # Extract ticker symbols from combined subject + body
            full_text = f"{clean_subj}\n\n{text_content}"
            tickers = self.extract_tickers(full_text)
            
            # Generate embedding (unless skipped)
            embedding = None if skip_embedding else self.generate_embedding(text_content)
            
            # Convert timestamp to datetime
            received_at = None
            if timestamp:
                try:
                    received_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid timestamp {timestamp}: {e}")
                    received_at = datetime.now(timezone.utc)
            else:
                received_at = datetime.now(timezone.utc)
            
            return {
                'sender': sender,
                'sender_name': sender_name,
                'recipient': recipient,
                'subject': clean_subj,
                'body_plain': text_content if body_plain else body_plain,
                'body_html': body_html,
                'tickers': tickers if tickers else None,
                'article_url': article_url,
                'embedding': embedding,
                'message_id': message_id,
                'received_at': received_at
            }
            
        except Exception as e:
            logger.error(f"Error processing newsletter: {e}")
            raise
