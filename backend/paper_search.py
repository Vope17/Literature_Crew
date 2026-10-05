"""Bounded, paced arXiv searches shared by all requests in this process."""

import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests

from search_filters import SearchFilters

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
TOTAL = "{http://a9.com/-/spec/opensearch/1.1/}totalResults"


@dataclass(frozen=True)
class Paper:
    title: str
    authors: list[str]
    year: int
    url: str
    pdf_url: str
    abstract: str
    doi: str | None = None


class SearchError(Exception):
    def __init__(self, message: str, status_code: int = 502, retry_after: int = 0):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def retry_seconds(value: str | None, default: int) -> int:
    try:
        return max(1, math.ceil(float(value)))
    except (TypeError, ValueError, OverflowError):
        try:
            return max(1, math.ceil(parsedate_to_datetime(value).timestamp() - time.time()))
        except (TypeError, ValueError, OverflowError):
            return default


def search_query(topic: str) -> str:
    # Preserve advanced arXiv syntax; qualify ordinary search terms explicitly.
    if re.search(r'\b(?:all|ti|au|abs|cat|id|co|jr|rn|doi|submittedDate|lastUpdatedDate):', topic):
        return topic
    terms = re.findall(r'"[^"]+"|[^\s"]+', topic)
    return " AND ".join(f"all:{term}" for term in terms)


def parse_feed(content: bytes) -> list[Paper]:
    try:
        root = ET.fromstring(content)
        if root.tag != f"{ATOM}feed":
            raise ValueError("Not an Atom feed")
        entries = root.findall(f"{ATOM}entry")
        if any("/api/errors" in entry.findtext(f"{ATOM}id", "") for entry in entries):
            raise SearchError("arXiv rejected this query. Check its syntax or try simple keywords.", 400)
        total = int(root.findtext(TOTAL, ""))
        if total and not entries:
            raise ValueError("Incomplete feed")
        papers = []
        for entry in entries:
            identifier = urlsplit(entry.findtext(f"{ATOM}id", "")).path.removeprefix("/abs/")
            if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?", identifier):
                raise ValueError("Invalid paper identifier")
            papers.append(Paper(
                title=" ".join(entry.findtext(f"{ATOM}title", "").split()),
                authors=[author.findtext(f"{ATOM}name", "") for author in entry.findall(f"{ATOM}author")],
                year=int(entry.findtext(f"{ATOM}published", "")[:4]),
                url=f"https://arxiv.org/abs/{identifier}",
                pdf_url=f"https://arxiv.org/pdf/{identifier}",
                abstract=entry.findtext(f"{ATOM}summary", "").strip(),
                doi=entry.findtext(f"{ARXIV}doi"),
            ))
        return papers
    except (ET.ParseError, ValueError) as exc:
        raise SearchError("arXiv returned an invalid response. Please try again later.") from exc


class ArxivSearch:
    def __init__(self):
        self._lock = threading.Lock()
        self._next_request_at = 0.0
        self._blocked_until = 0.0
        self._blocked_error = None
        self._cache = {}

    def search(self, topic: str, limit: int = 5, *, filters: SearchFilters | None = None) -> list[Paper]:
        topic = " ".join(topic.split())
        if not topic or not search_query(topic):
            raise ValueError("Enter a research topic.")
        if not 1 <= limit <= 10:
            raise ValueError("Search limit must be between 1 and 10.")
        filters = filters or SearchFilters()
        query = filters.arxiv_query(search_query(topic))
        key = (query, limit)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return list(cached[1])
            if self._blocked_until > time.monotonic():
                seconds = math.ceil(self._blocked_until - time.monotonic())
                raise SearchError(str(self._blocked_error), self._blocked_error.status_code, seconds)

            for attempt in range(3):
                time.sleep(max(0, self._next_request_at - time.monotonic()))
                try:
                    response = requests.get(
                        "https://export.arxiv.org/api/query",
                        params={"search_query": query, "start": 0, "max_results": limit, "sortBy": "relevance"},
                        headers={"User-Agent": "LiteratureCrew/0.1", "Accept": "application/atom+xml"},
                        timeout=(10, 20),
                    )
                except requests.Timeout as exc:
                    if attempt == 2:
                        raise SearchError("arXiv timed out. Try again later or use fewer search terms.", 504) from exc
                    continue
                except requests.ConnectionError as exc:
                    if attempt == 2:
                        raise SearchError("Cannot connect to arXiv. Check the backend's internet connection, DNS, or proxy.", 503) from exc
                    continue
                finally:
                    self._next_request_at = time.monotonic() + 3

                with response:
                    if response.status_code == 429:
                        seconds = retry_seconds(response.headers.get("Retry-After"), 60)
                        self._blocked_until = time.monotonic() + seconds
                        self._blocked_error = SearchError("arXiv is rate-limiting requests from this server. Please wait before searching again.", 429, seconds)
                        raise self._blocked_error
                    if response.status_code in (500, 502, 503, 504):
                        seconds = retry_seconds(response.headers.get("Retry-After"), 3 * (attempt + 1))
                        self._next_request_at = time.monotonic() + seconds
                        if attempt < 2 and seconds <= 10:
                            continue
                        self._blocked_until = self._next_request_at
                        self._blocked_error = SearchError(f"arXiv is temporarily unavailable (HTTP {response.status_code}). Please try again later.", 503, seconds)
                        raise self._blocked_error
                    if response.status_code == 400:
                        raise SearchError("arXiv rejected this query. Check its syntax or try simple keywords.", 400)
                    if response.status_code != 200:
                        raise SearchError(f"arXiv returned HTTP {response.status_code}. Check server connectivity or try again later.")
                    papers = [paper for paper in parse_feed(response.content) if filters.includes_year(paper.year)][:limit]
                    self._cache[key] = (time.monotonic() + 900, tuple(papers))
                    if len(self._cache) > 128:
                        del self._cache[next(iter(self._cache))]
                    return papers


_client = ArxivSearch()
search_papers = _client.search
