# Literature Crew

Minimal implementation of `CrewAI_文獻搜尋.pdf`: **Vue 3 + Vite** frontend,
**FastAPI + CrewAI** backend, and **uv** for Python dependencies.

## Run for development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js
22.12+ (or a newer supported version), and [pnpm](https://pnpm.io/installation).

From the project root, start the Python API:

```sh
cd backend
uv sync
cp -n .env.example .env
uv run uvicorn app:app --reload
```

In another terminal, from the project root, start Vue:

```sh
cd frontend
pnpm install
pnpm dev
```

Open **http://localhost:5173**. Vite proxies `/api` to the backend on port 8000.
Set your API key and model in `backend/.env`:

```dotenv
OPENAI_API_KEY=your-api-key
MODEL=openai/gpt-4o-mini
```

Restart the backend after editing this file, then refresh the browser. The `.env`
file is ignored by Git. Existing process environment variables take precedence.
The UI displays the configured model; requests cannot override the server's key
or model. The frontend does not list available models. API keys are
never sent to or entered in the frontend. Search works without an OpenAI key.

1. Enter a topic, optionally select a subject area and year range, and search (no API key required).
2. Select up to five papers and click **Generate review**. Progress appears while
   the background job runs; you can continue searching.
3. Read the comparison table and research-gap discussion; download Markdown or
   source evidence JSON or saved PDFs.
4. Click **Show history** to expand saved searches and reviews, then **Open result**
   to restore one. Reopening a saved review does not generate it again or use API credits.

Search filters apply to both arXiv and the Semantic Scholar fallback. Leave either
year blank for an open-ended range; **Reset filters** returns to all subjects and
years. The results header records the filters used for the last search. Years use
arXiv submission dates or Semantic Scholar publication years. Subject taxonomies
differ: biology maps to arXiv quantitative biology, and electrical engineering maps
to arXiv eess versus Semantic Scholar's broader Engineering field.

## Run as one server

Build Vue once, then start FastAPI from the project root:

```sh
pnpm --dir frontend install
pnpm --dir frontend build
uv run --directory backend uvicorn app:app
```

Open **http://localhost:8000**. FastAPI serves `frontend/dist` when that directory
exists at startup. These commands bind to localhost; this minimal app has no
authentication and is intended for local use.

## How it works

- `frontend/src/App.vue`: search, selection, settings, sanitized Markdown rendering,
  background-job polling, expandable history, and downloads.
- `backend/app.py`: `/api/config`, `/api/models`, `/api/search`, `/api/review`,
  `/api/reviews/{id}`, `/api/history`, `/api/history/{id}`, and `/api/pdfs/{id}`.
  Interactive API docs are available at **http://localhost:8000/docs**.
- `backend/review_jobs.py`: a separate worker for CrewAI runs, with persisted
  queued/running/completed/failed status and progress.
- `backend/storage.py`: SQLite search/review history and downloaded PDF blobs.
- `backend/paper_search.py`: arXiv queries, Atom parsing, shared request pacing, and caching.
- `backend/search_filters.py`: validated subject/year filters and provider-specific mappings.
- `backend/semantic_search.py`: independent Semantic Scholar fallback with its own pacing and cache.
- `backend/model_catalog.py`: model discovery with the OpenAI SDK.
- `backend/literature.py`: PDF extraction with PyMuPDF, then two sequential
  CrewAI agents for analysis and writing.

Python dependencies, the uv lockfile, environment template, and tests also live
in `backend/`. The Vue project and its dependencies live in `frontend/`.

`POST /api/review` returns **202 Accepted** and a job ID immediately. The frontend
polls `/api/reviews/{id}` every two seconds, with a finite timeout on each request.
Model requests have a 120-second timeout. Connection failures show a **Retry status
check** button; the job keeps running on the backend. The current job ID is stored
in the browser so refreshing reconnects to it. Completed results can always be
opened from history.

SQLite is created automatically at **`backend/data/history.sqlite3`**. To change
the path, set `HISTORY_DB_PATH` in `backend/.env`; relative paths are resolved from
`backend/`. History includes successful searches, selected papers, the configured
model, review Markdown, and source evidence. PDFs downloaded for reviews are stored
in SQLite, reused on subsequent reviews, and available through **Saved PDFs** in
the report. Failed downloads remain labelled as abstract-only evidence. API keys
are never stored in history. The default data directory is ignored by Git; back
it up to retain history and PDFs.

Run one backend process (the default uvicorn command). Reviews run one at a time;
additional requests are queued. An interrupted job is marked failed on the next
backend startup; open its saved papers and generate again. Closing the browser
does not cancel a job, and graceful shutdown waits for active jobs to finish.

Search requests are serialized with a three-second minimum gap per server process.
Identical searches are cached for 15 minutes. Temporary server and network errors
are retried up to twice with finite connect/read timeouts. Each provider honors
`Retry-After`, or uses a 60-second cooldown when it is omitted. If fallback cannot
provide results either, the UI shows the error and a countdown when available.
Cached results remain available during cooldowns. arXiv can still rate-limit a shared public IP; the app cannot remove an
upstream limit. When arXiv is rate-limited or unavailable, plain keyword searches
automatically fall back to Semantic Scholar's bulk-search API. The UI labels the
source and returns arXiv-linked papers from the first batch (up to 1,000 records),
ordered by citation count. arXiv-specific field queries are not silently translated.
PDFs still come from arXiv; blocked PDF downloads use the returned abstracts.
Invalid queries, timeouts, and connectivity failures are reported
separately rather than hidden behind one generic error.

If both providers are rate-limited, wait for the displayed cooldown. You can also
set an optional `SEMANTIC_SCHOLAR_API_KEY` in `backend/.env` and restart the backend
to use dedicated Semantic Scholar credentials. Request a key through
[Semantic Scholar](https://www.semanticscholar.org/product/api).

PDF downloads are limited to 20 MB and extracted text to the first 30,000
characters per paper. Failed downloads and scanned PDFs fall back to abstracts;
the UI and report identify limited coverage. OCR, SCI-index verification,
Zotero, and BibTeX export are outside this minimal version.
arXiv includes preprints, and generated claims still need human review. Generating
a review sends paper text to the model provider and uses API credits. Closing
the tab does not cancel an already-running backend review.

## Test

```sh
uv run --directory backend pytest
pnpm --dir frontend test
pnpm --dir frontend build
```

Tests use local PDFs and mocked services; they do not need API keys or credits.

References: [Vue](https://vuejs.org/guide/quick-start.html),
[FastAPI](https://fastapi.tiangolo.com/),
[OpenAI model listing](https://developers.openai.com/api/reference/resources/models),
[CrewAI tasks](https://docs.crewai.com/en/concepts/tasks), and
[arXiv search](https://info.arxiv.org/help/api/user-manual.html).
