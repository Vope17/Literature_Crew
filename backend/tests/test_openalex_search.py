from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import openalex_search as search
from search_filters import SearchFilters

WORK = {
    "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1234/ABC", "display_name": "Graph learning",
    "publication_year": 2025, "type": "article", "is_retracted": False,
    "authorships": [{"author": {"display_name": "Ada"}}, {"author": None}, "junk"],
    "abstract_inverted_index": {"Graphs": [0], "learn": [1], "well": [2]},
    "primary_location": {"landing_page_url": "https://journal.example/a", "source": {
        "display_name": "Journal of Graphs", "type": "journal", "issn": ["1234-5678", None]}},
    "best_oa_location": {"is_oa": True, "pdf_url": "https://repo.example/a.pdf"},
    "locations": [],
}
PAYLOAD = {"results": [
    WORK,
    {**WORK, "id": "https://openalex.org/W2", "display_name": "Retracted", "is_retracted": True},
    {**WORK, "id": "https://openalex.org/W3", "doi": None, "display_name": "Old", "publication_year": 1990},
    {**WORK, "id": "https://openalex.org/W4", "doi": None, "display_name": "Closed proceedings",
     "best_oa_location": None, "primary_location": {"landing_page_url": "https://conf.example/p",
        "source": {"display_name": "ConfConf", "type": "conference"}}},
    {**WORK, "id": "https://openalex.org/W5", "doi": None, "display_name": "Repository",
     "primary_location": {"landing_page_url": "http://insecure.example/p", "source": {"type": "repository", "display_name": "Repo"}},
     "best_oa_location": None},
    {"display_name": "", "publication_year": 2025},
    "junk",
]}


@pytest.fixture
def clock(monkeypatch):
    current = [100.0]
    monkeypatch.setattr(search, "time", SimpleNamespace(monotonic=lambda: current[0]))
    return current


def response(status=200, headers=None, payload=PAYLOAD):
    result = MagicMock(status_code=status, headers=headers or {})
    result.json.return_value = payload
    result.__enter__.return_value = result
    return result


def test_abstract_is_rebuilt_in_word_order_and_bounded():
    assert search.abstract_text({"world": [1], "hello": [0, 2]}) == "hello world hello"
    assert search.abstract_text({"x": [10_000, -1, "a"], "bad": "no"}) == ""
    assert search.abstract_text(None) == ""


def test_filter_clauses_cover_area_years_and_retractions():
    assert search.openalex_filters(SearchFilters()) == "is_retracted:false"
    clauses = search.openalex_filters(SearchFilters(area="biology", year_from=2020, year_to=2022)).split(",")
    assert clauses == ["is_retracted:false", "primary_topic.field.id:11|13|24",
                       "from_publication_date:2020-01-01", "to_publication_date:2022-12-31"]


def test_parse_maps_journal_doi_pdf_and_skips_unusable_records():
    papers = search.parse_papers(PAYLOAD, 10, SearchFilters(year_from=2000))
    assert [paper.title for paper in papers] == ["Graph learning", "Closed proceedings", "Repository"]
    first = papers[0]
    assert first.url == "https://doi.org/10.1234/abc" and first.doi == "10.1234/abc"
    assert first.pdf_url == "https://repo.example/a.pdf"
    assert first.journal == "Journal of Graphs" and first.issn == ["1234-5678"]
    assert first.authors == ["Ada"] and first.abstract == "Graphs learn well"
    assert first.source == "OpenAlex" and first.sources == ["OpenAlex"] and first.publication_type == "article"
    assert papers[1].pdf_url is None and papers[1].url == "https://conf.example/p" and papers[1].journal == "ConfConf"
    # An insecure landing page is dropped; the record falls back to its OpenAlex page, and a repository is no journal.
    assert papers[2].url == "https://openalex.org/W5" and papers[2].journal is None
    assert len(search.parse_papers(PAYLOAD, 1, SearchFilters(year_from=2000))) == 1


def test_repository_hosts_are_not_reported_as_journals():
    papers = search.parse_papers({"results": [{**WORK, "doi": None, "primary_location": {
        "landing_page_url": "https://repo.example/p", "source": {"type": "repository", "display_name": "Repo"}}}]}, 5)
    assert papers[0].journal is None


def test_invalid_payload_is_rejected():
    with pytest.raises(search.SearchError):
        search.parse_papers({"results": "nope"}, 5)


def test_search_sends_key_filters_and_caches(monkeypatch, clock):
    monkeypatch.setenv("OPENALEX_API_KEY", "secret")
    get = MagicMock(return_value=response())
    monkeypatch.setattr(search.requests, "get", get)
    client = search.OpenAlexSearch()
    filters = SearchFilters(area="computer_science", year_from=2000)
    assert client.search("  graph   learning ", 5, filters=filters) == client.search("graph learning", 5, filters=filters)
    assert get.call_count == 1
    kwargs = get.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer secret"
    assert kwargs["params"]["search"] == "graph learning" and kwargs["params"]["per_page"] == 5
    assert "primary_topic.field.id:17" in kwargs["params"]["filter"]
    assert kwargs["timeout"] == (10, 20)
    client.search("graph learning", 5)
    assert get.call_count == 2


def test_search_validates_input():
    client = search.OpenAlexSearch()
    for topic, limit in (("", 5), ("graphs", 0), ("graphs", 11)):
        with pytest.raises(ValueError):
            client.search(topic, limit)


def test_rate_limit_blocks_until_retry_after(monkeypatch, clock):
    get = MagicMock(side_effect=[response(429, {"Retry-After": "90"}), response()])
    monkeypatch.setattr(search.requests, "get", get)
    client = search.OpenAlexSearch()
    with pytest.raises(search.SearchError) as caught:
        client.search("graphs")
    assert caught.value.status_code == 429 and caught.value.retry_after == 90
    with pytest.raises(search.SearchError) as blocked:
        client.search("other topic")
    assert blocked.value.status_code == 429 and get.call_count == 1
    clock[0] += 90
    assert client.search("graphs")
    assert get.call_count == 2


@pytest.mark.parametrize("status, expected", [(401, 503), (403, 503), (500, 502)])
def test_error_statuses_map_to_search_errors(monkeypatch, clock, status, expected):
    monkeypatch.setattr(search.requests, "get", MagicMock(return_value=response(status)))
    with pytest.raises(search.SearchError) as caught:
        search.OpenAlexSearch().search("graphs")
    assert caught.value.status_code == expected


def test_network_failure_and_bad_json_are_reported(monkeypatch, clock):
    monkeypatch.setattr(search.requests, "get", MagicMock(side_effect=search.requests.ConnectionError()))
    with pytest.raises(search.SearchError) as caught:
        search.OpenAlexSearch().search("graphs")
    assert caught.value.status_code == 503
    broken = response()
    broken.json.side_effect = ValueError
    monkeypatch.setattr(search.requests, "get", MagicMock(return_value=broken))
    with pytest.raises(search.SearchError, match="invalid response"):
        search.OpenAlexSearch().search("graphs")
