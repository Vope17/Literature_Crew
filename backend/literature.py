"""arXiv retrieval and a two-agent literature review crew."""

import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict

import pymupdf
import requests

from paper_search import Paper, search_papers
from ai_backend import AIBackendError, require_cli_login, run_cli
from review_guidelines import (
    EVIDENCE_RULES, EvidenceAnalysis, ReviewOptions, analysis_prompt,
    ensure_study_placeholders, validate_analysis, writing_prompt,
)

MAX_PAPERS = 5
MAX_TEXT_CHARS = 30_000
MAX_PDF_BYTES = 20 * 1024 * 1024


def sample_pages(pages: list[tuple[int, str]]) -> tuple[str, bool]:
    """Keep early, late and section-heading pages when full text exceeds the budget."""
    full = "\n".join(f"[Page {number}]\n{text}" for number, text in pages)
    if len(full) <= MAX_TEXT_CHARS:
        return full, False
    # Include the opening and ending as well as methods/results/discussion, rather
    # than spending the whole budget on the beginning of a long paper.
    priority = [0, len(pages) - 1]
    sections = r"(?im)^\s*(?:\d+(?:\.\d+)*[.\s]+)?(?:limitations?|conclusions?|discussion|results?|methods?|methodology|experiments?)\b"
    priority.extend(i for i, (_, text) in enumerate(pages) if re.search(sections, text))
    priority.extend([1, len(pages) - 2, len(pages) - 3])
    priority.extend(round(i * (len(pages) - 1) / 11) for i in range(12))
    chosen = sorted(dict.fromkeys(i for i in priority if 0 <= i < len(pages)))
    if len(chosen) > 12:
        chosen = sorted(list(dict.fromkeys(i for i in priority if 0 <= i < len(pages)))[:12])
    # For very small test/configured budgets, a single bounded excerpt still fits.
    chosen = chosen[:max(1, min(len(chosen), MAX_TEXT_CHARS // 80))]
    allowance = max(0, (MAX_TEXT_CHARS - len(chosen) + 1) // len(chosen))
    parts = []
    marker = "\n[... text omitted ...]\n"
    for index in chosen:
        number, content = pages[index]
        label = f"[Page {number}]\n"
        budget = max(0, allowance - len(label))
        if len(content) > budget:
            if budget > len(marker):
                available = budget - len(marker)
                head = (available * 2) // 3
                tail = available - head
                content = content[:head] + marker + content[-tail:]
            else:
                content = content[:budget]
        parts.append(label + content)
    return "\n".join(parts)[:MAX_TEXT_CHARS], True


def extract_pdf(url: str, *, store=None) -> tuple[str, bool]:
    """Download a bounded PDF and return page-labelled text plus truncation status."""
    data = store.get_pdf(url=url) if store is not None else None
    downloaded = data is None
    if downloaded:
        with requests.get(url, timeout=(10, 45), stream=True) as response:
            response.raise_for_status()
            buffer = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                buffer.extend(chunk)
                if len(buffer) > MAX_PDF_BYTES:
                    raise ValueError("PDF exceeds the 20 MB download limit.")
        data = bytes(buffer)
    with pymupdf.open(stream=bytes(data), filetype="pdf") as document:
        if downloaded and store is not None:
            store.save_pdf(url, data)
        pages = []
        missing_text = False
        for index, page in enumerate(document):
            page_text = page.get_text().strip()
            if not page_text:
                missing_text = True
                continue
            pages.append((index + 1, page_text))
    if not pages:
        raise ValueError("PDF has no extractable text (OCR is not included).")
    text, sampled = sample_pages(pages)
    return text, sampled or missing_text


def collect_evidence(
    papers: list[Paper], progress: Callable[[str], None] = lambda _: None, *, pdf_store=None
) -> list[dict]:
    evidence = []
    for index, paper in enumerate(papers, start=1):
        progress(f"Reading paper {index}/{len(papers)}: {paper.title}")
        item = {"id": f"P{index}", **asdict(paper)}
        try:
            text, truncated = (extract_pdf(paper.pdf_url, store=pdf_store) if pdf_store is not None
                               else extract_pdf(paper.pdf_url))
            item.update(text=text, coverage="sampled PDF" if truncated else "full PDF")
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            item.update(text=paper.abstract, coverage="abstract only", error=str(exc))
        if pdf_store is not None:
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
    evidence = collect_evidence(papers, progress, pdf_store=pdf_store)
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
