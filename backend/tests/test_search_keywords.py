import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import search_keywords as module
from ai_backend import AIBackendError, AISettings
from search_keywords import SearchKeywords, extract_keywords
from search_filters import SearchFilters


@pytest.mark.parametrize("keywords", [[], ["a"] * 5, ["ti:graphs"], ["graphs OR cats"],
                                      ["中文"], ["a " * 11], ["x" * 81]])
def test_rejects_unbounded_or_query_syntax_output(keywords):
    with pytest.raises(ValidationError):
        SearchKeywords(keywords=keywords)


def test_api_extracts_structured_keywords_with_selected_model(monkeypatch):
    calls = {}

    class Client:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.responses = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def parse(self, **kwargs):
            calls["request"] = kwargs
            return SimpleNamespace(status="completed", output_parsed=SearchKeywords(
                keywords=[" machine learning ", "education", "Education"]))

    monkeypatch.setattr(module, "OpenAI", Client)
    result = extract_keywords("我想研究機器學習與教育", AISettings("openai_api", "openai/chosen", "secret"))
    assert result.keywords == ["machine learning", "education"]
    assert result.query == "machine learning education"
    assert calls["request"]["model"] == "chosen"
    assert calls["request"]["input"][1]["content"] == "我想研究機器學習與教育"
    assert calls["request"]["store"] is False
    assert calls["client"]["api_key"] == "secret"


@pytest.mark.parametrize("backend", ["codex_cli", "claude_cli"])
def test_cli_uses_subscription_and_bounded_extraction_timeout(monkeypatch, backend):
    monkeypatch.setattr("ai_backend.shutil.which", lambda _: "/bin/cli")
    logins = []
    monkeypatch.setattr(module, "require_cli_login", logins.append)

    def run(selected_backend, prompt, **kwargs):
        assert selected_backend == backend
        assert "Research description JSON" in prompt
        assert kwargs["model"] == "chosen"
        assert kwargs["schema"]["additionalProperties"] is False
        assert kwargs["timeout"] == 90
        return json.dumps({"keywords": ["graph learning"]})

    monkeypatch.setattr(module, "run_cli", run)
    assert extract_keywords("圖學習", AISettings(backend, "chosen", "")).query == "graph learning"
    assert logins == [backend]


def test_provider_failure_never_exposes_credentials(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("secret-key and provider output")
    monkeypatch.setattr(module, "OpenAI", fail)
    with pytest.raises(AIBackendError, match="keyword extraction failed") as error:
        extract_keywords("graphs", AISettings("openai_api", "openai/example", "secret-key"))
    assert "secret-key" not in str(error.value)


@pytest.mark.parametrize("status", ["completed", "incomplete"])
def test_refused_or_incomplete_api_output_fails(monkeypatch, status):
    from unittest.mock import MagicMock
    client = MagicMock()
    client.__enter__.return_value = client
    client.responses.parse.return_value = SimpleNamespace(status=status, output_parsed=None)
    monkeypatch.setattr(module, "OpenAI", lambda **kwargs: client)
    with pytest.raises(AIBackendError, match="keyword extraction failed"):
        extract_keywords("graphs", AISettings("openai_api", "openai/example", "secret"))


def test_extracts_typed_subject_years_and_count():
    plan = SearchKeywords.model_validate({"keywords": ["Linux", "networking"], "area": "computer_science",
                                          "years": {"year_from": 2025, "year_to": 2026}, "limit": 8})
    filters, limit = plan.resolve_filters(SearchFilters(), overrides=[])
    assert filters.model_dump() == {"area": "computer_science", "year_from": 2025, "year_to": 2026}
    assert limit == 8 and plan.query == "Linux networking"


@pytest.mark.parametrize("extra", [
    {"area": "invented"}, {"years": {"year_from": 2026, "year_to": 2025}},
    {"years": {"year_from": 1800, "year_to": None}}, {"years": {"year_from": None, "year_to": 9999}},
    {"limit": 11}, {"years": {"year_from": 2025, "year_to": 2026, "sql": "unsafe"}},
])
def test_invalid_inferred_filters_are_rejected(extra):
    with pytest.raises(ValidationError):
        SearchKeywords(keywords=["Linux"], **extra)


def test_manual_filters_win_and_automatic_values_do_not_leak_to_next_search():
    manual = SearchFilters(area="physics", year_from=2020, year_to=None)
    plan = SearchKeywords(keywords=["Linux"], area="computer_science", years={"year_from": 2025, "year_to": 2026}, limit=9)
    filters, limit = plan.resolve_filters(manual, 3, ["area", "years", "limit"])
    assert filters == manual and limit == 3
    filters, limit = SearchKeywords(keywords=["graphs"]).resolve_filters(manual, 9, [])
    assert filters == SearchFilters() and limit == 5
    # Explicitly clearing a control is also a manual override.
    filters, _ = plan.resolve_filters(SearchFilters(), 5, ["area", "years"])
    assert filters == SearchFilters()


def test_prompt_supplies_current_date_and_allowed_areas():
    from datetime import date
    prompt = module.search_instructions()
    assert date.today().isoformat() in prompt
    assert 'Linux networking maps to computer_science' in prompt
    assert 'previous N-1' in prompt and 'version numbers' in prompt
