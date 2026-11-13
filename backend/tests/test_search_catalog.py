import pytest

from paper_search import Paper, SearchError
from search_catalog import identity_keys, merge_papers, search_catalog
from search_filters import SearchFilters


def paper(title, url, **kwargs):
    return Paper(title=title, authors=[], year=2025, url=url, pdf_url=kwargs.pop("pdf_url", None),
                 abstract=kwargs.pop("abstract", ""), **kwargs)


def test_identity_uses_doi_arxiv_id_and_url():
    keys = identity_keys(paper("A", "https://arxiv.org/abs/2501.00001v2/", doi="https://doi.org/10.1/X",
                               pdf_url="https://arxiv.org/pdf/2501.00001v2"))
    assert ("doi", "10.1/x") in keys and ("arxiv", "2501.00001") in keys
    assert ("url", "https://arxiv.org/abs/2501.00001v2") in keys


def test_same_doi_merges_and_keeps_journal_longest_abstract_and_arxiv_pdf():
    arxiv = paper("Graphs", "https://arxiv.org/abs/2501.00001", doi="10.1/x", abstract="Short",
                  pdf_url="https://arxiv.org/pdf/2501.00001", source="arXiv")
    openalex = paper("Graphs", "https://doi.org/10.1/x", doi="10.1/x", abstract="A much longer abstract",
                     pdf_url="https://publisher.example/a.pdf", journal="Journal of Graphs", issn=["1234-5678"],
                     publication_type="article", source="OpenAlex", sources=["OpenAlex"])
    merged = merge_papers([[arxiv], [openalex]], 5)
    assert len(merged) == 1
    paper_ = merged[0]
    assert paper_.journal == "Journal of Graphs" and paper_.issn == ["1234-5678"]
    assert paper_.abstract == "A much longer abstract" and paper_.pdf_url == "https://arxiv.org/pdf/2501.00001"
    assert paper_.sources == ["arXiv", "OpenAlex"] and paper_.publication_type == "article"
    assert paper_.url == "https://doi.org/10.1/x"


def test_later_record_joins_two_earlier_versions():
    one = paper("A", "https://arxiv.org/abs/2501.00001", source="arXiv")
    two = paper("A", "https://doi.org/10.1/x", doi="10.1/x", source="OpenAlex", sources=["OpenAlex"])
    both = paper("A", "https://example.org/a", doi="10.1/x", pdf_url="https://arxiv.org/pdf/2501.00001",
                 source="Semantic Scholar", sources=["Semantic Scholar"])
    merged = merge_papers([[one], [two], [both]], 5)
    assert len(merged) == 1
    assert merged[0].sources == ["arXiv", "OpenAlex", "Semantic Scholar"]


def test_unidentified_papers_are_never_merged_and_ranks_interleave():
    a1, a2 = paper("A1", "https://a.example/1"), paper("A2", "https://a.example/2")
    b1 = paper("B1", "https://b.example/1")
    assert [p.title for p in merge_papers([[a1, a2], [b1]], 5)] == ["A1", "B1", "A2"]
    assert [p.title for p in merge_papers([[a1, a2], [b1]], 2)] == ["A1", "B1"]


def providers(**behaviour):
    def make(result):
        def search(query, limit, filters=None):
            if isinstance(result, Exception):
                raise result
            return result
        return search
    return {key: make(value) for key, value in behaviour.items()}


def test_partial_failure_returns_results_with_status_and_notice():
    ok = [paper("A", "https://a.example/1", source="arXiv")]
    papers, status, notice = search_catalog("q", 5, SearchFilters(), ["arxiv", "openalex"], providers(
        arxiv=ok, openalex=SearchError("down", 503)))
    assert papers == ok
    assert status == [{"source": "arXiv", "status": "ok", "count": 1},
                      {"source": "OpenAlex", "status": "unavailable", "count": 0}]
    assert "OpenAlex" in notice


def test_unexpected_provider_exception_is_isolated():
    ok = [paper("A", "https://a.example/1")]
    _, status, notice = search_catalog("q", 5, SearchFilters(), ["arxiv", "semantic_scholar"], providers(
        arxiv=ok, semantic_scholar=RuntimeError("secret internal detail")))
    assert status[1]["status"] == "unavailable" and "secret" not in notice


def test_all_sources_failing_raises_with_rate_limit_semantics():
    with pytest.raises(SearchError) as limited:
        search_catalog("q", 5, SearchFilters(), ["arxiv", "openalex"], providers(
            arxiv=SearchError("x", 429, 30), openalex=SearchError("y", 429, 90)))
    assert limited.value.status_code == 429 and limited.value.retry_after == 90
    with pytest.raises(SearchError) as mixed:
        search_catalog("q", 5, SearchFilters(), ["arxiv", "openalex"], providers(
            arxiv=SearchError("x", 429, 30), openalex=SearchError("y", 503)))
    assert mixed.value.status_code == 503


def test_duplicate_source_names_are_queried_once():
    calls = []

    def search(query, limit, filters=None):
        calls.append(query)
        return []

    search_catalog("q", 5, SearchFilters(), ["arxiv", "arxiv"], {"arxiv": search})
    assert calls == ["q"]


def test_openalex_arxiv_doi_merges_with_the_arxiv_record():
    arxiv = paper("A survey", "https://arxiv.org/abs/2303.10993v2", source="arXiv",
                  pdf_url="https://arxiv.org/pdf/2303.10993v2")
    openalex = paper("A survey", "https://doi.org/10.48550/arxiv.2303.10993", doi="10.48550/arXiv.2303.10993",
                     source="OpenAlex", sources=["OpenAlex"], pdf_url="https://arxiv.org/pdf/2303.10993")
    assert ("arxiv", "2303.10993") in identity_keys(openalex)
    merged = merge_papers([[arxiv], [openalex]], 5)
    assert len(merged) == 1 and merged[0].sources == ["arXiv", "OpenAlex"]
