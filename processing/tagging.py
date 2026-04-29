"""Topic tagging using RAKE with TF-IDF fallback."""

import re
from typing import Any, List

from rake_nltk import Rake
from sklearn.feature_extraction.text import TfidfVectorizer
import nltk

from utils.helpers import clean_text


def _sanitize_text(text: str) -> str:
    """Remove noisy tokens like URLs, timecodes, and hashtags for tagging."""
    cleaned = re.sub(r"https?://\S+|www\.\S+", " ", text)
    cleaned = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", cleaned)
    cleaned = re.sub(r"#[A-Za-z0-9_]+", " ", cleaned)
    cleaned = re.sub(r"\b\w+\s*\(\s*\)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _ensure_nltk_resources(logger: Any) -> None:
    """Ensure required NLTK resources are available."""
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        try:
            nltk.download("punkt", quiet=True)
        except Exception as exc:
            logger.warning("NLTK punkt download failed: %s", exc)
    try:
        nltk.data.find("corpora/stopwords")
    except LookupError:
        try:
            nltk.download("stopwords", quiet=True)
        except Exception as exc:
            logger.warning("NLTK stopwords download failed: %s", exc)


def _dedupe_preserve(items: List[str]) -> List[str]:
    """Remove duplicates while preserving order."""
    seen = set()
    result: List[str] = []
    for item in items:
        key = item.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item.strip())
    return result


def _code_words() -> set:
    """Return a set of code-like tokens to exclude from tags."""
    return {
        "def",
        "class",
        "return",
        "import",
        "from",
        "int",
        "float",
        "str",
        "list",
        "dict",
        "true",
        "false",
        "none",
        "null",
        "lambda",
        "for",
        "while",
        "if",
        "elif",
        "else",
        "try",
        "except",
        "print",
        "var",
        "let",
        "const",
        "function",
        "public",
        "private",
        "static",
    }


def _normalize_tag(tag: str) -> str:
    """Normalize tag text by removing symbols and extra whitespace."""
    cleaned = re.sub(r"[^A-Za-z0-9\s-]", " ", tag)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _filter_tags(tags: List[str]) -> List[str]:
    """Filter tags to keep only meaningful keyword phrases."""
    filtered: List[str] = []
    code_words = _code_words()
    for tag in tags:
        text = _normalize_tag(tag)
        if len(text) < 3 or len(text) > 80:
            continue
        if re.search(r"https?://|www\.", text):
            continue
        if re.search(r"\d{1,2}:\d{2}", text):
            continue
        alpha_count = sum(1 for ch in text if ch.isalpha())
        if alpha_count < max(3, len(text) // 3):
            continue
        lowered = text.lower()
        words = [word for word in lowered.split() if word]
        if any(len(word) < 3 for word in words):
            continue
        if any(word in code_words for word in words):
            continue
        blocked = [
            "patreon",
            "subscribe",
            "donation",
            "wishlist",
            "amazon",
            "youtube",
            "youtu",
        ]
        if any(word in lowered for word in blocked):
            continue
        filtered.append(text)
    return filtered


def _extract_noun_phrases(text: str, logger: Any) -> List[str]:
    """Extract noun phrases with spaCy when available."""
    try:
        import spacy

        try:
            nlp = spacy.load("en_core_web_sm")
        except Exception:
            return []
        doc = nlp(text)
        return [chunk.text for chunk in doc.noun_chunks]
    except Exception:
        return []


def _ensure_minimum_tags(tags: List[str], text: str) -> List[str]:
    """Ensure at least three tags by adding cleaned keywords from text."""
    if len(tags) >= 3:
        return tags
    code_words = _code_words()
    words = re.findall(r"\b[a-zA-Z][a-zA-Z-]{2,}\b", text.lower())
    for word in words:
        if word in code_words:
            continue
        if word in (tag.lower() for tag in tags):
            continue
        tags.append(word)
        if len(tags) >= 3:
            break
    return tags


def _tfidf_keywords(text: str, logger: Any, max_tags: int) -> List[str]:
    """Generate keywords using TF-IDF."""
    try:
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=20)
        matrix = vectorizer.fit_transform([text])
        scores = matrix.toarray().flatten()
        features = vectorizer.get_feature_names_out()
        ranked = sorted(zip(features, scores), key=lambda x: x[1], reverse=True)
        return [word for word, score in ranked[:max_tags] if score > 0]
    except Exception as exc:
        logger.warning("TF-IDF tagging failed: %s", exc)
        return []


def _fallback_keywords(text: str, max_tags: int, logger: Any) -> List[str]:
    """Fallback keyword extraction based on word frequency."""
    tokens = re.findall(r"\b\w+\b", text.lower())
    try:
        from nltk.corpus import stopwords

        stopword_set = set(stopwords.words("english"))
    except Exception as exc:
        logger.warning("Stopwords unavailable, using minimal list: %s", exc)
        stopword_set = {"the", "and", "for", "with", "that", "this", "from", "into", "are", "was"}

    freq: dict = {}
    for token in tokens:
        if len(token) < 3 or token in stopword_set:
            continue
        freq[token] = freq.get(token, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [word for word, _ in ranked[:max_tags]]


def generate_topic_tags(text: str, logger: Any) -> List[str]:
    """Generate topic tags using RAKE with TF-IDF fallback."""
    cleaned = clean_text(text)
    if not cleaned:
        return []

    sanitized = _sanitize_text(cleaned)
    if not sanitized:
        return []

    _ensure_nltk_resources(logger)

    noun_phrases = _extract_noun_phrases(sanitized, logger)

    try:
        rake = Rake()
        rake.extract_keywords_from_text(sanitized)
        rake_tags = rake.get_ranked_phrases()[:5]
    except Exception as exc:
        logger.warning("RAKE tagging failed: %s", exc)
        rake_tags = []

    tags = _filter_tags(_dedupe_preserve(noun_phrases + rake_tags))
    if len(tags) < 3:
        tfidf_tags = _tfidf_keywords(sanitized, logger, max_tags=5)
        tags = _filter_tags(_dedupe_preserve(tags + tfidf_tags))

    if len(tags) < 3:
        extra = _fallback_keywords(sanitized, max_tags=5, logger=logger)
        tags = _filter_tags(_dedupe_preserve(tags + extra))

    if len(tags) < 3:
        tokens = re.findall(r"\b\w+\b", sanitized.lower())
        tags = _filter_tags(_dedupe_preserve(tags + tokens))

    tags = _ensure_minimum_tags(tags, sanitized)
    return tags[:5] if len(tags) > 5 else tags
