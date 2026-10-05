"""FastAPI backend. From the project root: uv run --directory backend uvicorn app:app --reload"""

import logging
import os
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, PermissionDeniedError, RateLimitError

from literature import MAX_PAPERS, Paper, generate_review, search_papers
from model_catalog import list_models
from paper_search import SearchError, search_query
from semantic_search import search_semantic_scholar
from search_filters import AREAS, SearchFilters
from storage import HistoryStore
from review_jobs import ReviewJobs

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    path = Path(os.getenv("HISTORY_DB_PATH", "data/history.sqlite3"))
    if not path.is_absolute():
        path = BACKEND_DIR / path
    app.state.store = HistoryStore(path)
    app.state.store.recover_interrupted()
    app.state.jobs = ReviewJobs(app.state.store)
    try:
        yield
    finally:
        await asyncio.to_thread(app.state.jobs.shutdown)


app = FastAPI(title="Literature Crew", lifespan=lifespan)


class SearchRequest(SearchFilters):
    model_config = ConfigDict(str_strip_whitespace=True)
    topic: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class PaperInput(BaseModel):
    title: str = Field(min_length=1, max_length=2000)
    authors: list[str] = Field(max_length=1000)
    year: int
    url: str
    pdf_url: str
    abstract: str = Field(max_length=50_000)
    doi: str | None = None

    @field_validator("url", "pdf_url")
    @classmethod
    def arxiv_url(cls, value: str, info) -> str:
        parsed = urlsplit(value)
        prefix = "/pdf/" if info.field_name == "pdf_url" else "/abs/"
        if (
            parsed.scheme != "https"
            or parsed.netloc != "arxiv.org"
            or not parsed.path.startswith(prefix)
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Only HTTPS arXiv paper URLs are accepted.")
        return value


class ReviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    topic: str = Field(min_length=1, max_length=500)
    papers: list[PaperInput] = Field(min_length=1, max_length=MAX_PAPERS)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not echo request bodies, which can contain an API key.
    return JSONResponse(status_code=422, content={"detail": "Invalid input. Check the topic, paper selection, and settings."})


@app.get("/api/config")
def config():
    return {
        "model": os.getenv("MODEL", "").strip(),
        "has_api_key": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "max_papers": MAX_PAPERS,
        "search_areas": [{"value": value, "label": details[0]} for value, details in AREAS.items()],
    }


@app.post("/api/search")
def search(body: SearchRequest):
    filters = SearchFilters(area=body.area, year_from=body.year_from, year_to=body.year_to)
    try:
        try:
            papers = search_papers(body.topic, body.limit, filters=filters)
            source, notice = "arXiv", None
        except SearchError as primary_error:
            if primary_error.status_code not in (429, 502, 503, 504):
                raise
            # arXiv field operators have different meanings in the fallback API.
            if search_query(body.topic) == body.topic:
                raise SearchError(
                    "arXiv is unavailable. Use plain keywords to enable the Semantic Scholar fallback; arXiv field queries cannot be transferred.",
                    primary_error.status_code, primary_error.retry_after,
                ) from None
            try:
                papers = search_semantic_scholar(body.topic, body.limit, filters=filters)
            except SearchError as fallback_error:
                raise SearchError(
                    f"arXiv is unavailable. {fallback_error}",
                    fallback_error.status_code, fallback_error.retry_after,
                ) from None
            source = "Semantic Scholar"
            notice = (
                "arXiv search is unavailable. Showing arXiv-linked papers found through "
                "Semantic Scholar, ordered by citation count."
            )
            if not papers:
                notice += " No arXiv-linked matches were found in the first results page; try different keywords."
        payload = {"papers": [asdict(paper) for paper in papers], "source": source, "notice": notice}
        payload["history_id"] = app.state.store.create(
            kind="search", topic=body.topic, papers=payload["papers"], filters=filters.model_dump(),
            source=source, notice=notice,
        )
        return payload
    except SearchError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(exc.status_code, str(exc), headers=headers) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception:
        logger.exception("Unexpected arXiv search failure")
        raise HTTPException(502, "Unexpected search error. Check the backend log for details.") from None


@app.get("/api/models")
def models():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(400, "Set OPENAI_API_KEY in backend/.env and restart the backend to load models.")
    try:
        return {"models": list_models(api_key)}
    except AuthenticationError:
        raise HTTPException(401, "OpenAI rejected the API key. Check it and reload models.") from None
    except PermissionDeniedError:
        raise HTTPException(403, "This key cannot list models. Check its project permissions.") from None
    except RateLimitError:
        raise HTTPException(429, "OpenAI rate-limited model discovery. Wait a moment and reload models.") from None
    except APITimeoutError:
        raise HTTPException(504, "OpenAI model discovery timed out. Please retry.") from None
    except APIConnectionError:
        raise HTTPException(503, "Cannot connect to OpenAI. Check the backend's connection or proxy.") from None
    except APIStatusError:
        raise HTTPException(502, "OpenAI could not list models. Please retry later.") from None


@app.post("/api/review", status_code=202)
def review(body: ReviewRequest):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("MODEL", "").strip()
    if not api_key:
        raise HTTPException(400, "Set OPENAI_API_KEY in backend/.env and restart the backend first.")
    if not model:
        raise HTTPException(400, "Set MODEL in backend/.env and restart the backend first.")
    record_id = app.state.jobs.submit(body.topic, [Paper(**paper.model_dump()) for paper in body.papers],
                                     api_key, model, generate_review)
    return {"id": record_id, "status": "queued"}


@app.get("/api/reviews/{record_id}")
def review_status(record_id: str):
    record = app.state.store.get(record_id)
    if record is None or record["kind"] != "review":
        raise HTTPException(404, "Review not found.")
    return record


@app.get("/api/history")
def history(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    return app.state.store.list(limit, offset)


@app.get("/api/history/{record_id}")
def history_detail(record_id: str):
    record = app.state.store.get(record_id)
    if record is None:
        raise HTTPException(404, "History result not found.")
    return record


@app.get("/api/pdfs/{pdf_id}")
def saved_pdf(pdf_id: str):
    data = app.state.store.get_pdf(pdf_id=pdf_id)
    if data is None:
        raise HTTPException(404, "Saved PDF not found.")
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="paper-{pdf_id[:12]}.pdf"'})


# Build the frontend before starting the server to serve everything on port 8000.
dist = BACKEND_DIR.parent / "frontend" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
