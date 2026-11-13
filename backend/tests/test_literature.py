from types import SimpleNamespace

import pytest
import requests

import literature


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


def test_failed_pdf_uses_labelled_abstract(monkeypatch, paper):
    def fail(*args, **kwargs):
        raise requests.Timeout("private network details")
    monkeypatch.setattr(literature, "load_pdf", fail)
    item = literature.collect_evidence([paper], topic="graphs", settings=literature.AISettings("openai_api", "example", "key"))[0]
    assert item["coverage"] == "abstract only" and item["text"] == paper.abstract
    assert "private" not in item["error"]


def test_paper_without_open_pdf_or_abstract_never_reaches_the_analyst_empty(monkeypatch):
    monkeypatch.setattr(literature, "load_pdf", lambda *a, **kw: pytest.fail("No PDF to download"))
    closed = literature.Paper("Closed paper", ["Ada"], 2024, "https://doi.org/10.1/closed", None, "",
                              doi="10.1/closed", journal="Journal of Graphs")
    item = literature.collect_evidence([closed], topic="graphs", settings=literature.AISettings("openai_api", "example", "key"))[0]
    assert item["coverage"] == "abstract only" and "make no claims" in item["text"]
    assert "No open full text" in item["error"] and item["journal"] == "Journal of Graphs"


@pytest.fixture
def read_evidence(monkeypatch):
    monkeypatch.setattr(literature, "load_pdf", lambda *a, **kw: b"PDF")
    monkeypatch.setattr(literature, "read_pdf", lambda *a, **kw: {
        "text": "[Page 1] Evidence", "coverage": "multimodal PDF", "citation_pages": [1],
        "pages": [{"page": 1, "text": "Full page text excluded from final synthesis"}],
        "page_count": 1, "processed_pages": 1,
    })


def test_review_requires_key_before_retrieval(paper):
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        literature.generate_review("graphs", [paper], "")


def test_crew_wiring_and_source_export(monkeypatch, paper, analysis_notes, read_evidence):
    import crewai

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
    assert "multimodal PDF" in review
    assert "Full page text excluded" not in captured["inputs"]["analysis_prompt"]
    assert evidence[0]["doi"] is None
    assert evidence[0]["analysis"]["findings"][0]["kind"] == "reported"


@pytest.mark.parametrize("backend", ["codex_cli", "claude_cli"])
def test_cli_uses_validated_analysis_before_writing_without_api_key(monkeypatch, paper, analysis_notes, backend, read_evidence):
    calls = []
    monkeypatch.setattr(literature, "require_cli_login", lambda value: calls.append(value))

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


def test_invalid_analysis_stops_before_writing(monkeypatch, paper, analysis_notes, read_evidence):
    monkeypatch.setattr(literature, "require_cli_login", lambda _: None)
    analysis_notes.papers[0].findings[0].citations[0].page = 99
    calls = []

    def cli(*args, **kwargs):
        calls.append(args)
        return analysis_notes.model_dump_json()

    monkeypatch.setattr(literature, "run_cli", cli)
    with pytest.raises(ValueError, match="outside"):
        literature.generate_review("graphs", [paper], backend="codex_cli", model="")
    assert len(calls) == 1


def test_multimodal_failure_does_not_fall_back_to_abstract(monkeypatch, paper):
    monkeypatch.setattr(literature, "load_pdf", lambda *a, **kw: b"PDF")
    def fail(*args, **kwargs):
        raise literature.AIBackendError("Batch 2 failed")
    monkeypatch.setattr(literature, "read_pdf", fail)
    with pytest.raises(literature.AIBackendError, match="Batch 2"):
        literature.collect_evidence([paper], topic="graphs", settings=literature.AISettings("openai_api", "example", "key"))


def test_pdf_readings_flow_into_synthesis_and_export(monkeypatch, paper, analysis_notes):
    import json
    import pymupdf
    import pdf_reading
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "Evidence on the first page.")
        data = doc.tobytes()
    monkeypatch.setattr(literature, "load_pdf", lambda *a, **kw: data)
    def read(prompt, schema, settings, *, images):
        assert images[0].startswith(b"\x89PNG")
        return pdf_reading.BatchReading(pages=[{
            "page": 1, "part": 1, "status": "readable", "limitations": "",
            "observations": [{"text": "A graph method is reported.", "kind": "reported", "content_type": "figure"}],
        }])
    monkeypatch.setattr(pdf_reading, "read_structured", read)
    def crew(analysis, writing, evidence, *args):
        context = json.loads(analysis.split("Evidence JSON:\n")[1])
        assert "pages" not in context[0]
        assert "A graph method is reported." in context[0]["text"]
        literature.validate_analysis(analysis_notes, evidence)
        return "A finding [P1, p. 1].", analysis_notes
    monkeypatch.setattr(literature, "_run_crew", crew)
    review, evidence = literature.generate_review("graphs", [paper], "test-key")
    assert evidence[0]["pages"][0]["text"] == "Evidence on the first page."
    assert evidence[0]["processed_pages"] == 1
    assert "multimodal PDF" in review
