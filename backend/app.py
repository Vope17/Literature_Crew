"""FastAPI backend. From the project root: uv run --directory backend uvicorn app:app --reload"""

import logging
import os
import asyncio
from dataclasses import replace
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from typing import Literal
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, PermissionDeniedError, RateLimitError

from literature import MAX_PAPERS, Paper, generate_review, search_papers
from model_catalog import list_models
from paper_search import SearchError
from search_keywords import MAX_TOPIC_CHARS, extract_keywords
from semantic_search import search_semantic_scholar
from search_filters import AREAS, SearchFilters
from openalex_search import search_openalex
from search_catalog import search_catalog, SOURCE_LABELS
from paper_urls import public_url
from storage import HistoryStore
from review_jobs import ReviewJobs
from ai_backend import AIBackendError, AISettings, get_settings, require_cli_login
from ai_sessions import AISessions, COOKIE_NAME, SESSION_SECONDS
from chatgpt_login import ChatGPTLogin
from review_guidelines import ReviewOptions

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
    app.state.chatgpt_login = ChatGPTLogin()
    app.state.ai_sessions = AISessions()
    try:
        yield
    finally:
        app.state.ai_sessions.clear()
        await app.state.chatgpt_login.close()
        await asyncio.to_thread(app.state.jobs.shutdown)


app = FastAPI(title="Literature Crew", lifespan=lifespan)


class SearchRequest(SearchFilters):
    model_config = ConfigDict(str_strip_whitespace=True)
    topic: str = Field(min_length=1, max_length=MAX_TOPIC_CHARS)
    limit: int = Field(default=5, ge=1, le=10)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    connection_id: str | None = Field(default=None, max_length=128)
    filter_overrides: list[Literal["area", "years", "limit"]] | None = Field(default=None, max_length=3)
    # Omitted by older clients, which retain the arXiv -> Semantic Scholar fallback.
    sources: list[Literal["arxiv", "openalex", "semantic_scholar"]] | None = Field(default=None, min_length=1, max_length=3)


class PaperInput(BaseModel):
    title: str = Field(min_length=1, max_length=2000)
    authors: list[str] = Field(max_length=1000)
    year: int
    url: str
    pdf_url: str | None = None
    abstract: str = Field(max_length=50_000)
    doi: str | None = None
    source: str = Field(default="arXiv", max_length=100)
    journal: str | None = Field(default=None, max_length=2000)
    issn: list[str] = Field(default_factory=list, max_length=20)
    publication_type: str | None = Field(default=None, max_length=200)
    sources: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("url", "pdf_url")
    @classmethod
    def paper_url(cls, value, info):
        if value is None and info.field_name == "pdf_url":
            return None
        if not public_url(value):
            raise ValueError("Only public HTTPS paper URLs are accepted.")
        return value


class ReviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    topic: str = Field(min_length=1, max_length=MAX_TOPIC_CHARS)
    papers: list[PaperInput] = Field(min_length=1, max_length=MAX_PAPERS)
    options: ReviewOptions = Field(default_factory=ReviewOptions)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    connection_id: str | None = Field(default=None, max_length=128)


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["openai_api", "codex_cli", "claude_cli"]
    api_key: SecretStr | None = Field(default=None, max_length=1024)


def effective_settings(request: Request):
    return app.state.ai_sessions.get(request.cookies.get(COOKIE_NAME)) or get_settings()


