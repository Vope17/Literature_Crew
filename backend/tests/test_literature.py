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


def test_crew_wiring_and_source_export(monkeypatch, paper, analysis_notes):
    import crewai

    monkeypatch.setattr(literature, "extract_pdf", lambda _: ("[Page 1] Evidence", False))
    captured = {}

    def kickoff(self, inputs):
        captured["crew"] = self
        captured["inputs"] = inputs
        self.tasks[0].callback(SimpleNamespace(pydantic=analysis_notes))
        return SimpleNamespace(raw="# Review\nA finding [P1].")

    monkeypatch.setattr(crewai.Crew, "kickoff", kickoff)
    review, evidence = literature.generate_review("graphs", [paper], "test-key")
    assert len(captured["crew"].agents) == 2
    assert captured["crew"].agents[0].llm.temperature is None
    assert captured["crew"].agents[0].llm.timeout == 120
    assert captured["crew"].tasks[1].context == [captured["crew"].tasks[0]]
    assert "[Page 1] Evidence" in captured["inputs"]["analysis_prompt"]
    assert paper.url in review
    assert "full PDF" in review
    assert evidence[0]["doi"] is None
    assert evidence[0]["analysis"]["findings"][0]["kind"] == "reported"


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


def test_long_pdf_keeps_ending_and_middle_sections_within_budget(monkeypatch):
    monkeypatch.setattr(literature, "MAX_TEXT_CHARS", 1800)
    pages = [(i, ("Introduction\n" if i == 1 else "") + "Background text. " * 200) for i in range(1, 21)]
    pages[9] = (10, "Results\nContradictory result in the middle. " + "More evidence. " * 200)
    pages[-1] = (20, "Limitations\nThe method fails on unseen graphs. " + "More limitations. " * 200)
    text, sampled = literature.sample_pages(pages)
    assert sampled and len(text) <= 1800
    assert "[Page 1]" in text and "[Page 20]" in text
    assert "Contradictory result" in text and "fails on unseen graphs" in text


@pytest.mark.parametrize("backend", ["codex_cli", "claude_cli"])
def test_cli_uses_validated_analysis_before_writing_without_api_key(monkeypatch, paper, analysis_notes, backend):
    calls = []
    monkeypatch.setattr(literature, "require_cli_login", lambda value: calls.append(value))
    monkeypatch.setattr(literature, "extract_pdf", lambda _: ("[Page 1] Evidence", False))

    def cli(value, prompt, **kwargs):
        calls.append((value, prompt, kwargs))
        return analysis_notes.model_dump_json() if kwargs.get("schema") else "# Review\nA finding [P1, p. 1]."

    monkeypatch.setattr(literature, "run_cli", cli)
    review, evidence = literature.generate_review("graphs", [paper], backend=backend, model="")
    assert calls[0] == backend and len(calls) == 3
    assert calls[1][2]["schema"]["type"] == "object"
    assert "Validated analysis JSON" in calls[2][1]
    assert "Sources and coverage" in review
    assert evidence[0]["analysis"]["paper_id"] == "P1"


def test_invalid_analysis_stops_before_writing(monkeypatch, paper, analysis_notes):
    monkeypatch.setattr(literature, "require_cli_login", lambda _: None)
    monkeypatch.setattr(literature, "extract_pdf", lambda _: ("[Page 1] Evidence", False))
    analysis_notes.papers[0].findings[0].citations[0].page = 99
    calls = []

    def cli(*args, **kwargs):
        calls.append(args)
        return analysis_notes.model_dump_json()

    monkeypatch.setattr(literature, "run_cli", cli)
    with pytest.raises(ValueError, match="outside"):
        literature.generate_review("graphs", [paper], backend="codex_cli", model="")
    assert len(calls) == 1
