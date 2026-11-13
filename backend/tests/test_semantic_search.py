from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import semantic_search as search
from search_filters import SearchFilters

PAYLOAD = {"data": [
    {"title": "Without arXiv link", "year": 2025, "externalIds": {"DOI": "10.1/Example"},
     "openAccessPdf": {"url": "https://publisher.example/open.pdf"},
     "journal": {"name": "Journal of Graphs"}, "publicationTypes": ["JournalArticle"]},
    {"title": "Graphs", "year": 2025, "abstract": "Evidence", "authors": [{"name": "Ada"}],
     "externalIds": {"ArXiv": "2501.00001", "DOI": "10.2/example"}},
    {"title": "No abstract", "year": 2024, "abstract": None,
     "externalIds": {"ArXiv": "2401.00001"}},
]}


@pytest.fixture
def clock(monkeypatch):
    current = [100.0]

    def sleep(seconds):
        current[0] += seconds

    monkeypatch.setattr(search, "time", SimpleNamespace(monotonic=lambda: current[0], sleep=sleep))
    return current


def response(status=200, headers=None):
    result = MagicMock(status_code=status, headers=headers or {})
    result.json.return_value = PAYLOAD
    result.__enter__.return_value = result
    return result


def test_papers_without_arxiv_id_are_kept_with_doi_and_open_pdf():
    papers = search.parse_papers(PAYLOAD, 5)
    assert [paper.title for paper in papers] == ["Without arXiv link", "Graphs", "No abstract"]
    journal = papers[0]
    assert journal.url == "https://doi.org/10.1/example" and journal.doi == "10.1/example"
    assert journal.pdf_url == "https://publisher.example/open.pdf"
    assert journal.journal == "Journal of Graphs" and journal.publication_type == "JournalArticle"
    assert journal.source == "Semantic Scholar" and journal.sources == ["Semantic Scholar"]
    assert papers[1].authors == ["Ada"]
    assert papers[1].url == "https://arxiv.org/abs/2501.00001"
    assert papers[1].pdf_url == "https://arxiv.org/pdf/2501.00001"
    assert papers[1].doi == "10.2/example"
    assert papers[2].abstract == ""
    assert len(search.parse_papers(PAYLOAD, 1)) == 1


def test_untrusted_links_and_ids_are_dropped():
    payload = {"data": [
        {"title": "Private host", "year": 2025, "url": "https://127.0.0.1/paper"},
        {"title": "Not HTTPS", "year": 2025, "url": "http://example.org/paper"},
        {"title": "Bad pdf", "year": 2025, "externalIds": {"DOI": "10.3/x"},
         "openAccessPdf": {"url": "http://example.org/a.pdf"}},
        "not a record",
    ]}
    papers = search.parse_papers(payload, 5)
    assert [paper.title for paper in papers] == ["Bad pdf"]
    assert papers[0].pdf_url is None


def test_fallback_rejects_malformed_response():
    with pytest.raises(search.SearchError):
        search.parse_papers({"error": "provider error"}, 5)


def test_fallback_uses_optional_key_and_cache(monkeypatch, clock):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "test-secret")
    get = MagicMock(return_value=response())
    monkeypatch.setattr(search.requests, "get", get)
    client = search.SemanticScholarSearch()
    assert client.search("graphs") == client.search("graphs")
    assert get.call_count == 1
    assert get.call_args.args[0].endswith("/paper/search/bulk")
    assert get.call_args.kwargs["headers"]["x-api-key"] == "test-secret"
    assert get.call_args.kwargs["timeout"] == (10, 20)


def test_fallback_respects_its_own_rate_limit(monkeypatch, clock):
    get = MagicMock(side_effect=[response(429, {"Retry-After": "90"}), response()])
    monkeypatch.setattr(search.requests, "get", get)
    client = search.SemanticScholarSearch()
    with pytest.raises(search.SearchError) as caught:
        client.search("graphs")
    assert caught.value.status_code == 429 and caught.value.retry_after == 90
    with pytest.raises(search.SearchError):
        client.search("different query")
    assert get.call_count == 1
    clock[0] += 90
    assert client.search("graphs")
    assert get.call_count == 2


def test_fallback_filters_change_request_and_cache(monkeypatch, clock):
    get = MagicMock(return_value=response())
    monkeypatch.setattr(search.requests, "get", get)
    client = search.SemanticScholarSearch()
    filters = SearchFilters(area="computer_science", year_from=2025, year_to=2025)
    papers = client.search("graphs", filters=filters)
    assert [paper.year for paper in papers] == [2025, 2025]
    params = get.call_args.kwargs["params"]
    assert params["fieldsOfStudy"] == "Computer Science"
    assert params["year"] == "2025-2025"
    client.search("graphs", filters=filters)
    assert get.call_count == 1
    assert len(client.search("graphs")) == 3
    assert get.call_count == 2
