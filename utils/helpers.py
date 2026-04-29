"""Shared helper utilities for the scraping pipeline."""

import hashlib
import logging
import os
import re
import time
from typing import Any, Callable, Optional

from bs4 import BeautifulSoup

def retry(func: Optional[Callable[..., Any]] = None, retries: int = 3, delay: int = 2) -> Callable[..., Any]:
    """Retry decorator for transient failures."""

    def decorator(inner_func: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a function with retry behavior."""
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Execute the wrapped function with retries."""
            last_exc: Optional[Exception] = None
            for _ in range(retries):
                try:
                    return inner_func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    time.sleep(delay)
            if last_exc:
                raise last_exc
            return None

        return wrapper

    if func:
        return decorator(func)
    return decorator


def clean_text(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    if not text:
        return ""
    soup = BeautifulSoup(text, "lxml")
    cleaned = soup.get_text(" ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging to console and file."""
    logger = logging.getLogger("scraper")
    if logger.handlers:
        return logger

    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    file_handler = logging.FileHandler(os.path.join(base_dir, "scraper.log"))
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def safe_get(source: Any, key: str, default: Any = None) -> Any:
    """Safely get a value from a dictionary-like object."""
    if isinstance(source, dict):
        return source.get(key, default)
    return default


def save_raw_content(output_dir: str, url: str, content: str, logger: Any) -> None:
    """Save raw HTML or text content to disk with a stable filename."""
    try:
        os.makedirs(output_dir, exist_ok=True)
        hash_digest = hashlib.md5(url.encode("utf-8")).hexdigest()
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", url)[:60]
        file_path = os.path.join(output_dir, f"{safe_name}_{hash_digest}.txt")
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(content)
    except Exception as exc:
        logger.warning("Failed to save raw content: %s", exc)
