"""Trust score calculation logic."""

import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp a score to the provided range."""
    return max(minimum, min(maximum, value))


def _parse_domain(url: str) -> str:
    """Parse the domain from a URL."""
    parsed = urlparse(url)
    return parsed.hostname or ""


def _is_fake_author(author: Optional[str]) -> bool:
    """Detect authors that are only numbers or special characters."""
    if not author:
        return True
    text = author.strip()
    if not text:
        return True
    return bool(re.fullmatch(r"[\W\d_]+", text))


def _author_score(author: Optional[str], domain: str, source_type: str) -> float:
    """Compute author credibility based on author presence and domain."""
    if not author or author.strip().lower() == "unknown" or _is_fake_author(author):
        return 0.2
    if source_type == "pubmed":
        return 0.90
    if domain.endswith(".edu") or domain.endswith(".gov"):
        return 0.95
    if "youtube.com" in domain or "youtu.be" in domain:
        return 0.70
    if domain:
        if domain.endswith(".xyz") or domain.endswith(".info"):
            return 0.40
        return 0.55
    return 0.40


def _author_credibility(author: Optional[str], domain: str, source_type: str) -> float:
    """Handle multiple authors for PubMed and compute final credibility."""
    if source_type == "pubmed" and author:
        authors = [item.strip() for item in author.split(",") if item.strip()]
        if authors:
            scores = [_author_score(item, domain, source_type) for item in authors]
            return sum(scores) / len(scores)
    return _author_score(author, domain, source_type)


def _count_links(text: str) -> int:
    """Count URL-like patterns in text."""
    if not text:
        return 0
    return len(re.findall(r"https?://\S+|www\.\S+", text))


def _citation_score(
    content: str, source_type: str, raw_html: Optional[str] = None, description: Optional[str] = None, explicit_citation_count: Optional[int] = None
) -> float:
    """Calculate citation score based on source type."""
    if explicit_citation_count is not None:
        citations = explicit_citation_count
    elif source_type == "youtube" and description:
        citations = _count_links(description)
    elif source_type == "blog" and raw_html:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_html, "lxml")
        citations = len(soup.find_all("a", href=True))
    else:
        citations = _count_links(content)

    if citations == 0:
        score = 0.1
    elif 1 <= citations <= 3:
        score = 0.4
    elif 4 <= citations <= 10:
        score = 0.7
    else:
        score = 1.0
    if source_type == "pubmed":
        score = min(score + 0.2, 1.0)
    return score


def _domain_authority(url: str) -> float:
    """Assess domain authority using heuristic rules."""
    domain = _parse_domain(url)
    if domain.endswith(".gov"):
        return 0.95
    if domain.endswith(".edu"):
        return 0.90
    if domain == "pubmed.ncbi.nlm.nih.gov":
        return 0.95
    if "youtube.com" in domain or "youtu.be" in domain:
        return 0.70
    if "medium.com" in domain:
        return 0.60
    if domain.endswith(".org"):
        return 0.65
    if domain.endswith(".com"):
        news_domains = {"bbc.com", "cnn.com", "nytimes.com", "reuters.com", "theguardian.com"}
        if any(domain.endswith(item) for item in news_domains):
            return 0.75
        return 0.45
    if domain.endswith(".xyz") or domain.endswith(".info"):
        return 0.20
    return 0.40


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Parse a YYYY-MM-DD date string to a date object."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def _recency_score(published_date: Optional[str], logger: Any) -> float:
    """Compute recency score based on published date."""
    if not published_date:
        logger.warning("Missing published_date; using recency penalty.")
        return 0.3
    parsed = _parse_date(published_date)
    if not parsed:
        logger.warning("Invalid published_date format; using recency penalty.")
        return 0.3

    days_old = (date.today() - parsed).days
    years_old = days_old / 365.25
    if years_old < 1:
        return 1.0
    if years_old < 2:
        return 0.80
    if years_old < 3:
        return 0.65
    if years_old < 5:
        return 0.45
    return 0.20


def _medical_topic_detected(topic_tags: List[str]) -> bool:
    """Detect medical topic keywords in tags."""
    medical_terms = {"health", "medicine", "medical", "disease", "treatment", "drug"}
    for tag in topic_tags:
        lowered = tag.lower()
        if any(term in lowered for term in medical_terms):
            return True
    return False


def _disclaimer_score(content: str, source_type: str, topic_tags: List[str]) -> float:
    """Score disclaimer presence for medical topics."""
    if not _medical_topic_detected(topic_tags):
        return 1.0

    text = (content or "").lower()
    phrases = ["consult a doctor", "not medical advice", "healthcare professional"]
    if any(phrase in text for phrase in phrases):
        return 0.90
    return 0.10


def _link_density(content: str, raw_html: Optional[str]) -> float:
    """Compute link density as links per word."""
    words = re.findall(r"\b\w+\b", content or "")
    word_count = len(words)
    if word_count == 0:
        return 0.0
    link_count = _count_links(raw_html or content or "")
    return link_count / word_count


def calculate_trust_score(
    author: Optional[str],
    content: str,
    url: str,
    published_date: Optional[str],
    source_type: str,
    topic_tags: List[str],
    raw_html: Optional[str],
    logger: Any,
    description: Optional[str] = None,
    explicit_citation_count: Optional[int] = None,
    return_breakdown: bool = False,
) -> Union[float, Tuple[float, Dict[str, float]]]:
    """Calculate the trust score for a scraped source."""
    domain = _parse_domain(url)
    author_score = _clamp(_author_credibility(author, domain, source_type))
    citation_score = _clamp(_citation_score(content, source_type, raw_html, description, explicit_citation_count))
    domain_score = _clamp(_domain_authority(url))
    recency_score = _clamp(_recency_score(published_date, logger))
    disclaimer_score = _clamp(_disclaimer_score(content, source_type, topic_tags))

    trust_score = (
        0.25 * author_score
        + 0.20 * citation_score
        + 0.20 * domain_score
        + 0.20 * recency_score
        + 0.15 * disclaimer_score
    )

    if _link_density(content, raw_html) > (1 / 50):
        trust_score = max(0.0, trust_score - 0.15)

    if domain_score < 0.35:
        trust_score = min(trust_score, 0.50)

    parsed_date = _parse_date(published_date)
    if parsed_date:
        years_old = (date.today() - parsed_date).days / 365.25
        if years_old >= 5:
            trust_score = min(trust_score, 0.55)
    trust_score = _clamp(trust_score)

    if return_breakdown:
        breakdown = {
            "author_credibility": author_score,
            "domain_authority": domain_score,
            "recency": recency_score,
            "citations": citation_score,
            "disclaimer": disclaimer_score,
        }
        return trust_score, breakdown

    return trust_score
