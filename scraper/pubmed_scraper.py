"""PubMed scraper implementation."""

import io
import re
from typing import Any, Dict, List, Optional

import requests
from Bio import Entrez
from bs4 import BeautifulSoup

from scraper.base_scraper import BaseScraper
from utils.helpers import clean_text, retry


class PubMedScraper(BaseScraper):
    """Scraper for PubMed articles using the Entrez API."""

    def __init__(self, logger: Any) -> None:
        """Initialize the PubMed scraper."""
        super().__init__(logger)

    def _extract_pmid(self, url_or_id: str) -> Optional[str]:
        """Extract PMID from a PubMed URL or direct ID."""
        cleaned = url_or_id.strip()
        if cleaned.isdigit():
            return cleaned
        match = re.search(r"(\d{5,})", cleaned)
        if match:
            return match.group(1)
        return None

    def _extract_year(self, pub_date: Dict[str, Any]) -> Optional[str]:
        """Extract publication year from a PubMed PubDate record."""
        year = pub_date.get("Year") if pub_date else None
        if year:
            return str(year)
        medline_date = pub_date.get("MedlineDate") if pub_date else None
        if medline_date:
            match = re.search(r"(\d{4})", medline_date)
            if match:
                return match.group(1)
        return None

    def _normalize_date_string(self, value: Optional[str]) -> Optional[str]:
        """Normalize date strings to YYYY-MM-DD when possible."""
        if not value:
            return None
        text = value.strip()
        if not text:
            return None
        match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
        if match:
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        match = re.search(r"(\d{4})", text)
        if match:
            year = match.group(1)
            return f"{year}-01-01"
        return None

    def _parse_authors(self, author_list: List[Dict[str, Any]]) -> List[str]:
        """Parse authors list into display names."""
        authors: List[str] = []
        for author in author_list:
            collective = author.get("CollectiveName")
            if collective:
                authors.append(str(collective))
                continue
            fore_name = author.get("ForeName") or ""
            last_name = author.get("LastName") or ""
            full_name = f"{fore_name} {last_name}".strip()
            if full_name:
                authors.append(full_name)
        return authors

    def _build_pubmed_url(self, pmid: str, url_or_id: str) -> str:
        """Build a PubMed URL from a PMID if needed."""
        if "pubmed.ncbi.nlm.nih.gov" in url_or_id:
            return url_or_id
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

    @retry(retries=3, delay=2)
    def _fetch_pubmed_html(self, url: str) -> str:
        """Fetch PubMed HTML as a fallback."""
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text

    def _extract_from_html(self, html: str) -> Dict[str, Any]:
        """Extract PubMed metadata and abstract from HTML."""
        soup = BeautifulSoup(html, "lxml")
        title = None
        authors: List[str] = []
        published_date = None
        abstract = None

        meta_title = soup.find("meta", attrs={"name": "citation_title"})
        if meta_title and meta_title.get("content"):
            title = meta_title.get("content")

        for tag in soup.find_all("meta", attrs={"name": "citation_author"}):
            if tag.get("content"):
                authors.append(tag.get("content"))

        meta_authors = soup.find("meta", attrs={"name": "citation_authors"})
        if meta_authors and meta_authors.get("content") and not authors:
            authors = [item.strip() for item in meta_authors.get("content").split(",") if item.strip()]

        meta_date = (
            soup.find("meta", attrs={"name": "citation_publication_date"})
            or soup.find("meta", attrs={"name": "citation_date"})
            or soup.find("meta", attrs={"name": "citation_online_date"})
        )
        if meta_date and meta_date.get("content"):
            published_date = self._normalize_date_string(meta_date.get("content"))

        meta_abstract = soup.find("meta", attrs={"name": "citation_abstract"})
        if meta_abstract and meta_abstract.get("content"):
            abstract = meta_abstract.get("content")
        if not abstract:
            abstract_div = soup.find("div", class_=re.compile("abstract", re.I))
            if abstract_div:
                abstract = abstract_div.get_text(" ", strip=True)

        return {
            "title": title,
            "author": ", ".join(authors) if authors else None,
            "published_date": published_date,
            "content": clean_text(abstract or title or ""),
        }

    def _scrape_from_html(self, pmid: str, url_or_id: str) -> Optional[Dict[str, Any]]:
        """Scrape PubMed data from HTML when Entrez fails."""
        try:
            url = self._build_pubmed_url(pmid, url_or_id)
            html = self._fetch_pubmed_html(url)
            extracted = self._extract_from_html(html)
            return {
                "source_url": url_or_id,
                "title": extracted.get("title"),
                "author": extracted.get("author") or "Unknown",
                "published_date": extracted.get("published_date"),
                "content": extracted.get("content", ""),
                "raw_html": html,
            }
        except Exception as exc:
            self._logger.warning("PubMed HTML fallback failed for %s: %s", pmid, exc)
            return None

    def scrape(self, url_or_id: str) -> Optional[Dict[str, Any]]:
        """Scrape PubMed metadata and abstract using Entrez."""
        pmid = self._extract_pmid(url_or_id)
        if not pmid:
            self._logger.warning("Unable to extract PMID from %s", url_or_id)
            return None

        Entrez.email = "test@example.com"
        raw_xml: bytes = b""
        try:
            handle = Entrez.efetch(db="pubmed", id=pmid, retmode="xml")
            raw_xml = handle.read()
            handle.close()
            if isinstance(raw_xml, str):
                raw_xml = raw_xml.encode("utf-8")
            bio_handle = io.BytesIO(raw_xml)
            bio_handle.mode = "b"
            records = Entrez.read(bio_handle)
        except Exception as exc:
            self._logger.warning("Entrez fetch failed for %s: %s", pmid, exc)
            fallback = self._scrape_from_html(pmid, url_or_id)
            return fallback

        try:
            article = records["PubmedArticle"][0]["MedlineCitation"]["Article"]
            title = article.get("ArticleTitle")
            journal = article.get("Journal", {}).get("Title")
            abstract_blocks = article.get("Abstract", {}).get("AbstractText", [])
            abstract = " ".join(str(block) for block in abstract_blocks)
            pub_date = article.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
            year = self._extract_year(pub_date)
            published_date = f"{year}-01-01" if year else None

            authors = self._parse_authors(article.get("AuthorList", []))
            author_str = ", ".join(authors) if authors else "Unknown"

            pubmed_data = records["PubmedArticle"][0].get("PubmedData", {})
            ref_list = pubmed_data.get("ReferenceList", [])
            citation_count = 0
            if ref_list:
                for rl in ref_list:
                    citation_count += len(rl.get("Reference", []))

            content = abstract or title or journal or ""
            data: Dict[str, Any] = {
                "source_url": url_or_id,
                "title": title,
                "author": author_str,
                "published_date": published_date,
                "content": clean_text(content),
                "citation_count": citation_count,
                "raw_html": raw_xml.decode("utf-8", errors="ignore"),
            }
            return data
        except Exception as exc:
            self._logger.warning("Failed to parse PubMed record %s: %s", pmid, exc)
            fallback = self._scrape_from_html(pmid, url_or_id)
            return fallback
