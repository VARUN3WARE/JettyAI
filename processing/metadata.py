"""Metadata extraction helpers for HTML documents."""

import json
import re
from datetime import datetime
from typing import Any, Dict, Optional

from bs4 import BeautifulSoup


def _parse_date_string(value: Optional[str]) -> Optional[str]:
    """Parse a date string into YYYY-MM-DD when possible."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass

    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    match = re.search(r"(\d{4})", text)
    if match:
        year = match.group(1)
        return f"{year}-01-01"

    return None


def _extract_json_ld(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extract metadata fields from JSON-LD blocks."""
    data: Dict[str, Any] = {}
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            content = script.string or ""
            if not content.strip():
                continue
            parsed = json.loads(content)
            items = parsed if isinstance(parsed, list) else [parsed]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if "author" in item and not data.get("author"):
                    author = item.get("author")
                    if isinstance(author, dict):
                        data["author"] = author.get("name")
                    elif isinstance(author, list):
                        names = [a.get("name") for a in author if isinstance(a, dict)]
                        data["author"] = ", ".join(name for name in names if name)
                    else:
                        data["author"] = str(author)
                if "datePublished" in item and not data.get("published_date"):
                    data["published_date"] = _parse_date_string(str(item.get("datePublished")))
                if "headline" in item and not data.get("title"):
                    data["title"] = item.get("headline")
        except Exception:
            continue
    return data


def extract_metadata_from_html(html: str, url: str) -> Dict[str, Optional[str]]:
    """Extract author, date, title, and description from HTML."""
    soup = BeautifulSoup(html, "lxml")

    title = None
    author = None
    published_date = None
    description = None

    meta_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if meta_title and meta_title.get("content"):
        title = meta_title.get("content")
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    meta_author = soup.find("meta", attrs={"name": "author"})
    if meta_author and meta_author.get("content"):
        author = meta_author.get("content")
    if not author:
        meta_author = soup.find("meta", property="article:author") or soup.find("meta", attrs={"name": "byline"})
        if meta_author and meta_author.get("content"):
            author = meta_author.get("content")

    byline = soup.find(attrs={"class": re.compile("author|byline", re.I)})
    if not author and byline:
        author = byline.get_text(" ", strip=True)

    meta_date = soup.find("meta", property="article:published_time")
    if meta_date and meta_date.get("content"):
        published_date = _parse_date_string(meta_date.get("content"))

    if not published_date:
        time_tag = soup.find("time")
        if time_tag:
            published_date = _parse_date_string(time_tag.get("datetime") or time_tag.get_text())

    meta_description = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
    if meta_description and meta_description.get("content"):
        description = meta_description.get("content")

    json_ld = _extract_json_ld(soup)
    author = author or json_ld.get("author")
    published_date = published_date or json_ld.get("published_date")
    title = title or json_ld.get("title")

    return {
        "author": author or "Unknown",
        "published_date": published_date,
        "title": title,
        "description": description,
    }
