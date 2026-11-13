"""arXiv retrieval and a two-agent literature review crew."""

import json
import os
from collections.abc import Callable
from dataclasses import asdict

import requests

from paper_search import Paper, search_papers
from ai_backend import AIBackendError, AISettings, require_cli_login, run_cli
from pdf_reading import load_pdf, read_pdf
from review_guidelines import (
    EVIDENCE_RULES, EvidenceAnalysis, ReviewOptions, analysis_prompt,
    ensure_study_placeholders, validate_analysis, writing_prompt,
)

MAX_PAPERS = 5
NO_TEXT_NOTICE = ("No abstract or open full text was available for this paper. Only its bibliographic "
                  "metadata (title, authors, year, journal) is known; make no claims about its content.")


def collect_evidence(
    papers: list[Paper], progress: Callable[[str], None] = lambda _: None, *,
    topic: str, settings: AISettings, pdf_store=None,
) -> list[dict]:
    evidence = []
    for index, paper in enumerate(papers, start=1):
        progress(f"Loading paper {index}/{len(papers)}: {paper.title}")
        item = {"id": f"P{index}", **asdict(paper)}
        try:
            if not paper.pdf_url:
                raise ValueError("No open full text is available.")
            data = load_pdf(paper.pdf_url, store=pdf_store)
        except (requests.RequestException, RuntimeError, ValueError):
            item.update(
                # Never hand the analyst an empty text to fill in from its own knowledge.
                text=paper.abstract or NO_TEXT_NOTICE, coverage="abstract only",
                error=("No open full text is available; only the abstract was supplied." if not paper.pdf_url
                       else "PDF download or opening failed; only the abstract was supplied."),
            )
        else:
            # Analysis/rendering failures must stop the job, never masquerade as completed reading.
            item.update(read_pdf(data, item["id"], topic, settings, progress))
        if pdf_store is not None and paper.pdf_url:
            item["stored_pdf_url"] = pdf_store.pdf_link(paper.pdf_url)
        evidence.append(item)
    return evidence


def generate_review(
    topic: str,
    papers: list[Paper],
    api_key: str = "",
    model: str = "openai/gpt-4o-mini",
    progress: Callable[[str], None] = lambda _: None,
    *, pdf_store=None, backend: str = "openai_api", cli_timeout: int = 600,
    options: ReviewOptions | None = None,
) -> tuple[str, list[dict]]:
    """Fetch evidence, then run an analyst and a writer sequentially."""
    if backend not in ("openai_api", "codex_cli", "claude_cli"):
        raise AIBackendError("Unsupported AI backend.")
    if backend == "openai_api" and not api_key.strip():
        raise ValueError("Set OPENAI_API_KEY in backend/.env.")
    if not topic.strip() or (backend == "openai_api" and not model.strip()):
        raise ValueError("Topic and model must not be empty.")
    if not 1 <= len(papers) <= MAX_PAPERS:
        raise ValueError(f"Select between 1 and {MAX_PAPERS} papers.")

    options = options or ReviewOptions()
    if backend != "openai_api":
        require_cli_login(backend)
    settings = AISettings(backend, model, api_key, cli_timeout)
    evidence = collect_evidence(papers, progress, topic=topic, settings=settings, pdf_store=pdf_store)
    analysis_text = analysis_prompt(topic, evidence)
    writing_text = writing_prompt(topic, options)
    metadata = [{key: item[key] for key in ("id", "title", "year", "coverage")} for item in evidence]
    writing_text += "\nVerified source metadata JSON:\n" + json.dumps(metadata, ensure_ascii=False)

    if backend != "openai_api":
        progress("Analyzing papers and synthesizing evidence…")
        raw_analysis = run_cli(backend, analysis_text, model=model,
                               schema=EvidenceAnalysis.model_json_schema(), timeout=cli_timeout)
        notes = EvidenceAnalysis.model_validate_json(raw_analysis)
        validate_analysis(notes, evidence)
        progress("Analysis complete. Writing the review…")
        raw_review = run_cli(backend, writing_text + "\nValidated analysis JSON:\n" + notes.model_dump_json(),
                             model=model, timeout=cli_timeout)
    else:
        raw_review, notes = _run_crew(analysis_text, writing_text, evidence, api_key, model, progress)

    notes_by_id = {paper.paper_id: paper for paper in notes.papers}
    for item in evidence:
        item["analysis"] = notes_by_id[item["id"]].model_dump()
    references = "\n\n## Sources and coverage\n\n" + "\n".join(
        f"- [{item['id']}] {item['title']} ({item['year']}). "
        f"{item['url']} — {item['coverage']}"
        for item in evidence
    )
    return ensure_study_placeholders(raw_review, options) + references, evidence


def _run_crew(analysis_text, writing_text, evidence, api_key, model, progress):
    # Import lazily so searching and CLI usage do not initialize an API client.
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    from crewai import Agent, Crew, LLM, Process, Task

    # Let the provider use its default; reasoning models may reject temperature.
    llm = LLM(model=model.strip(), api_key=api_key.strip(), timeout=120)
    analyst = Agent(
        role="Literature analyst",
        goal="Extract and compare evidence about the research topic.",
        backstory=EVIDENCE_RULES,
        llm=llm,
        allow_delegation=False,
        max_iter=3,
    )
    writer = Agent(
        role="Literature review writer",
        goal="Write a concise, traceable Markdown literature review.",
        backstory=EVIDENCE_RULES,
        llm=llm,
        allow_delegation=False,
        max_iter=3,
    )
    validated = []

    def analysis_complete(output):
        notes = output.pydantic if isinstance(output.pydantic, EvidenceAnalysis) else EvidenceAnalysis.model_validate_json(output.raw)
        validate_analysis(notes, evidence)
        validated.append(notes)
        progress("Analysis complete. Writing the review…")

    analysis = Task(
        description="{analysis_prompt}",
        expected_output="Structured, source-linked paper notes, thematic synthesis, opposing findings and candidate gaps.",
        output_pydantic=EvidenceAnalysis,
        agent=analyst,
        callback=analysis_complete,
    )
    writing = Task(
        description="{writing_prompt}",
        expected_output="A Markdown literature review, without enclosing code fences.",
        agent=writer,
        context=[analysis],
        markdown=True,
    )
    progress("Analyzing papers and writing the review…")
    result = Crew(
        agents=[analyst, writer],
        tasks=[analysis, writing],
        process=Process.sequential,
        memory=False,
        verbose=False,
        tracing=False,
    ).kickoff(inputs={"analysis_prompt": analysis_text, "writing_prompt": writing_text})
    if not validated:
        raise ValueError("No validated evidence analysis was produced.")
    return result.raw, validated[-1]
