"""YouTube scraper implementation."""

import json
import os
import re
from http.cookiejar import MozillaCookieJar
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from pytube import YouTube
from yt_dlp import YoutubeDL
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

from scraper.base_scraper import BaseScraper
from utils.helpers import clean_text, retry


class YouTubeScraper(BaseScraper):
    """Scraper for YouTube metadata and transcripts."""

    def __init__(self, logger: Any, cookies_path: Optional[str] = None) -> None:
        """Initialize the YouTube scraper."""
        super().__init__(logger)
        self._cookies_path = cookies_path
        self._cookiejar = self._load_cookiejar()

    def _load_cookiejar(self) -> Optional[MozillaCookieJar]:
        """Load cookies from a Netscape cookies.txt file when provided."""
        if not self._cookies_path:
            return None
        if not os.path.isfile(self._cookies_path):
            self._logger.warning("Cookies file not found: %s", self._cookies_path)
            return None
        if os.path.getsize(self._cookies_path) == 0:
            self._logger.warning("Cookies file is empty: %s", self._cookies_path)
            return None

        jar = MozillaCookieJar()
        try:
            jar.load(self._cookies_path, ignore_discard=True, ignore_expires=True)
        except Exception as exc:
            self._logger.warning("Failed to load cookies file: %s", exc)
            return None
        return jar

    def _format_date(self, value: Optional[datetime]) -> Optional[str]:
        """Format a datetime value as YYYY-MM-DD."""
        if not value:
            return None
        return value.strftime("%Y-%m-%d")

    def _normalize_date_string(self, value: Optional[str]) -> Optional[str]:
        """Normalize a date string to YYYY-MM-DD when possible."""
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
            match = re.search(r"\d{4}-\d{2}-\d{2}", text)
            return match.group(0) if match else None

    def _trim_description(self, description: str) -> str:
        """Trim noisy promotional sections from descriptions."""
        if not description:
            return ""
        stop_markers = [
            "support my channel",
            "become a channel member",
            "you can find me on",
            "subscribe",
            "follow me",
            "patreon",
        ]
        lowered = description.lower()
        cut_index = None
        for marker in stop_markers:
            index = lowered.find(marker)
            if index != -1 and (cut_index is None or index < cut_index):
                cut_index = index
        if cut_index and cut_index > 50:
            return description[:cut_index].strip()
        return description

    def _parse_upload_date(self, value: Optional[str]) -> Optional[str]:
        """Parse YYYYMMDD or ISO date strings into YYYY-MM-DD."""
        if not value:
            return None
        text = value.strip()
        if re.fullmatch(r"\d{8}", text):
            return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
        return self._normalize_date_string(text)

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract the YouTube video ID from a URL."""
        parsed = urlparse(url)
        if parsed.hostname in {"youtu.be"}:
            return parsed.path.lstrip("/") or None
        if parsed.hostname and "youtube.com" in parsed.hostname:
            if parsed.path == "/watch":
                query = parse_qs(parsed.query)
                return query.get("v", [None])[0]
            match = re.search(r"/shorts/([^/?]+)", parsed.path)
            if match:
                return match.group(1)
        return None

    @retry(retries=2, delay=2)
    def _fetch_watch_html(self, url: str) -> str:
        """Fetch the YouTube watch page HTML."""
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, cookies=self._cookiejar, timeout=15)
        response.raise_for_status()
        return response.text

    def _extract_player_response(self, html: str) -> Optional[Dict[str, Any]]:
        """Extract the ytInitialPlayerResponse JSON block from HTML."""
        marker = "ytInitialPlayerResponse"
        start = html.find(marker)
        if start == -1:
            return None
        brace_start = html.find("{", start)
        if brace_start == -1:
            return None
        depth = 0
        end = None
        for index in range(brace_start, len(html)):
            char = html[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            return None
        try:
            return json.loads(html[brace_start:end])
        except Exception:
            return None

    def _extract_metadata_from_html(self, html: str) -> Dict[str, Optional[str]]:
        """Extract metadata from YouTube HTML as a fallback."""
        data: Dict[str, Optional[str]] = {
            "title": None,
            "author": None,
            "published_date": None,
            "description": None,
        }

        player_response = self._extract_player_response(html)
        if player_response:
            details = player_response.get("videoDetails", {})
            microformat = (
                player_response.get("microformat", {})
                .get("playerMicroformatRenderer", {})
            )
            data["title"] = details.get("title")
            data["author"] = details.get("author")
            data["description"] = details.get("shortDescription")
            data["published_date"] = self._normalize_date_string(microformat.get("publishDate"))

        if any(data.values()):
            return data

        soup = BeautifulSoup(html, "lxml")
        meta_title = soup.find("meta", property="og:title") or soup.find("meta", itemprop="name")
        if meta_title and meta_title.get("content"):
            data["title"] = meta_title.get("content")
        meta_desc = soup.find("meta", property="og:description") or soup.find("meta", itemprop="description")
        if meta_desc and meta_desc.get("content"):
            data["description"] = meta_desc.get("content")
        meta_author = soup.find("meta", itemprop="author")
        if meta_author and meta_author.get("content"):
            data["author"] = meta_author.get("content")
        meta_date = soup.find("meta", itemprop="datePublished")
        if meta_date and meta_date.get("content"):
            data["published_date"] = self._normalize_date_string(meta_date.get("content"))

        return data

    def _extract_caption_url_from_html(self, html: str) -> Optional[str]:
        """Extract a caption track URL from the player response JSON."""
        player_response = self._extract_player_response(html)
        if not player_response:
            return None
        captions = player_response.get("captions", {})
        tracklist = captions.get("playerCaptionsTracklistRenderer", {})
        tracks = tracklist.get("captionTracks", [])
        if not tracks:
            return None

        preferred = ["en", "en-US", "en-GB"]
        for lang in preferred:
            for track in tracks:
                if track.get("languageCode") == lang and track.get("baseUrl"):
                    base_url = track.get("baseUrl")
                    if "fmt=" not in base_url:
                        base_url = f"{base_url}&fmt=vtt"
                    return base_url

        first = tracks[0].get("baseUrl") if tracks else None
        if first and "fmt=" not in first:
            first = f"{first}&fmt=vtt"
        return first

    def _build_yt_dlp_options(self) -> Dict[str, Any]:
        """Build yt-dlp options, including cookies when available."""
        class YtDlpLogger:
            """Silence yt-dlp console output and route errors to the pipeline logger."""

            def __init__(self, parent_logger: Any) -> None:
                """Initialize with the pipeline logger."""
                self._parent_logger = parent_logger

            def debug(self, message: str) -> None:
                """Ignore debug messages."""
                return None

            def warning(self, message: str) -> None:
                """Ignore warnings to keep output clean."""
                return None

            def error(self, message: str) -> None:
                """Log yt-dlp errors once."""
                self._parent_logger.warning("yt-dlp error: %s", message)

        options: Dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "no_warnings": True,
            "ignore_no_formats_error": True,
            "allow_unplayable_formats": True,
            "logger": YtDlpLogger(self._logger),
        }

        if self._cookies_path and os.path.isfile(self._cookies_path):
            if os.path.getsize(self._cookies_path) > 0:
                options["cookiefile"] = self._cookies_path
        return options

    def _fetch_yt_dlp_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch metadata using yt-dlp without downloading media."""
        options = self._build_yt_dlp_options()
        with YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=False)

    def _extract_metadata_from_yt_dlp(self, info: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """Extract title, author, date, and description from yt-dlp info."""
        return {
            "title": info.get("title"),
            "author": info.get("uploader") or info.get("channel") or info.get("uploader_id"),
            "published_date": self._parse_upload_date(info.get("upload_date") or info.get("release_date")),
            "description": info.get("description"),
        }

    def _pick_subtitle_url(self, subtitles: Dict[str, Any]) -> Optional[str]:
        """Pick a subtitle URL from yt-dlp subtitle metadata."""
        preferred_langs = ["en", "en-US", "en-GB"]
        for lang in preferred_langs:
            entries = subtitles.get(lang)
            if not entries:
                continue
            for ext in ["vtt", "srv3", "ttml", "srt"]:
                for entry in entries:
                    if entry.get("ext") == ext and entry.get("url"):
                        return entry.get("url")
            for entry in entries:
                if entry.get("url"):
                    return entry.get("url")
        return None

    def _extract_subtitle_text(self, payload: str) -> str:
        """Extract plain text from subtitle payloads (VTT/SRT)."""
        lines = []
        for line in payload.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("WEBVTT") or stripped.startswith("NOTE"):
                continue
            if re.fullmatch(r"\d+", stripped):
                continue
            if re.match(r"\d{2}:\d{2}:\d{2}[\.,]\d{3} -->", stripped):
                continue
            lines.append(stripped)
        return clean_text(" ".join(lines))

    def _fetch_subtitle_text(self, url: str) -> Optional[str]:
        """Download and parse subtitle text from a URL."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            }
            response = requests.get(url, headers=headers, cookies=self._cookiejar, timeout=15)
            response.raise_for_status()
            return self._extract_subtitle_text(response.text)
        except Exception:
            return None

    def _fetch_transcript(
        self,
        video_id: str,
        yt_dlp_info: Optional[Dict[str, Any]],
        html: Optional[str],
    ) -> Optional[str]:
        """Fetch transcript text using APIs, yt-dlp, or HTML caption tracks."""
        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
            text = " ".join(entry.get("text", "") for entry in transcript)
            return clean_text(text)
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
            pass
        except Exception:
            pass

        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            try:
                transcript = transcript_list.find_manually_created_transcript(["en"])
            except Exception:
                transcript = transcript_list.find_generated_transcript(["en"])
            entries = transcript.fetch()
            text = " ".join(entry.get("text", "") for entry in entries)
            return clean_text(text)
        except Exception:
            pass

        if yt_dlp_info:
            subtitles = yt_dlp_info.get("subtitles") or {}
            auto_captions = yt_dlp_info.get("automatic_captions") or {}
            url = self._pick_subtitle_url(subtitles) or self._pick_subtitle_url(auto_captions)
            if url:
                return self._fetch_subtitle_text(url)

        if html:
            caption_url = self._extract_caption_url_from_html(html)
            if caption_url:
                return self._fetch_subtitle_text(caption_url)
        return None

    def scrape(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape YouTube metadata and transcript."""
        video_id = self._extract_video_id(url)
        if not video_id:
            self._logger.warning("Unable to parse YouTube ID from %s", url)
            return None

        data: Dict[str, Any] = {
            "source_url": url,
            "title": None,
            "author": None,
            "published_date": None,
            "content": "",
            "description": "",
            "raw_html": None,
        }

        description = ""
        html = ""
        yt_dlp_info: Optional[Dict[str, Any]] = None
        metadata_error: Optional[Exception] = None
        try:
            yt_dlp_info = self._fetch_yt_dlp_info(url)
            if yt_dlp_info:
                info_data = self._extract_metadata_from_yt_dlp(yt_dlp_info)
                data["title"] = info_data.get("title") or data.get("title")
                data["author"] = info_data.get("author") or data.get("author")
                data["published_date"] = info_data.get("published_date") or data.get("published_date")
                description = info_data.get("description") or description
        except Exception as exc:
            metadata_error = exc

        if not data.get("title") or not data.get("author") or not data.get("published_date"):
            try:
                yt = YouTube(url)
                data["title"] = data.get("title") or yt.title
                data["author"] = data.get("author") or yt.author
                data["published_date"] = data.get("published_date") or self._format_date(yt.publish_date)
                description = description or (yt.description or "")
            except Exception as exc:
                metadata_error = metadata_error or exc

        try:
            html = self._fetch_watch_html(url)
        except Exception as exc:
            self._logger.warning("Failed to fetch YouTube HTML: %s", exc)

        if html:
            fallback = self._extract_metadata_from_html(html)
            if not data.get("title"):
                data["title"] = fallback.get("title")
            if not data.get("author"):
                data["author"] = fallback.get("author")
            if not data.get("published_date"):
                data["published_date"] = fallback.get("published_date")
            if not description:
                description = fallback.get("description") or ""

        if not any([data.get("title"), data.get("author"), data.get("published_date"), description]):
            if metadata_error:
                self._logger.warning("YouTube metadata unavailable: %s", metadata_error)
            else:
                self._logger.warning("YouTube metadata unavailable for %s", url)

        description = self._trim_description(description)

        transcript_text = self._fetch_transcript(video_id, yt_dlp_info, html)
        if transcript_text:
            data["content"] = transcript_text
            data["raw_html"] = transcript_text
        else:
            if description:
                self._logger.warning("Transcript unavailable; using description fallback: %s", url)
                data["content"] = description
                data["raw_html"] = description
            else:
                data["content"] = data.get("title") or ""
                data["raw_html"] = data["content"]

        data["content"] = clean_text(data.get("content", ""))
        data["description"] = description
        if not data.get("author"):
            data["author"] = "Unknown"
        return data
