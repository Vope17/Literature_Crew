"""Independent metadata search when the arXiv API is unavailable."""

import os
import re
import threading
import time
import math
from urllib.parse import quote

import requests

from paper_search import Paper, SearchError, retry_seconds
from search_filters import SearchFilters
from paper_urls import public_url, normalize_doi


def parse_papers(payload: dict, limit: int, filters: SearchFilters | None = None) -> list[Paper]:
    filters = filters or SearchFilters()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SearchError("Semantic Scholar returned an invalid response.")
    papers, seen = [], set()
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        identifiers = item.get("externalIds") or {}
        arxiv_id = identifiers.get("ArXiv", "")
        if not isinstance(arxiv_id, str) or not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?", arxiv_id):
            arxiv_id = ""
        doi = normalize_doi(identifiers.get("DOI"))
        url = (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else
               public_url("https://doi.org/" + quote(doi, safe="/():;")) if doi else public_url(item.get("url")))
        if not url or url in seen or not item.get("title") or not isinstance(item.get("year"), int):
            continue
        if not filters.includes_year(item["year"]):
            continue
        seen.add(url)
        venue = item.get("journal") or {}
        publication = item.get("publicationVenue") or {}
        papers.append(Paper(
            title=item["title"][:2000],
            authors=[author["name"] for author in item.get("authors", []) if author.get("name")][:1000],
            year=item["year"],
            url=url,
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else public_url((item.get("openAccessPdf") or {}).get("url")),
            abstract=(item.get("abstract") or "")[:50_000], doi=doi,
            source="Semantic Scholar", sources=["Semantic Scholar"],
            journal=venue.get("name") or publication.get("name") or item.get("venue") or None,
            issn=[publication["issn"]] if publication.get("issn") else [],
            publication_type=", ".join(item.get("publicationTypes") or []) or None,
        ))
        if len(papers) >= limit:
            break
    return papers


class SemanticScholarSearch:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}
        self._next_request_at = 0.0
        self._blocked_until = 0.0

    def search(self, topic: str, limit: int = 5, *, filters: SearchFilters | None = None) -> list[Paper]:
        topic = " ".join(topic.split())
        if not topic or not 1 <= limit <= 10:
            raise ValueError("Enter a topic and select between 1 and 10 results.")
        filters = filters or SearchFilters()
        key = (topic, limit, *filters.cache_key())
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return list(cached[1])
            if self._blocked_until > time.monotonic():
                raise SearchError(
                    "Semantic Scholar is also rate-limited. Wait, or configure SEMANTIC_SCHOLAR_API_KEY in backend/.env.",
                    429, math.ceil(self._blocked_until - time.monotonic()),
                )
            time.sleep(max(0, self._next_request_at - time.monotonic()))
            headers = {"User-Agent": "LiteratureCrew/0.1"}
            api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
            if api_key:
                headers["x-api-key"] = api_key
            try:
                response = requests.get(
                    "https://api.semanticscholar.org/graph/v1/paper/search/bulk",
                    params={
                        "query": topic,
                        "fields": "title,authors,year,abstract,externalIds,url,openAccessPdf,journal,publicationVenue,publicationTypes,venue",
                        "sort": "citationCount:desc",
                        **filters.semantic_params(),
                    },
                    headers=headers, timeout=(10, 20),
                )
            except requests.RequestException as exc:
                raise SearchError("Cannot reach Semantic Scholar either. Check the backend connection or try later.", 503) from exc
            finally:
                self._next_request_at = time.monotonic() + 3
            with response:
                if response.status_code == 429:
                    seconds = retry_seconds(response.headers.get("Retry-After"), 60)
                    self._blocked_until = time.monotonic() + seconds
                    raise SearchError(
                        "Semantic Scholar is also rate-limited. Wait, or configure SEMANTIC_SCHOLAR_API_KEY in backend/.env.",
                        429, seconds,
                    )
                if response.status_code in (401, 403):
                    raise SearchError("Semantic Scholar rejected access. Check SEMANTIC_SCHOLAR_API_KEY in backend/.env.", 503)
                if response.status_code != 200:
                    raise SearchError(f"Semantic Scholar returned HTTP {response.status_code}. Try simpler keywords or retry later.")
                try:
                    papers = parse_papers(response.json(), limit, filters)
                except (ValueError, TypeError, AttributeError) as exc:
                    raise SearchError("Semantic Scholar returned an invalid response.") from exc
            self._cache[key] = (time.monotonic() + 900, tuple(papers))
            if len(self._cache) > 128:
                del self._cache[next(iter(self._cache))]
            return papers


_client = SemanticScholarSearch()
search_semantic_scholar = _client.search
