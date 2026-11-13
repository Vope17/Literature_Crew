from dataclasses import asdict
from threading import Event
import time

import pytest
from fastapi.testclient import TestClient

import app
from literature import Paper
from paper_search import SearchError
from search_keywords import SearchKeywords

@pytest.fixture(autouse=True)
def isolated_history(monkeypatch, tmp_path):
    global client
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "history.sqlite3"))
    monkeypatch.setenv("MODEL", "openai/example")
    monkeypatch.setenv("AI_BACKEND", "openai_api")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(app, "extract_keywords", lambda topic, settings: SearchKeywords(keywords=["graphs"]))
    with TestClient(app.app) as client:
        yield


def wait_for_review(record_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/api/reviews/{record_id}")
        assert response.status_code == 200
        if response.json()["status"] in ("completed", "failed"):
            return response.json()
        time.sleep(0.01)
    pytest.fail("Review job did not finish")


@pytest.fixture
def paper():
    return Paper("Graph paper", ["Ada"], 2025,
                 "https://arxiv.org/abs/2501.00001",
                 "https://arxiv.org/pdf/2501.00001", "Abstract")


def test_search_and_review(monkeypatch, paper):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(app, "search_papers", lambda topic, limit, **kwargs: [paper])
    response = client.post("/api/search", json={"topic": "graphs", "limit": 1})
    assert response.status_code == 200
    assert response.json()["papers"] == [asdict(paper)]

    def generate(topic, papers, key, model, **kwargs):
        assert topic == "graphs" and papers == [paper]
        assert key == "test-key"
        return "# Review", [{"id": "P1", "coverage": "abstract only"}]

    monkeypatch.setattr(app, "generate_review", generate)
    response = client.post("/api/review", json={
        "topic": "graphs", "papers": response.json()["papers"],
    })
    assert response.status_code == 202
    saved = wait_for_review(response.json()["id"])
    assert saved["review"] == "# Review"
    assert saved["evidence"][0]["coverage"] == "abstract only"
    assert len(client.get("/api/history").json()["items"]) == 2


def test_config_hides_key_and_review_uses_environment(monkeypatch, paper):
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret")
    monkeypatch.setenv("MODEL", "openai/example")
    response = client.get("/api/config")
    assert response.json()["has_api_key"] is True
    assert "server-secret" not in response.text

    def generate(topic, papers, key, model, **kwargs):
        assert key == "server-secret" and model == "openai/example"
        return "Report", []

    monkeypatch.setattr(app, "generate_review", generate)
    response = client.post("/api/review", json={"topic": "graphs", "papers": [asdict(paper)]})
    assert response.status_code == 202
    assert wait_for_review(response.json()["id"])["status"] == "completed"


def test_missing_key(monkeypatch, paper):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post("/api/review", json={"topic": "graphs", "papers": [asdict(paper)]})
    assert response.status_code == 400


def test_search_requires_ai_connection(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(app, "search_papers", lambda *a, **kw: pytest.fail("No search before AI setup"))
    assert client.post("/api/search", json={"topic": "graphs"}).status_code == 400


def test_long_description_preserved_with_keywords_and_browser_model(monkeypatch, paper):
    monkeypatch.setattr(app, "list_models", lambda key: [{"id": "openai/chosen", "name": "chosen"}])
    connection = client.post("/api/ai/connection", json={"backend": "openai_api", "api_key": "browser-key"},
                             headers={"origin": "http://testserver"}).json()
    topic = "我想研究機器學習在教育中的應用。" * 100

    def extract(description, settings):
        assert description == topic
        assert settings.api_key == "browser-key" and settings.model == "openai/chosen"
        return SearchKeywords(keywords=["machine learning", "education"])

    def search(query, limit, **kwargs):
        assert query == "machine learning education"
        return [paper]

    monkeypatch.setattr(app, "extract_keywords", extract)
    monkeypatch.setattr(app, "search_papers", search)
    response = client.post("/api/search", json={"topic": topic, "model": "openai/chosen",
                                               "connection_id": connection["connection_id"]})
    assert response.status_code == 200
    saved = client.get('/api/history/' + response.json()["history_id"]).json()
    assert saved["topic"] == topic
    assert saved["keywords"] == ["machine learning", "education"]
    assert saved["model"] == "openai/chosen"
    assert "browser-key" not in str(saved)
    monkeypatch.setattr(app, "generate_review", lambda *a, **kw: ("Review", []))
    review = client.post("/api/review", json={"topic": topic, "papers": [asdict(paper)]})
    assert review.status_code == 202
    assert wait_for_review(review.json()["id"])["topic"] == topic


def test_search_rejects_expired_connection_and_invalid_model_before_ai(monkeypatch):
    monkeypatch.setattr(app, "extract_keywords", lambda *a: pytest.fail("Must reject before AI usage"))
    assert client.post("/api/search", json={"topic": "graphs", "connection_id": "expired"}).status_code == 409
    monkeypatch.setattr(app, "list_models", lambda key: [{"id": "openai/allowed"}])
    assert client.post("/api/search", json={"topic": "graphs", "model": "openai/unknown"}).status_code == 400
    assert client.post("/api/search", json={"topic": "a" * 10001}).status_code == 422


def test_keyword_failure_stops_before_paper_search(monkeypatch):
    def fail(*args):
        raise app.AIBackendError("AI keyword extraction failed.")
    monkeypatch.setattr(app, "extract_keywords", fail)
    monkeypatch.setattr(app, "search_papers", lambda *a, **kw: pytest.fail("Do not search raw text"))
    assert client.post("/api/search", json={"topic": "研究描述"}).status_code == 503


def test_natural_language_filters_apply_to_fallback_response_and_history(monkeypatch, paper):
    monkeypatch.setattr(app, "extract_keywords", lambda *args: SearchKeywords(
        keywords=["Linux", "networking"], area="computer_science", years={"year_from": 2025, "year_to": 2026}, limit=7))
    calls = []
    def primary(query, limit, *, filters):
        calls.append((query, limit, filters.model_dump()))
        raise SearchError("Unavailable", 503)
    def fallback(query, limit, *, filters):
        calls.append((query, limit, filters.model_dump()))
        return [paper]
    monkeypatch.setattr(app, "search_papers", primary)
    monkeypatch.setattr(app, "search_semantic_scholar", fallback)
    topic = "我想找linux網路相關的推薦一下，2025-2026的，給我7篇"
    response = client.post('/api/search', json={"topic": topic, "filter_overrides": []})
    assert response.status_code == 200
    expected = {"area": "computer_science", "year_from": 2025, "year_to": 2026}
    assert calls == [("Linux networking", 7, expected)] * 2
    assert response.json()["filters"] == {**expected, "limit": 7}
    saved = client.get('/api/history/' + response.json()["history_id"]).json()
    assert saved["filters"] == response.json()["filters"] and saved["topic"] == topic


def test_search_respects_explicit_manual_override_of_inferred_dates(monkeypatch):
    monkeypatch.setattr(app, "extract_keywords", lambda *args: SearchKeywords(
        keywords=["Linux"], area="computer_science", years={"year_from": 2025, "year_to": 2026}))
    monkeypatch.setattr(app, "search_papers", lambda *a, **kw: [])
    response = client.post('/api/search', json={"topic": "Linux 2025-2026", "year_from": 2020,
        "year_to": 2022, "filter_overrides": ["years"]})
    assert response.json()["filters"] == {"area": "computer_science", "year_from": 2020, "year_to": 2022, "limit": 5}


@pytest.mark.parametrize("payload", [{"topic": " "}, {"topic": "graphs", "limit": 11}])
def test_invalid_search(payload):
    assert client.post("/api/search", json=payload).status_code == 422


def test_rejects_arbitrary_pdf_urls_and_hides_input(paper):
    data = asdict(paper)
    data["pdf_url"] = "http://127.0.0.1/private"
    response = client.post("/api/review", json={"topic": "graphs", "papers": [data], "api_key": "secret"})
    assert response.status_code == 422
    assert "secret" not in response.text


def test_rejects_too_many_papers(paper):
    response = client.post("/api/review", json={"topic": "graphs", "papers": [asdict(paper)] * 6})
    assert response.status_code == 422


def test_provider_errors_do_not_expose_secrets(monkeypatch, paper):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    def fail(*args, **kwargs):
        raise RuntimeError("provider failed for secret-key")

    monkeypatch.setattr(app, "generate_review", fail)
    response = client.post("/api/review", json={"topic": "graphs", "papers": [asdict(paper)]})
    assert response.status_code == 202
    saved = wait_for_review(response.json()["id"])
    assert saved["status"] == "failed"
    assert "secret-key" not in str(saved)
    assert "secret-key" not in client.get("/api/history").text


def test_search_rate_limit_status_and_retry_header(monkeypatch):
    def fail(*args, **kwargs):
        raise SearchError("arXiv is rate-limiting requests.", 429, 60)

    monkeypatch.setattr(app, "search_papers", fail)
    monkeypatch.setattr(app, "search_semantic_scholar", fail)
    response = client.post("/api/search", json={"topic": "graphs"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert "rate-limiting" in response.json()["detail"]


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_search_uses_fallback_when_arxiv_is_unavailable(monkeypatch, paper, status):
    def primary(*args, **kwargs):
        raise SearchError("arXiv unavailable", status, 60)

    monkeypatch.setattr(app, "search_papers", primary)
    monkeypatch.setattr(app, "search_semantic_scholar", lambda topic, limit, **kwargs: [paper])
    response = client.post("/api/search", json={"topic": "graph networks"})
    assert response.status_code == 200
    assert response.json()["source"] == "Semantic Scholar"
    assert response.json()["papers"] == [asdict(paper)]
    assert "citation count" in response.json()["notice"]
    app.PaperInput.model_validate(response.json()["papers"][0])


def test_bad_query_does_not_call_fallback(monkeypatch):
    def primary(*args, **kwargs):
        raise SearchError("Invalid query", 400)

    def fallback(*args, **kwargs):
        pytest.fail("Fallback must not run for invalid queries")

    monkeypatch.setattr(app, "search_papers", primary)
    monkeypatch.setattr(app, "search_semantic_scholar", fallback)
    assert client.post("/api/search", json={"topic": "bad query"}).status_code == 400


def test_ai_keywords_are_used_by_both_search_providers(monkeypatch):
    def primary(*args, **kwargs):
        assert args[0] == "graphs"
        raise SearchError("arXiv unavailable", 429, 60)

    def fallback(*args, **kwargs):
        assert args[0] == "graphs"
        return []

    monkeypatch.setattr(app, "search_papers", primary)
    monkeypatch.setattr(app, "search_semantic_scholar", fallback)
    response = client.post("/api/search", json={"topic": "請幫我找圖論的相關文獻"})
    assert response.status_code == 200
    assert response.json()["keywords"] == ["graphs"]


def test_models_uses_server_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "server-key")
    keys = []

    def models(key):
        keys.append(key)
        return [{"id": "openai/test", "name": "test"}]

    monkeypatch.setattr(app, "list_models", models)
    response = client.get("/api/models")
    assert response.status_code == 200
    assert "server-key" not in response.text
    assert keys == ["server-key"]


def test_models_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert client.get("/api/models").status_code == 400


def test_models_auth_error_is_safe(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    import httpx
    from openai import AuthenticationError

    def fail(key):
        raise AuthenticationError("Bad key secret-key", response=httpx.Response(
            401, request=httpx.Request("GET", "https://api.openai.com/v1/models")), body=None)

    monkeypatch.setattr(app, "list_models", fail)
    response = client.get("/api/models")
    assert response.status_code == 401
    assert "secret-key" not in response.text


@pytest.mark.parametrize("override", [{"api_key": "browser-secret"}])
def test_browser_cannot_override_server_credentials(monkeypatch, paper, override):
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret")
    response = client.post("/api/review", json={"topic": "graphs", "papers": [asdict(paper)], **override})
    assert response.status_code == 422
    assert "browser-secret" not in response.text


def test_review_requires_configured_model(monkeypatch, paper):
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret")
    monkeypatch.setenv("MODEL", " ")
    response = client.post("/api/review", json={"topic": "graphs", "papers": [asdict(paper)]})
    assert response.status_code == 400
    assert "MODEL" in response.json()["detail"]


def test_search_forwards_filters_to_primary_and_fallback(monkeypatch, paper):
    received = []

    def primary(topic, limit, *, filters):
        received.append(filters.model_dump())
        raise SearchError("Rate limited", 429, 60)

    def fallback(topic, limit, *, filters):
        received.append(filters.model_dump())
        return [paper]

    monkeypatch.setattr(app, "search_papers", primary)
    monkeypatch.setattr(app, "search_semantic_scholar", fallback)
    filters = {"area": "computer_science", "year_from": 2020, "year_to": 2025}
    response = client.post("/api/search", json={"topic": "graphs", **filters})
    assert response.status_code == 200
    assert received == [filters, filters]


@pytest.mark.parametrize("filters", [
    {"area": "unknown"}, {"year_from": 2025, "year_to": 2020},
    {"year_from": 1800}, {"year_to": 9999},
])
def test_search_rejects_invalid_filters(filters):
    assert client.post("/api/search", json={"topic": "graphs", **filters}).status_code == 422


def test_background_review_returns_before_generation_and_reports_progress(monkeypatch, paper):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    entered, release = Event(), Event()

    def generate(topic, papers, key, model, *, progress, pdf_store, **kwargs):
        progress("Reading paper 1/1")
        entered.set()
        assert release.wait(5)
        return "# Async review", []

    monkeypatch.setattr(app, "generate_review", generate)
    try:
        response = client.post("/api/review", json={"topic": "graphs", "papers": [asdict(paper)]})
        assert response.status_code == 202
        assert entered.wait(1)
        record_id = response.json()["id"]
        job = client.get(f"/api/reviews/{record_id}").json()
        assert job["status"] == "running" and job["progress"] == "Reading paper 1/1"
        assert client.get("/api/config").status_code == 200
        assert client.get("/api/history").json()["items"][0]["id"] == record_id
    finally:
        release.set()
    assert wait_for_review(record_id)["review"] == "# Async review"


def test_search_history_can_be_reopened_without_a_provider(monkeypatch, paper):
    monkeypatch.setattr(app, "search_papers", lambda *args, **kwargs: [paper])
    response = client.post("/api/search", json={"topic": "graphs", "area": "computer_science"})
    record_id = response.json()["history_id"]
    monkeypatch.setattr(app, "search_papers", lambda *args, **kwargs: pytest.fail("Must use saved results"))
    saved = client.get(f"/api/history/{record_id}").json()
    assert saved["papers"] == [asdict(paper)]
    assert saved["filters"]["area"] == "computer_science"
    assert client.get(f"/api/reviews/{record_id}").status_code == 404


def test_saved_pdf_download_and_missing_records():
    pdf_id = app.app.state.store.save_pdf("https://arxiv.org/pdf/example", b"%PDF-test")
    response = client.get(f"/api/pdfs/{pdf_id}")
    assert response.content == b"%PDF-test"
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    for path in ("history/missing", "reviews/missing", "pdfs/missing"):
        assert client.get(f"/api/{path}").status_code == 404


@pytest.mark.parametrize("backend", ["codex_cli", "claude_cli"])
def test_cli_review_without_api_key_saves_study_options(monkeypatch, paper, backend):
    import ai_backend

    monkeypatch.setenv("AI_BACKEND", backend)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CLI_MODEL", raising=False)
    monkeypatch.setattr(ai_backend.shutil, "which", lambda _: "/usr/bin/cli")

    def generate(topic, papers, key, model, **kwargs):
        assert key == model == ""
        assert kwargs["backend"] == backend
        assert kwargs["options"].mode == "introduction"
        assert kwargs["options"].units == "chip layouts"
        return "# Introduction\n[待補：研究問題] [P1]", [{"id": "P1", "text": "Abstract", "coverage": "abstract only"}]

    monkeypatch.setattr(app, "generate_review", generate)
    config = client.get("/api/config").json()
    assert config["ready"] is True and config["has_api_key"] is False
    response = client.post("/api/review", json={
        "topic": "graphs", "papers": [asdict(paper)],
        "options": {"mode": "introduction", "units": "chip layouts"},
    })
    assert response.status_code == 202
    saved = wait_for_review(response.json()["id"])
    assert saved["status"] == "completed"
    assert saved["ai_backend"] == backend
    assert saved["options"]["units"] == "chip layouts"
    assert saved["checks"][2]["status"] == "warning"
    assert client.get(f"/api/history/{saved['id']}").json()["options"] == saved["options"]


def test_browser_cannot_override_backend_inside_options(paper):
    response = client.post("/api/review", json={
        "topic": "graphs", "papers": [asdict(paper)], "options": {"ai_backend": "codex_cli"},
    })
    assert response.status_code == 422


def test_chatgpt_signin_routes_require_same_origin_and_hide_credentials(monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setenv("AI_BACKEND", "codex_cli")
    manager = app.app.state.chatgpt_login
    monkeypatch.setattr(manager, "status", AsyncMock(return_value={"status": "disconnected", "connected": False}))
    monkeypatch.setattr(manager, "start", AsyncMock(return_value={
        "status": "pending", "connected": False, "verification_url": "https://auth.openai.com/codex/device", "user_code": "ABCD-1234",
    }))
    monkeypatch.setattr(manager, "cancel", AsyncMock(return_value={"status": "disconnected", "connected": False}))
    assert client.get("/api/auth/chatgpt").headers["cache-control"] == "no-store"
    for origin in (None, "https://evil.example"):
        headers = {"Origin": origin} if origin else {}
        assert client.post("/api/auth/chatgpt/start", json={}, headers=headers).status_code == 403
    assert not manager.start.called
    headers = {"Origin": "http://testserver"}
    started = client.post("/api/auth/chatgpt/start", json={}, headers=headers)
    assert started.status_code == 200 and started.json()["user_code"] == "ABCD-1234"
    assert "token" not in started.text.lower()
    assert client.post("/api/auth/chatgpt/cancel", json={}, headers=headers).json()["status"] == "disconnected"
    monkeypatch.setenv("AI_BACKEND", "openai_api")
    assert client.get("/api/auth/chatgpt").status_code == 409


def test_selected_api_model_is_validated_used_and_saved(monkeypatch, paper):
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret")
    monkeypatch.setenv("MODEL", "")
    monkeypatch.setattr(app, "list_models", lambda key: [{"id": "openai/chosen", "name": "Chosen"}])

    def generate(topic, papers, key, model, **kwargs):
        assert key == "server-secret" and model == "openai/chosen"
        return "Report", []

    monkeypatch.setattr(app, "generate_review", generate)
    body = {"topic": "graphs", "papers": [asdict(paper)], "model": "openai/chosen"}
    response = client.post("/api/review", json=body)
    assert response.status_code == 202
    assert wait_for_review(response.json()["id"])["model"] == "openai/chosen"
    body["model"] = "openai/not-in-catalog"
    assert client.post("/api/review", json=body).status_code == 400


def test_subscription_model_selection_uses_native_model_id(monkeypatch, paper):
    from unittest.mock import AsyncMock
    monkeypatch.setenv("AI_BACKEND", "codex_cli")
    monkeypatch.setattr(app.app.state.chatgpt_login, "models", AsyncMock(return_value=[{"id": "chosen", "name": "Chosen"}]))
    import ai_backend
    monkeypatch.setattr(ai_backend.shutil, "which", lambda _: "/usr/bin/codex")

    def generate(topic, papers, key, model, **kwargs):
        assert key == "" and model == "chosen" and kwargs["backend"] == "codex_cli"
        return "Report", []

    monkeypatch.setattr(app, "generate_review", generate)
    assert client.get("/api/models").json()["models"][0]["id"] == "chosen"
    response = client.post("/api/review", json={"topic": "graphs", "papers": [asdict(paper)], "model": "chosen"})
    assert response.status_code == 202
    assert wait_for_review(response.json()["id"])["model"] == "chosen"


def test_ui_api_key_is_verified_session_scoped_and_used_without_disclosure(monkeypatch, paper):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    keys = []

    def catalog(key):
        keys.append(key)
        return [{"id": "openai/chosen", "name": "Chosen"}]

    monkeypatch.setattr(app, "list_models", catalog)
    headers = {"Origin": "http://testserver"}
    response = client.post("/api/ai/connection", json={"backend": "openai_api", "api_key": "private-input-key"}, headers=headers)
    assert response.status_code == 200 and response.json()["api_verified"] is True
    assert response.headers["cache-control"] == "no-store"
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
    assert "private-input-key" not in response.text
    assert client.get("/api/config").json()["api_verified"] is True

    def generate(topic, papers, key, model, **kwargs):
        assert key == "private-input-key" and model == "openai/chosen"
        return "Report", []

    monkeypatch.setattr(app, "generate_review", generate)
    job = client.post("/api/review", json={"topic": "graphs", "papers": [asdict(paper)], "model": "openai/chosen"})
    saved = wait_for_review(job.json()["id"])
    assert saved["status"] == "completed" and "private-input-key" not in str(saved)
    assert keys == ["private-input-key", "private-input-key"]
    identifier = response.json()["connection_id"]
    app.app.state.ai_sessions.clear()
    expired = client.post("/api/review", json={"topic": "graphs", "papers": [asdict(paper)], "connection_id": identifier})
    assert expired.status_code == 409
    client.cookies.clear()
    assert client.get("/api/config").json()["api_verified"] is False
    assert client.get("/api/config").json()["has_api_key"] is False


def test_ui_connection_rejects_cross_origin_and_keeps_working_key_after_failed_validation(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(app, "api_models", AsyncMock(return_value=[{"id": "openai/chosen", "name": "Chosen"}]))
    body = {"backend": "openai_api", "api_key": "working-key"}
    assert client.post("/api/ai/connection", json=body).status_code == 403
    headers = {"Origin": "http://testserver"}
    assert client.post("/api/ai/connection", json=body, headers=headers).status_code == 200
    monkeypatch.setattr(app, "api_models", AsyncMock(side_effect=app.HTTPException(401, "Invalid API key")))
    response = client.post("/api/ai/connection", json={"backend": "openai_api", "api_key": "bad-key"}, headers=headers)
    assert response.status_code == 401 and "bad-key" not in response.text
    assert client.get("/api/config").json()["api_verified"] is True


def test_browser_can_switch_to_subscription_without_changing_server_environment(monkeypatch):
    import ai_backend
    from unittest.mock import AsyncMock
    monkeypatch.setattr(ai_backend.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(app.app.state.chatgpt_login, "status", AsyncMock(return_value={"status": "connected", "connected": True}))
    response = client.post("/api/ai/connection", json={"backend": "codex_cli"}, headers={"Origin": "http://testserver"})
    assert response.status_code == 200 and response.json()["ai_backend"] == "codex_cli"
    assert client.get("/api/auth/chatgpt").json()["connected"] is True
    client.cookies.clear()
    assert client.get("/api/config").json()["ai_backend"] == "openai_api"
