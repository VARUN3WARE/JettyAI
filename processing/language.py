"""Language and region detection utilities."""

from typing import Any, Optional
from urllib.parse import urlparse

from langdetect import DetectorFactory, LangDetectException, detect


def detect_language(text: str, logger: Any) -> Optional[str]:
    """Detect language code for the provided text."""
    if not text:
        return None
    try:
        DetectorFactory.seed = 0
        return detect(text)
    except LangDetectException:
        return None
    except Exception as exc:
        logger.warning("Language detection failed: %s", exc)
        return None


def detect_region(url: str) -> Optional[str]:
    """Detect region based on the URL TLD."""
    if not url:
        return None
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not hostname:
        return None
    tld = hostname.split(".")[-1].lower()
    if tld == "in":
        return "India"
    if tld == "uk":
        return "UK"
    if tld == "com":
        return None
    return None
