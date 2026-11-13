"""Search independent catalogs concurrently and merge identities without ranking unlike scores."""

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import zip_longest

from paper_search import SearchError
from paper_urls import normalize_doi

SOURCE_LABELS = {"openalex": "OpenAlex", "semantic_scholar": "Semantic Scholar", "arxiv": "arXiv"}


def identity_keys(paper):
    keys = {("url", paper.url.rstrip("/"))}
    if doi := normalize_doi(paper.doi):
        keys.add(("doi", doi))
    for url in (paper.url, paper.pdf_url or ""):
        match = re.search(r"^https://arxiv\.org/(?:abs|pdf)/(.+?)(?:v\d+)?(?:\.pdf)?$", url)
        if match:
            keys.add(("arxiv", match[1]))
    return keys


def merge_papers(groups, limit):
    merged, identities = [], []
    # Interleave provider ranks; scores/citation counts from different catalogs are not comparable.
    for row in zip_longest(*groups):
        for paper in row:
            if paper is None:
                continue
            keys = identity_keys(paper)
            matches = [i for i, known in enumerate(identities) if known & keys]
            if not matches:
                merged.append(paper)
                identities.append(keys)
                continue
            index = matches[0]
            # A later DOI+arXiv record can join two previously separate versions.
            for i in reversed(matches):
                old = merged[i]
                keys |= identities[i]
                primary = paper if paper.journal and not old.journal else old
                pdf = next((url for url in (old.pdf_url, paper.pdf_url) if url and url.startswith("https://arxiv.org/pdf/")), None)
                paper = replace(primary, doi=old.doi or paper.doi, pdf_url=pdf or old.pdf_url or paper.pdf_url,
                    abstract=max((old.abstract, paper.abstract), key=len),
                    journal=old.journal or paper.journal, issn=list(dict.fromkeys(old.issn + paper.issn)),
                    publication_type=primary.publication_type or paper.publication_type or old.publication_type,
                    sources=list(dict.fromkeys((old.sources or [old.source]) + (paper.sources or [paper.source]))))
                if i != index:
                    del merged[i]
                    del identities[i]
            merged[index], identities[index] = paper, keys
    return merged[:limit]


def search_catalog(query, limit, filters, sources, providers):
    sources = list(dict.fromkeys(sources))
    groups, status, errors = [], [], []
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = {key: executor.submit(providers[key], query, limit, filters=filters) for key in sources}
        for key, future in futures.items():
            try:
                papers = future.result()
                groups.append(papers)
                status.append({"source": SOURCE_LABELS[key], "status": "ok", "count": len(papers)})
            except Exception as exc:
                error = exc if isinstance(exc, SearchError) else SearchError("Search source is unavailable.", 503)
                errors.append(error)
                status.append({"source": SOURCE_LABELS[key], "status": "unavailable", "count": 0})
    if not groups:
        rate_limited = all(error.status_code == 429 for error in errors)
        raise SearchError("All selected search sources are unavailable. Try again later or check source API keys.",
                          429 if rate_limited else 503, max((error.retry_after for error in errors), default=0))
    unavailable = [item["source"] for item in status if item["status"] != "ok"]
    notice = "Some sources are unavailable: " + ", ".join(unavailable) + ". Results may be incomplete." if unavailable else None
    return merge_papers(groups, limit), status, notice
