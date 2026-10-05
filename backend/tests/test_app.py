from dataclasses import asdict
from threading import Event
import time

import pytest
from fastapi.testclient import TestClient

import app
from literature import Paper
from paper_search import SearchError

@pytest.fixture(autouse=True)
def isolated_history(monkeypatch, tmp_path):
    global client
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "history.sqlite3"))
    monkeypatch.setenv("MODEL", "openai/example")
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


def test_advanced_query_does_not_silently_change_meaning(monkeypatch):
    def primary(*args, **kwargs):
        raise SearchError("arXiv unavailable", 429, 60)

    def fallback(*args, **kwargs):
        pytest.fail("arXiv field syntax cannot be sent to Semantic Scholar")

    monkeypatch.setattr(app, "search_papers", primary)
    monkeypatch.setattr(app, "search_semantic_scholar", fallback)
    response = client.post("/api/search", json={"topic": "ti:graphs AND cat:cs.LG"})
    assert response.status_code == 429
    assert "plain keywords" in response.json()["detail"]


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


@pytest.mark.parametrize("override", [{"api_key": "browser-secret"}, {"model": "openai/browser-model"}])
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

    def generate(topic, papers, key, model, *, progress, pdf_store):
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
