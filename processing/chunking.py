"""Paragraph-based chunking utilities."""

import re
from typing import Any, List

from utils.helpers import clean_text


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using punctuation boundaries."""
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]


def _split_long_words(words: List[str], max_words: int) -> List[List[str]]:
    """Split a long list of words into fixed-size chunks."""
    return [words[i : i + max_words] for i in range(0, len(words), max_words)]


def chunk_text(text: str, logger: Any) -> List[str]:
    """Chunk text into 200-300 word segments using paragraphs and sentences."""
    if not text:
        return []

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.strip() for p in normalized.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current: List[str] = []
    current_count = 0

    def flush_current() -> None:
        """Flush the current buffer into a chunk."""
        nonlocal current, current_count
        if current:
            chunk = clean_text(" ".join(current))
            if chunk:
                chunks.append(chunk)
        current = []
        current_count = 0

    for paragraph in paragraphs:
        words = paragraph.split()
        if len(words) > 300:
            flush_current()
            sentences = _split_sentences(paragraph)
            for sentence in sentences:
                sentence_words = sentence.split()
                if not sentence_words:
                    continue
                if len(sentence_words) > 300:
                    for block in _split_long_words(sentence_words, 300):
                        chunk = clean_text(" ".join(block))
                        if chunk:
                            chunks.append(chunk)
                    continue
                if current_count + len(sentence_words) <= 300:
                    current.append(sentence)
                    current_count += len(sentence_words)
                else:
                    flush_current()
                    current.append(sentence)
                    current_count = len(sentence_words)
                if current_count >= 200:
                    flush_current()
        else:
            if current_count + len(words) <= 300:
                current.append(paragraph)
                current_count += len(words)
            else:
                flush_current()
                current.append(paragraph)
                current_count = len(words)
            if current_count >= 200:
                flush_current()

    flush_current()
    if not chunks:
        logger.warning("Chunking produced no output.")
    return chunks
