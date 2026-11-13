"""OpenAlex discovery of journal articles, proceedings and other scholarly works."""

import os
import threading
import time
import math
from urllib.parse import quote

import requests

from paper_search import Paper, SearchError, retry_seconds
from paper_urls import public_url, normalize_doi
from search_filters import SearchFilters

FIELDS = {"computer_science": "17", "mathematics": "26", "physics": "31",
          "biology": "11|13|24", "economics": "20", "engineering": "22"}


def openalex_filters(filters):
    clauses = ["is_retracted:false"]
    if filters.area in FIELDS:
        clauses.append(f"primary_topic.field.id:{FIELDS[filters.area]}")
    if filters.year_from:
        clauses.append(f"from_publication_date:{filters.year_from}-01-01")
    if filters.year_to:
        clauses.append(f"to_publication_date:{filters.year_to}-12-31")
    return ",".join(clauses)


def abstract_text(index):
    if not isinstance(index, dict):
        return ""
    words = {}
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if type(position) is int and 0 <= position < 10_000:
                words[position] = word
    return " ".join(words[position] for position in sorted(words))[:50_000]


def parse_papers(payload, limit, filters=None):
    filters = filters or SearchFilters()
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise SearchError("OpenAlex returned an invalid response.")
    papers, seen = [], set()
    for item in payload["results"]:
        if not isinstance(item, dict) or item.get("is_retracted"):
            continue
        title, year = item.get("display_name"), item.get("publication_year")
        if not isinstance(title, str) or not title.strip() or type(year) is not int or not filters.includes_year(year):
            continue
        primary = item.get("primary_location") or {}
        venue = primary.get("source") or {}
        doi = normalize_doi(item.get("doi"))
        url = (public_url("https://doi.org/" + quote(doi, safe="/():;")) if doi else None) or public_url(
            primary.get("landing_page_url")) or public_url(item.get("id"))
        if not url or url in seen:
            continue
        seen.add(url)
        locations = [item.get("best_oa_location") or {}, primary, *(item.get("locations") or [])]
        pdf_url = next((public_url(loc.get("pdf_url")) for loc in locations
                        if isinstance(loc, dict) and loc.get("is_oa") and public_url(loc.get("pdf_url"))), None)
        papers.append(Paper(
            title=title.strip()[:2000], year=year, url=url, pdf_url=pdf_url, doi=doi,
            authors=[entry["author"]["display_name"] for entry in item.get("authorships", [])
                     if isinstance(entry, dict) and isinstance(entry.get("author"), dict)
                     and isinstance(entry["author"].get("display_name"), str)][:1000],
            abstract=abstract_text(item.get("abstract_inverted_index")), source="OpenAlex",
            journal=venue.get("display_name") if venue.get("type") in ("journal", "conference") else None,
            issn=[value for value in venue.get("issn") or [] if isinstance(value, str)],
            publication_type=item.get("type"), sources=["OpenAlex"],
        ))
        if len(papers) >= limit:
            break
    return papers


class OpenAlexSearch:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}
        self._blocked_until = 0.0

    def search(self, topic, limit=5, *, filters=None):
        filters = filters or SearchFilters()
        topic = " ".join(topic.split())
        if not topic or not 1 <= limit <= 10:
            raise ValueError("Enter a topic and select between 1 and 10 results.")
        key = (topic, limit, *filters.cache_key())
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return list(cached[1])
            if self._blocked_until > time.monotonic():
                raise SearchError("OpenAlex is rate-limiting requests. Try later or configure OPENALEX_API_KEY.",
                                  429, math.ceil(self._blocked_until - time.monotonic()))
            headers = {"User-Agent": "LiteratureCrew/0.1"}
            if api_key := os.getenv("OPENALEX_API_KEY", "").strip():
                headers["Authorization"] = f"Bearer {api_key}"
            try:
                response = requests.get("https://api.openalex.org/works", headers=headers,
                    params={"search": topic, "filter": openalex_filters(filters), "per_page": limit,
                            "select": "id,doi,display_name,publication_year,authorships,abstract_inverted_index,primary_location,best_oa_location,locations,type,is_retracted"},
                    timeout=(10, 20))
            except requests.RequestException:
                raise SearchError("Cannot reach OpenAlex. Try again later.", 503) from None
            with response:
                if response.status_code == 429:
                    seconds = retry_seconds(response.headers.get("Retry-After"), 60)
                    self._blocked_until = time.monotonic() + seconds
                    raise SearchError("OpenAlex is rate-limiting requests. Try later or configure OPENALEX_API_KEY.", 429, seconds)
                if response.status_code in (401, 403):
                    raise SearchError("OpenAlex requires a valid API key. Configure OPENALEX_API_KEY.", 503)
                if response.status_code != 200:
                    raise SearchError(f"OpenAlex returned HTTP {response.status_code}. Try again later.")
                try:
                    papers = parse_papers(response.json(), limit, filters)
                except (ValueError, TypeError, AttributeError, KeyError):
                    raise SearchError("OpenAlex returned an invalid response.") from None
            self._cache[key] = (time.monotonic() + 900, tuple(papers))
            if len(self._cache) > 128:
                del self._cache[next(iter(self._cache))]
            return papers


search_openalex = OpenAlexSearch().search