def check_connection(request, identifier):
    if identifier is not None and identifier != app.state.ai_sessions.identifier(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(409, "AI connection expired or changed. Reconnect in settings.")


def connection_config(settings, verified=False):
    return {**settings.public_config(), "api_verified": verified and settings.backend == "openai_api",
            "connection_verified": verified}


def require_ui_origin(request: Request):
    origin = urlsplit(request.headers.get("origin", ""))
    if (origin.scheme not in ("http", "https") or origin.netloc != request.headers.get("host")
            or request.headers.get("content-type", "").split(";")[0] != "application/json"):
        raise HTTPException(403, "Use the settings panel on this application's page.")


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not echo request bodies, which can contain an API key.
    return JSONResponse(status_code=422, content={"detail": "Invalid input. Check the topic, paper selection, and settings."})


@app.get("/api/config")
def config(request: Request):
    session = app.state.ai_sessions.get(request.cookies.get(COOKIE_NAME))
    return {
        **connection_config(session or get_settings(), verified=session is not None),
        "connection_id": app.state.ai_sessions.identifier(request.cookies.get(COOKIE_NAME)),
        "max_papers": MAX_PAPERS,
        "search_areas": [{"value": value, "label": details[0]} for value, details in AREAS.items()],
        "search_sources": [{"value": value, "label": label} for value, label in SOURCE_LABELS.items()],
    }


@app.post("/api/search")
async def search(body: SearchRequest, request: Request):
    check_connection(request, body.connection_id)
    settings = effective_settings(request)
    if body.model is not None:
        catalog = await models(request)
        if body.model not in {item["id"] for item in catalog["models"]}:
            raise HTTPException(400, "Selected model is not in the current model list. Refresh models and select again.")
        settings = replace(settings, model=body.model)
    if error := settings.setup_error():
        raise HTTPException(400, "Connect AI in settings before searching. " + error)
    try:
        keywords = await asyncio.to_thread(extract_keywords, body.topic, settings)
    except AIBackendError as exc:
        raise HTTPException(503, str(exc)) from None
    return await asyncio.to_thread(search_with_keywords, body, keywords, settings)


def search_with_keywords(body, keywords, settings):
    filters, limit = keywords.resolve_filters(
        SearchFilters(area=body.area, year_from=body.year_from, year_to=body.year_to),
        body.limit, body.filter_overrides,
    )
    applied_filters = {**filters.model_dump(), "limit": limit}
    if body.sources is not None:
        applied_filters["sources"] = list(dict.fromkeys(body.sources))
    try:
        source_status = []
        if body.sources is not None:
            papers, source_status, notice = search_catalog(keywords.query, limit, filters, body.sources, {
                "arxiv": search_papers, "semantic_scholar": search_semantic_scholar, "openalex": search_openalex,
            })
            source = " + ".join(item["source"] for item in source_status if item["status"] == "ok")
        else:
            papers, source, notice = legacy_search(keywords.query, limit, filters)
        payload = {"papers": [asdict(paper) for paper in papers], "source": source, "notice": notice,
                   "keywords": keywords.keywords, "filters": applied_filters, "source_status": source_status}
        payload["history_id"] = app.state.store.create(
            kind="search", topic=body.topic, papers=payload["papers"], filters=applied_filters,
            source=source, notice=notice,
            keywords=keywords.keywords, model=settings.model, ai_backend=settings.backend,
        )
        return payload
    except SearchError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(exc.status_code, str(exc), headers=headers) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception:
        logger.exception("Unexpected paper search failure")
        raise HTTPException(502, "Unexpected search error. Check the backend log for details.") from None


def legacy_search(query, limit, filters):
        try:
            papers = search_papers(query, limit, filters=filters)
            source, notice = "arXiv", None
        except SearchError as primary_error:
            if primary_error.status_code not in (429, 502, 503, 504):
                raise
            try:
                papers = search_semantic_scholar(query, limit, filters=filters)
            except SearchError as fallback_error:
                raise SearchError(
                    f"arXiv is unavailable. {fallback_error}",
                    fallback_error.status_code, fallback_error.retry_after,
                ) from None
            source = "Semantic Scholar"
            notice = (
                "arXiv search is unavailable. Showing papers found through "
                "Semantic Scholar, ordered by citation count."
            )
            if not papers:
                notice += " No matches were found; try different keywords."
        return papers, source, notice


async def chatgpt_auth_response(request: Request, action: str):
    if effective_settings(request).backend != "codex_cli":
        raise HTTPException(409, "ChatGPT sign-in requires AI_BACKEND=codex_cli on the backend.")
    if action != "status":
        require_ui_origin(request)
    try:
        result = await getattr(app.state.chatgpt_login, action)()
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except AIBackendError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


@app.get("/api/auth/chatgpt")
async def chatgpt_auth_status(request: Request):
    return await chatgpt_auth_response(request, "status")


@app.post("/api/auth/chatgpt/start")
async def chatgpt_auth_start(request: Request):
    return await chatgpt_auth_response(request, "start")


@app.post("/api/auth/chatgpt/cancel")
async def chatgpt_auth_cancel(request: Request):
    return await chatgpt_auth_response(request, "cancel")


@app.get("/api/models")
async def models(request: Request, connection_id: str | None = None):
    check_connection(request, connection_id)
    settings = effective_settings(request)
    if settings.backend == "codex_cli":
        try:
            return {"models": await app.state.chatgpt_login.models(),
                    "notice": "Model access is confirmed when generation runs."}
        except AIBackendError as exc:
            raise HTTPException(503, str(exc)) from None
    if settings.backend == "claude_cli":
        try:
            await asyncio.to_thread(require_cli_login, "claude_cli")
        except AIBackendError as exc:
            raise HTTPException(503, str(exc)) from None
        return {"models": [{"id": name, "name": name.title()} for name in ("sonnet", "opus", "haiku")],
                "notice": "Claude Code aliases. Model access depends on your account."}
    if settings.backend != "openai_api":
        raise HTTPException(400, "Check AI_BACKEND in backend/.env.")
    api_key = settings.api_key
    if not api_key:
        raise HTTPException(400, "Set OPENAI_API_KEY in backend/.env and restart the backend to load models.")
    return {"models": await api_models(api_key)}


async def api_models(api_key):
    try:
        return await asyncio.to_thread(list_models, api_key)
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


@app.post("/api/ai/connection")
async def set_ai_connection(body: ConnectionInput, request: Request):
    require_ui_origin(request)
    current = effective_settings(request)
    if body.backend == "openai_api":
        key = body.api_key.get_secret_value().strip() if body.api_key else ""
        key = key or current.api_key or os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            raise HTTPException(400, "Enter an OpenAI API key.")
        catalog = await api_models(key)
        if not catalog:
            raise HTTPException(400, "The API key returned no supported text models.")
        default = os.getenv("MODEL", "").strip()
        if default not in {item["id"] for item in catalog}:
            default = catalog[0]["id"]
        settings = AISettings("openai_api", default, key)
    else:
        settings = AISettings(body.backend, os.getenv("CLI_MODEL", "").strip(), "", current.timeout)
        if error := settings.setup_error():
            raise HTTPException(400, error)
        if body.backend == "claude_cli":
            try:
                await asyncio.to_thread(require_cli_login, "claude_cli")
            except AIBackendError as exc:
                raise HTTPException(503, str(exc)) from None
    token = app.state.ai_sessions.set(request.cookies.get(COOKIE_NAME), settings)
    payload = {**connection_config(settings, verified=True), "connection_id": app.state.ai_sessions.identifier(token)}
    response = JSONResponse(payload, headers={"Cache-Control": "no-store"})
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=urlsplit(request.headers.get("origin", "")).scheme == "https", samesite="strict", path="/api")
    return response


@app.post("/api/review", status_code=202)
async def review(body: ReviewRequest, request: Request):
    check_connection(request, body.connection_id)
    settings = effective_settings(request)
    error = settings.setup_error()
    if error and not (body.model and settings.backend == "openai_api" and settings.api_key and not settings.model):
        raise HTTPException(400, error)
    selected_model = settings.model
    if body.model is not None:
        catalog = await models(request)
        if body.model not in {item["id"] for item in catalog["models"]}:
            raise HTTPException(400, "Selected model is not in the current model list. Refresh models and select again.")
        selected_model = body.model
    record_id = app.state.jobs.submit(body.topic, [Paper(**paper.model_dump()) for paper in body.papers],
                                     settings.api_key, selected_model, generate_review,
                                     backend=settings.backend, cli_timeout=settings.timeout, options=body.options)
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
