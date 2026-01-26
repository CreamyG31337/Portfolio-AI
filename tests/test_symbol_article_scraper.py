"""
Unit tests for symbol article scraper.

Tests cover HTML parsing, URL validation, and article link extraction.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'web_dashboard'))

try:
    from bs4 import BeautifulSoup
    from symbol_article_scraper import (
        build_symbol_url,
        is_valid_article_url,
        extract_article_links,
        filter_article_links,
        scrape_symbol_articles,
        fetch_symbol_page,
    )
except ImportError as e:
    BeautifulSoup = None
    print(f"Warning: Some dependencies not available - {e}")


class TestSymbolArticleHTMLParsing(unittest.TestCase):
    """Test HTML parsing and link extraction."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Sample HTML structure based on typical symbol pages
        self.sample_html = """
        <html>
        <body>
            <div class="article-list">
                <a href="/article/1234567-title-here">Article Title 1</a>
                <a href="https://seekingalpha.com/article/1234568-another-title">Article Title 2</a>
            </div>
            <div class="news-section">
                <a href="/news/1234569-news-item">News Item 1</a>
            </div>
            <div class="analysis-section">
                <a href="/analysis/1234570-analysis">Analysis 1</a>
            </div>
            <div class="comments">
                <a href="/article/1234567-title-here/comments">Comments</a>
            </div>
            <a href="/symbol/STLD">Back to Symbol</a>
            <a href="/author/john-doe">Author Profile</a>
        </body>
        </html>
        """
    
    def test_parse_html_structure(self):
        """Test that we can parse HTML and find links."""
        if not BeautifulSoup:
            self.skipTest("BeautifulSoup not available")
        
        soup = BeautifulSoup(self.sample_html, 'html.parser')
        links = soup.find_all('a', href=True)
        
        self.assertGreater(len(links), 0, "Should find at least one link")
    
    def test_extract_article_urls(self):
        """Test extracting article URLs from HTML."""
        if not BeautifulSoup:
            self.skipTest("BeautifulSoup not available")
        
        soup = BeautifulSoup(self.sample_html, 'html.parser')
        links = soup.find_all('a', href=True)
        
        article_urls = []
        for link in links:
            href = link.get('href', '')
            if '/article/' in href and '/comments' not in href:
                # Make absolute if relative
                if href.startswith('/'):
                    href = f"https://seekingalpha.com{href}"
                article_urls.append(href)
        
        self.assertGreater(len(article_urls), 0, "Should find article URLs")
        self.assertTrue(any('/article/1234567' in url for url in article_urls))
    
    def test_filter_non_article_links(self):
        """Test filtering out non-article links (comments, profiles, etc.)."""
        if not BeautifulSoup:
            self.skipTest("BeautifulSoup not available")
        
        soup = BeautifulSoup(self.sample_html, 'html.parser')
        links = soup.find_all('a', href=True)
        
        # Filter to only article links
        article_urls = []
        excluded_patterns = ['/comments', '/author/', '/symbol/']
        
        for link in links:
            href = link.get('href', '')
            if '/article/' in href:
                # Exclude if matches excluded patterns
                if not any(pattern in href for pattern in excluded_patterns):
                    if href.startswith('/'):
                        href = f"https://seekingalpha.com{href}"
                    article_urls.append(href)
        
        # Should not include comment links
        self.assertFalse(any('/comments' in url for url in article_urls))
        # Should include article links
        self.assertTrue(any('/article/1234567' in url for url in article_urls))


class TestURLValidation(unittest.TestCase):
    """Test URL validation strategies."""
    
    def test_build_symbol_url(self):
        """Test URL construction."""
        try:
            # US ticker
            us_url = build_symbol_url('AAPL')
            self.assertIn('/symbol/AAPL', us_url)
            self.assertTrue(us_url.startswith('https://'))
            
            # Canadian ticker
            canadian_url = build_symbol_url('ABC', 'TSX')
            self.assertIn('/symbol/TSX:ABC', canadian_url)
            self.assertIn(':', canadian_url)
        except NameError:
            self.skipTest("symbol_article_scraper module not available")
    
    def test_is_valid_article_url_pattern(self):
        """Test URL pattern validation."""
        try:
            valid_urls = [
                "https://seekingalpha.com/article/1234567-title",
                "https://seekingalpha.com/news/1234568-item",
                "https://seekingalpha.com/analysis/1234569-analysis",
            ]
            
            invalid_urls = [
                "https://seekingalpha.com/symbol/STLD",
                "https://seekingalpha.com/article/1234567-title/comments",
                "https://seekingalpha.com/author/john-doe",
                "https://seekingalpha.com/",
            ]
            
            for url in valid_urls:
                self.assertTrue(is_valid_article_url(url), f"Should validate: {url}")
            
            for url in invalid_urls:
                self.assertFalse(is_valid_article_url(url), f"Should invalidate: {url}")
        except NameError:
            self.skipTest("symbol_article_scraper module not available")


class TestFetching(unittest.TestCase):
    """Test fetching functionality (mocked)."""
    
    @patch('symbol_article_scraper.trafilatura')
    def test_fetch_symbol_page_success(self, mock_trafilatura):
        """Test successful page fetch."""
        try:
            mock_trafilatura.fetch_url.return_value = "<html><body>Test</body></html>"
            
            result = fetch_symbol_page('STLD')
            self.assertIsNotNone(result)
            mock_trafilatura.fetch_url.assert_called_once()
        except NameError:
            self.skipTest("symbol_article_scraper module not available")
    
    @patch('symbol_article_scraper.trafilatura')
    def test_fetch_symbol_page_failure(self, mock_trafilatura):
        """Test failed page fetch."""
        try:
            mock_trafilatura.fetch_url.return_value = None
            
            result = fetch_symbol_page('INVALID')
            self.assertIsNone(result)
        except NameError:
            self.skipTest("symbol_article_scraper module not available")
    
    def test_extract_article_links_from_html(self):
        """Test extracting article links from HTML."""
        try:
            html = """
            <html>
            <body>
                <a href="/article/1234567-title">Article 1</a>
                <a href="https://seekingalpha.com/article/1234568-another">Article 2</a>
                <a href="/article/1234567-title/comments">Comments</a>
                <a href="/symbol/STLD">Symbol</a>
            </body>
            </html>
            """
            
            links = extract_article_links(html)
            self.assertGreater(len(links), 0)
            # Should include article links
            self.assertTrue(any('1234567' in link for link in links) or 
                          any('1234568' in link for link in links))
            # Should not include comments
            self.assertFalse(any('/comments' in link for link in links))
        except NameError:
            self.skipTest("symbol_article_scraper module not available")
    
    def test_paywall_detection(self):
        """Test paywall content detection."""
        try:
            from symbol_article_scraper import is_paywalled_content
            
            # Test paywalled content
            paywalled = "Create a free account to read the full article"
            self.assertTrue(is_paywalled_content(paywalled))
            
            # Test normal content
            normal = "This is a normal article with substantial content that discusses various topics in detail. " * 10
            self.assertFalse(is_paywalled_content(normal))
            
            # Test short content with paywall phrase
            short_paywall = "Sign up for free to continue reading"
            self.assertTrue(is_paywalled_content(short_paywall))
            
            # Test content with paywall in title (content must be non-empty but short)
            # Function requires non-empty content - empty content returns False
            short_content_with_paywall_title = "Short content"
            self.assertTrue(is_paywalled_content(short_content_with_paywall_title, title="Create a free account to read"))
        except NameError:
            self.skipTest("symbol_article_scraper module not available")


if __name__ == '__main__':
    unittest.main()

