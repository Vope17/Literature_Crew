from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import semantic_search as search
from search_filters import SearchFilters

PAYLOAD = {"data": [
    {"title": "Without arXiv link", "year": 2025, "externalIds": {"DOI": "10.1/example"}},
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


def test_fallback_converts_only_arxiv_linked_papers():
    papers = search.parse_papers(PAYLOAD, 5)
    assert len(papers) == 2
    assert papers[0].title == "Graphs"
    assert papers[0].authors == ["Ada"]
    assert papers[0].pdf_url == "https://arxiv.org/pdf/2501.00001"
    assert papers[0].doi == "10.2/example"
    assert "not provided" in papers[1].abstract
    assert len(search.parse_papers(PAYLOAD, 1)) == 1


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
    assert [paper.year for paper in papers] == [2025]
    params = get.call_args.kwargs["params"]
    assert params["fieldsOfStudy"] == "Computer Science"
    assert params["year"] == "2025-2025"
    client.search("graphs", filters=filters)
    assert get.call_count == 1
    assert len(client.search("graphs")) == 2
    assert get.call_count == 2
