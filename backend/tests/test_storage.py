import sqlite3

from storage import HistoryStore


def test_history_survives_reopening_and_pages_without_large_payloads(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = HistoryStore(path)
    search_id = store.create(kind="search", topic="graphs", papers=[{"title": "Paper"}],
                             filters={"area": "all"}, source="arXiv")
    review_id = store.create(kind="review", topic="graphs", papers=[], model="example")
    store.complete(review_id, "# Review", [{"text": "Evidence"}])
    reopened = HistoryStore(path)
    assert reopened.get(search_id)["filters"] == {"area": "all"}
    assert reopened.get(review_id)["evidence"][0]["text"] == "Evidence"
    page = reopened.list(limit=1)
    assert page["has_more"] and page["items"][0]["id"] == review_id
    assert "evidence" not in page["items"][0]
    assert reopened.list(limit=1, offset=1)["items"][0]["id"] == search_id


def test_restart_marks_unfinished_jobs_failed_without_changing_completed_history(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    queued = store.create(kind="review", topic="queued", papers=[])
    running = store.create(kind="review", topic="running", papers=[])
    completed = store.create(kind="review", topic="completed", papers=[])
    store.progress(running, "Working")
    store.complete(completed, "Report", [])
    store.recover_interrupted()
    for record_id in (queued, running):
        assert store.get(record_id)["status"] == "failed"
        assert "restarted" in store.get(record_id)["error"]
    assert store.get(completed)["review"] == "Report"
    store.complete(running, "Late result", [])
    assert store.get(running)["status"] == "failed"


def test_pdf_blobs_are_persistent_and_deduplicated(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = HistoryStore(path)
    url = "https://arxiv.org/pdf/2501.00001v1"
    pdf_id = store.save_pdf(url, b"%PDF-original")
    assert store.save_pdf(url, b"duplicate") == pdf_id
    reopened = HistoryStore(path)
    assert reopened.get_pdf(url=url) == b"%PDF-original"
    assert reopened.get_pdf(pdf_id=pdf_id) == b"%PDF-original"
    assert reopened.pdf_link(url) == f"/api/pdfs/{pdf_id}"


def test_existing_database_is_migrated_without_losing_saved_reports(tmp_path):
    path = tmp_path / "history.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE history (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, topic TEXT NOT NULL,
                model TEXT, papers TEXT NOT NULL, filters TEXT, source TEXT, notice TEXT,
                status TEXT NOT NULL, progress TEXT NOT NULL, review TEXT,
                evidence TEXT NOT NULL DEFAULT '[]', error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO history (id,kind,topic,papers,status,progress,review,created_at,updated_at)
            VALUES ('old','review','graphs','[]','completed','Saved','Original report','2025','2025');
        """)
    store = HistoryStore(path)
    old = store.get("old")
    assert old["review"] == "Original report"
    assert old["options"] == {} and old["checks"] == [] and old["ai_backend"] == "openai_api"
    new_id = store.create(kind="review", topic="new", papers=[], ai_backend="claude_cli",
                          options={"mode": "introduction", "units": "layouts"})
    store.complete(new_id, "New draft", [], checks=[{"name": "Coverage", "status": "warning"}])
    reopened = HistoryStore(path)
    assert reopened.get(new_id)["options"]["units"] == "layouts"
    assert reopened.get(new_id)["checks"][0]["status"] == "warning"
