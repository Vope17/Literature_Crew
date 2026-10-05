from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

import paper_search as search
from search_filters import SearchFilters

FEED = b'''<feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
 xmlns:arxiv="http://arxiv.org/schemas/atom">
 <opensearch:totalResults>1</opensearch:totalResults>
 <entry><id>http://arxiv.org/abs/2501.00001v2</id><title>Graph\n analysis</title>
 <published>2025-01-01T00:00:00Z</published><author><name>Ada</name></author>
 <summary>An abstract</summary><arxiv:doi>10.1234/example</arxiv:doi></entry></feed>'''


def response(status=200, content=FEED, headers=None):
    result = MagicMock(status_code=status, content=content, headers=headers or {})
    result.__enter__.return_value = result
    return result


@pytest.fixture
def clock(monkeypatch):
    current = [100.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        current[0] += seconds

    monkeypatch.setattr(search, "time", SimpleNamespace(
        monotonic=lambda: current[0], time=lambda: 0, sleep=sleep,
    ))
    return current, sleeps


def test_real_atom_schema_metadata_query_and_cache(monkeypatch, clock):
    get = MagicMock(return_value=response())
    monkeypatch.setattr(search.requests, "get", get)
    client = search.ArxivSearch()
    papers = client.search("graph neural", 1)
    assert papers[0].title == "Graph analysis"
    assert papers[0].authors == ["Ada"]
    assert papers[0].year == 2025
    assert papers[0].doi == "10.1234/example"
    assert papers[0].pdf_url == "https://arxiv.org/pdf/2501.00001v2"
    assert get.call_args.kwargs["params"]["search_query"] == "all:graph AND all:neural"
    assert get.call_args.kwargs["params"]["max_results"] == 1
    assert get.call_args.kwargs["timeout"] == (10, 20)
    assert client.search("graph   neural", 1) == papers
    assert get.call_count == 1
    clock[0][0] += 901
    client.search("graph neural", 1)
    assert get.call_count == 2


def test_rate_limit_honors_retry_after_without_hammering(monkeypatch, clock):
    get = MagicMock(side_effect=[response(429, headers={"Retry-After": "120"}), response()])
    monkeypatch.setattr(search.requests, "get", get)
    client = search.ArxivSearch()
    with pytest.raises(search.SearchError) as caught:
        client.search("graphs")
    assert caught.value.status_code == 429 and caught.value.retry_after == 120
    clock[0][0] += 10
    with pytest.raises(search.SearchError) as caught:
        client.search("different query")
    assert caught.value.retry_after == 110
    assert get.call_count == 1
    clock[0][0] += 110
    assert client.search("graphs")
    assert get.call_count == 2


def test_cached_results_remain_available_during_rate_limit(monkeypatch, clock):
    get = MagicMock(side_effect=[response(), response(429)])
    monkeypatch.setattr(search.requests, "get", get)
    client = search.ArxivSearch()
    original = client.search("graphs")
    with pytest.raises(search.SearchError):
        client.search("another query")
    assert client.search("graphs") == original
    assert get.call_count == 2


def test_transient_failure_retries_and_requests_are_paced(monkeypatch, clock):
    get = MagicMock(side_effect=[response(503), response(), response()])
    monkeypatch.setattr(search.requests, "get", get)
    client = search.ArxivSearch()
    assert client.search("graphs")
    assert client.search("networks")
    assert clock[1] == [0, 3, 3]


def test_long_retry_after_does_not_block_worker(monkeypatch, clock):
    get = MagicMock(return_value=response(503, headers={"Retry-After": "300"}))
    monkeypatch.setattr(search.requests, "get", get)
    client = search.ArxivSearch()
    for _ in range(2):
        with pytest.raises(search.SearchError) as caught:
            client.search("graphs")
        assert caught.value.status_code == 503
        assert caught.value.retry_after == 300
    assert get.call_count == 1
    assert clock[1] == [0]


@pytest.mark.parametrize("exception, status", [(requests.Timeout(), 504), (requests.ConnectionError(), 503)])
def test_network_errors_are_bounded(monkeypatch, clock, exception, status):
    get = MagicMock(side_effect=exception)
    monkeypatch.setattr(search.requests, "get", get)
    with pytest.raises(search.SearchError) as caught:
        search.ArxivSearch().search("graphs")
    assert caught.value.status_code == status
    assert get.call_count == 3


def test_invalid_feed_is_not_reported_as_empty_results():
    with pytest.raises(search.SearchError, match="invalid response"):
        search.parse_feed(b"<html>Bad gateway</html>")
    empty = FEED[:FEED.index(b" <entry>")].replace(b">1<", b">0<") + b"</feed>"
    assert search.parse_feed(empty) == []


def test_advanced_queries_and_retry_dates(clock):
    assert search.search_query('ti:"graph networks" AND cat:cs.LG') == 'ti:"graph networks" AND cat:cs.LG'
    assert search.search_query('"graph networks"') == 'all:"graph networks"'
    assert search.retry_seconds("Thu, 01 Jan 1970 00:02:00 GMT", 60) == 120
    assert search.retry_seconds(None, 60) == 60


def test_arxiv_filters_change_query_and_cache(monkeypatch, clock):
    get = MagicMock(return_value=response())
    monkeypatch.setattr(search.requests, "get", get)
    client = search.ArxivSearch()
    filters = SearchFilters(area="computer_science", year_from=2020, year_to=2025)
    assert client.search("graphs", filters=filters)
    query = get.call_args.kwargs["params"]["search_query"]
    assert "cat:cs.*" in query
    assert "submittedDate:[202001010000 TO 202512312359]" in query
    client.search("graphs", filters=filters)
    assert get.call_count == 1
    assert not client.search("graphs", filters=SearchFilters(year_to=2020))
    assert get.call_count == 2


def test_filters_preserve_advanced_query_grouping_and_open_year_bounds():
    filters = SearchFilters(area="mathematics", year_from=2020)
    assert filters.arxiv_query("ti:graphs OR ti:networks").startswith("(ti:graphs OR ti:networks) AND (cat:math.*)")
    assert filters.semantic_params() == {"fieldsOfStudy": "Mathematics", "year": "2020-"}
    assert SearchFilters(year_to=2025).semantic_params() == {"year": "-2025"}
