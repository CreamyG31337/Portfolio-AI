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
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class NewsletterService:
    """Service for processing newsletter emails from Mailgun"""
    
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

        Removes repeated Fwd:, Fw:, Re: prefixes (case-insensitive) so that
        stored subjects show the original newsletter title.

        Args:
            subject: Raw email subject line

        Returns:
            Cleaned subject with prefixes removed
        """
        if not subject:
            return subject
        return re.sub(r'^(?:(?:Fwd?|Re)\s*:\s*)+', '', subject, flags=re.IGNORECASE).strip()

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
    
    def extract_tickers(self, text: str) -> List[str]:
        """Extract stock ticker symbols from text
        
        Args:
            text: Text to search for tickers
            
        Returns:
            List of unique ticker symbols found
        """
        try:
            # Pattern for ticker symbols: 1-5 uppercase letters
            # Avoid common words that look like tickers
            pattern = r'\b([A-Z]{1,5})\b'
            
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
            
            matches = re.findall(pattern, text)
            
            # Filter out excluded words and ensure 2-5 characters (most tickers)
            tickers = [
                ticker for ticker in set(matches)
                if ticker not in exclude_words and 2 <= len(ticker) <= 5
            ]
            
            # Sort alphabetically
            return sorted(tickers)
            
        except Exception as e:
            logger.error(f"Error extracting tickers: {e}")
            return []
    
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
                'embedding': embedding,
                'message_id': message_id,
                'received_at': received_at
            }
            
        except Exception as e:
            logger.error(f"Error processing newsletter: {e}")
            raise
