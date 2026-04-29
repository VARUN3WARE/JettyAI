"""Abstract base class for scrapers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseScraper(ABC):
    """Abstract base scraper defining the scrape contract."""

    def __init__(self, logger: Any) -> None:
        """Initialize the scraper with a logger instance."""
        self._logger = logger

    @abstractmethod
    def scrape(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape a URL and return a dictionary of extracted data."""
        raise NotImplementedError
