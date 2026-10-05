from types import SimpleNamespace
from unittest.mock import MagicMock

import pymupdf
import pytest
import requests

import literature
from storage import HistoryStore


@pytest.fixture
def paper():
    return literature.Paper(
        title="Example paper",
        authors=["A. Researcher"],
        year=2025,
        url="https://arxiv.org/abs/2501.00001",
        pdf_url="https://arxiv.org/pdf/2501.00001",
        abstract="A method for graph analysis.",
    )


def mock_download(monkeypatch, data):
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_content.return_value = [data]
    monkeypatch.setattr(literature.requests, "get", lambda *args, **kwargs: response)


def test_pdf_extraction_and_truncation(monkeypatch):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "Method: graph neural network.")
        doc.new_page().insert_text((72, 72), "Results: accuracy 0.90.")
        data = doc.tobytes()
    mock_download(monkeypatch, data)
    text, truncated = literature.extract_pdf("https://arxiv.org/pdf/example")
    assert "[Page 1]" in text and "[Page 2]" in text
    assert "accuracy 0.90" in text
    assert not truncated
    monkeypatch.setattr(literature, "MAX_TEXT_CHARS", 25)
    text, truncated = literature.extract_pdf("https://arxiv.org/pdf/example")
    assert len(text) == 25
    assert truncated


def test_oversized_pdf_is_rejected(monkeypatch):
    monkeypatch.setattr(literature, "MAX_PDF_BYTES", 4)
    mock_download(monkeypatch, b"12345")
    with pytest.raises(ValueError, match="download limit"):
        literature.extract_pdf("https://arxiv.org/pdf/example")


def test_failed_pdf_uses_labelled_abstract(monkeypatch, paper):
    def fail(_):
        raise requests.Timeout("Timed out")

    monkeypatch.setattr(literature, "extract_pdf", fail)
    item = literature.collect_evidence([paper])[0]
    assert item["coverage"] == "abstract only"
    assert item["text"] == paper.abstract
    assert item["id"] == "P1"


def test_review_requires_key_before_retrieval(paper):
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        literature.generate_review("graphs", [paper], "")


def test_crew_wiring_and_source_export(monkeypatch, paper):
    import crewai

    monkeypatch.setattr(literature, "extract_pdf", lambda _: ("[Page 1] Evidence", False))
    captured = {}

    def kickoff(self, inputs):
        captured["crew"] = self
        captured["inputs"] = inputs
        return SimpleNamespace(raw="# Review\nA finding [P1].")

    monkeypatch.setattr(crewai.Crew, "kickoff", kickoff)
    review, evidence = literature.generate_review("graphs", [paper], "test-key")
    assert len(captured["crew"].agents) == 2
    assert captured["crew"].agents[0].llm.temperature is None
    assert captured["crew"].agents[0].llm.timeout == 120
    assert captured["crew"].tasks[1].context == [captured["crew"].tasks[0]]
    assert "[Page 1] Evidence" in captured["inputs"]["evidence"]
    assert paper.url in review
    assert "full PDF" in review
    assert evidence[0]["doi"] is None


def test_pdf_is_stored_and_reused_without_network(monkeypatch, paper, tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "Stored PDF evidence.")
        data = doc.tobytes()
    mock_download(monkeypatch, data)
    item = literature.collect_evidence([paper], pdf_store=store)[0]
    assert item["coverage"] == "full PDF"
    assert store.get_pdf(url=paper.pdf_url) == data
    assert item["stored_pdf_url"].startswith("/api/pdfs/")
    monkeypatch.setattr(literature.requests, "get", lambda *args, **kwargs: pytest.fail("Must use cached PDF"))
    assert "Stored PDF evidence" in literature.collect_evidence([paper], pdf_store=store)[0]["text"]


def test_scanned_pdf_is_saved_but_evidence_uses_abstract(monkeypatch, paper, tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    with pymupdf.open() as doc:
        doc.new_page()
        data = doc.tobytes()
    mock_download(monkeypatch, data)
    item = literature.collect_evidence([paper], pdf_store=store)[0]
    assert item["coverage"] == "abstract only"
    assert item["stored_pdf_url"]
    assert store.get_pdf(url=paper.pdf_url) == data
