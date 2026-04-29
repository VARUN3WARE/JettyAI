"""Blog scraper implementation."""

from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from newspaper import Article

from processing.metadata import extract_metadata_from_html
from scraper.base_scraper import BaseScraper
from utils.helpers import clean_text, retry


class BlogScraper(BaseScraper):
    """Scraper for blog articles using newspaper3k with BeautifulSoup fallback."""

    def __init__(self, logger: Any) -> None:
        """Initialize the blog scraper."""
        super().__init__(logger)

    @retry(retries=3, delay=2)
    def _fetch_html(self, url: str) -> str:
        """Fetch HTML content for a URL."""
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text

    def _format_date(self, value: Optional[datetime]) -> Optional[str]:
        """Format a datetime value as YYYY-MM-DD."""
        if not value:
            return None
        return value.strftime("%Y-%m-%d")

    def _extract_with_newspaper(self, url: str, html: str) -> Dict[str, Any]:
        """Extract content and metadata using newspaper3k."""
        article = Article(url)
        article.set_html(html)
        article.parse()
        return {
            "title": article.title or None,
            "author": ", ".join(article.authors) if article.authors else None,
            "published_date": self._format_date(article.publish_date),
            "content": article.text or "",
        }

    def _extract_with_bs4(self, html: str) -> Dict[str, Any]:
        """Extract content using BeautifulSoup as a fallback."""
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        def is_ad_class(value: Any) -> bool:
            """Check if a class attribute indicates an ad element."""
            if isinstance(value, str):
                return "ad" in value.lower()
            if isinstance(value, list):
                return any(isinstance(item, str) and "ad" in item.lower() for item in value)
            return False

        for tag in soup.find_all(True, {"class": is_ad_class}):
            tag.decompose()

        main_node = soup.find("article") or soup.find("main") or soup.body
        raw_text = main_node.get_text(" ") if main_node else soup.get_text(" ")
        return {"content": clean_text(raw_text)}

    def _is_medium_domain(self, url: str) -> bool:
        """Check if a URL is a Medium or Towards Data Science domain."""
        hostname = urlparse(url).hostname or ""
        return "medium.com" in hostname or "towardsdatascience.com" in hostname

    def _extract_medium_content(self, html: str) -> Optional[str]:
        """Extract main article content for Medium-like pages."""
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        article = soup.find("article") or soup.find("main")
        if not article:
            return None

        parts = []
        for tag in article.find_all(["p", "h2", "h3", "h4", "li", "blockquote"]):
            text = tag.get_text(" ", strip=True)
            if text:
                parts.append(text)

        if not parts:
            return None
        return clean_text(" ".join(parts))

    def _looks_paywalled(self, content: str) -> bool:
        """Heuristic check for paywalled or gated content."""
        if not content:
            return True
        word_count = len(content.split())
        if word_count < 80:
            lowered = content.lower()
            indicators = [
                "complete this form",
                "gain instant access",
                "sign in",
                "subscribe",
                "create an account",
            ]
            return any(token in lowered for token in indicators)
        return False

    def scrape(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape blog content and metadata from a URL."""
        try:
            html = self._fetch_html(url)
        except Exception as exc:
            self._logger.warning("Failed to fetch blog HTML: %s", exc)
            return None

        data: Dict[str, Any] = {
            "source_url": url,
            "title": None,
            "author": None,
            "published_date": None,
            "content": "",
            "raw_html": html,
        }

        try:
            extracted = self._extract_with_newspaper(url, html)
            data.update(extracted)
        except Exception as exc:
            self._logger.warning("Newspaper3k parse failed: %s", exc)

        if not data.get("content") and self._is_medium_domain(url):
            medium_text = self._extract_medium_content(html)
            if medium_text:
                data["content"] = medium_text

        if not data.get("content"):
            fallback = self._extract_with_bs4(html)
            data.update(fallback)

        metadata = extract_metadata_from_html(html, url)
        if not data.get("title"):
            data["title"] = metadata.get("title")
        if not data.get("author"):
            data["author"] = metadata.get("author")
        if not data.get("published_date"):
            data["published_date"] = metadata.get("published_date")

        if not data.get("content") and metadata.get("description"):
            data["content"] = metadata.get("description", "")

        data["content"] = clean_text(data.get("content", ""))
        if self._looks_paywalled(data.get("content", "")) and metadata.get("description"):
            data["content"] = clean_text(metadata.get("description", ""))
        if not data.get("author"):
            data["author"] = "Unknown"
        return data
