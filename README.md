# Literature Crew

Minimal implementation of `CrewAI_文獻搜尋.pdf`: **Vue 3 + Vite + TypeScript** frontend,
**FastAPI + CrewAI** backend, and **uv** for Python dependencies. Reports follow
the supplied `緒論規範.pdf`: evidence-linked thematic synthesis, alternative findings,
candidate research gaps, and an optional introduction draft with your study details.

## Run with Docker

Docker Engine with Compose v2.24+ is sufficient; Python, uv, Node and the official
AI CLIs are installed inside the image.

```sh
make env
# Edit backend/.env to choose an AI backend (see below).
docker compose up --build -d
```

Open **http://localhost:8000**. `docker compose logs -f app` shows server logs;
`docker compose down` stops the app while preserving its volumes. The app runs as
an unprivileged container user, and the published port binds only to localhost.
The image excludes `.env`, local credentials, databases and PDFs from its build context.

Nginx is the only published service: `localhost:8000 → nginx:80 → app:8000`.
FastAPI is accessible only inside the Compose network. Nginx forwards the frontend,
API polling and PDF downloads, and allows up to 300 seconds for AI keyword extraction and searches that
retry upstream providers. Its upstream DNS refreshes when the app is recreated.
Configuration is packaged from `nginx/default.conf.template`; run `docker compose exec nginx nginx -t`
to validate it. After editing, run `docker compose up --build -d nginx` to rebuild it.
Only the iLearn portal (`http://127.0.0.1:8090`, `http://localhost:8090`) may show the app in a frame.
Set `LITERATURE_FRAME_ANCESTORS` (space-separated origins) to change that, or to an empty value to forbid framing.

Run tests entirely in Docker:

```sh
make docker-test
```

The `literature-data` volume stores new history and PDFs. Existing host data under
`backend/data/` stays on the host; it is not automatically imported into Docker.
Separate `codex-login` and `claude-login` volumes retain official CLI sign-ins.
Treat those volumes as account credentials. Avoid `docker compose down -v` if you
want to retain history and logins.

## Choose API billing or your own CLI subscription

Open the **⚙ 設定** panel to choose appearance, AI connection and model. Choose
**ChatGPT 訂閱登入** to authorize through OpenAI, or **OpenAI API** to enter a key
and click **驗證 API 連線**. A model dropdown appears after connection succeeds.
The browser's selected connection is used for its reports.

Entered API keys are sent to the backend for validation and held in server memory
for at most eight hours. A browser-scoped HttpOnly cookie identifies the connection.
Restarting the service requires re-entering a key. Credentials are excluded from
history and responses. Failed verification preserves the prior server connection;
the form stays unverified until verification succeeds. Expired connection contexts
require reconnecting before a new report can start.

`backend/.env` supplies the initial backend and optional API key. Recreate the app
after changing it with `docker compose up -d`.

| `AI_BACKEND` | Authentication | Model setting |
|---|---|---|
| `openai_api` (default) | `OPENAI_API_KEY`; OpenAI API billing | `MODEL=openai/...` |
| `codex_cli` | Your own ChatGPT login through the official Codex CLI | Optional `CLI_MODEL`; empty uses the CLI default |
| `claude_cli` | Your own Claude subscription login through official Claude Code | Optional `CLI_MODEL`; empty uses the CLI default |

For ChatGPT subscription usage, set `AI_BACKEND=codex_cli`, then sign in:

Open the app's settings panel and click **Connect ChatGPT subscription**. Copy the
one-time code, open the displayed official OpenAI sign-in link, enter the code and
approve access. The app polls the official Codex app-server and shows **Connected
to ChatGPT** when authorization completes. No callback port needs to be published
through Docker or Nginx. Enable device code login in ChatGPT security settings or
workspace permissions if OpenAI requires it. Pending login can be cancelled or
restarted after expiry. This does not validate access to every model; generation
still checks the selected model and your account limits.

The terminal remains available as an alternative:

```sh
docker compose run --rm app codex login --device-auth
docker compose run --rm app codex login status
docker compose up -d
```

For Claude subscription usage, set `AI_BACKEND=claude_cli`, then sign in:

```sh
docker compose run --rm app claude auth login
docker compose run --rm app claude auth status
docker compose up -d
```

Complete the official browser flow yourself. For terminal login, if the container cannot open a
browser, copy its displayed URL into your browser and follow the CLI's code-paste
instructions. The application does not collect or parse tokens or browser cookies.
Login in the container is separate from any host CLI login. Run these commands
from your own terminal; they are interactive.

CLI modes run the published binaries, verify subscription authentication before
reading papers, send prompts through stdin, attach page images for document reading, and disable generation tools. They
ignore `MODEL` and the app's API keys. Set `CLI_MODEL` to a CLI-native model name,
without an `openai/` prefix. `CLI_TIMEOUT_SECONDS` defaults to 600 per stage.
The UI's “CLI available” means the binary is installed; authentication is checked
when generation starts. Subscription access, supported models and usage limits
remain subject to your account. The app does not fall back to API billing.

This integration is intended for this local, single-user app. Each user signs in
with their own account in the unchanged official CLI. It does not provide a
shared Claude or ChatGPT login service. See official [Codex authentication](https://learn.chatgpt.com/docs/auth),
[Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[Claude Code programmatic usage](https://code.claude.com/docs/en/headless),
[Claude Code authentication](https://code.claude.com/docs/en/authentication), and
[Claude Code credential-use requirements](https://code.claude.com/docs/en/legal-and-compliance).

Without Docker, install and sign in to the selected CLI as the same OS user that
runs the backend (`codex login` or `claude auth login`). The backend must have the
CLI on its `PATH`.

## Run for development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js
22.12+ (or a newer supported version), and [pnpm](https://pnpm.io/installation).

With Make and Bash 4.3+ installed, run from the project root:

```sh
make install
# Edit backend/.env to set your API key and model.
make start
```

`make start` runs the backend on **http://localhost:8000** and Vue on
**http://localhost:5173**. Press **Ctrl+C** to stop both services, including their
child processes. If either service exits, the other is stopped as well. Existing
`backend/.env` settings are preserved. Run `make help` to list commands.

Use `make backend` and `make frontend` to run services in separate terminals.
`make serve` builds Vue and runs the app on port 8000; `make test` runs both test
suites. The equivalent commands without Make are below.

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
After connection, the settings panel loads a model dropdown. OpenAI API models
come from the API catalog; ChatGPT models come from Codex's authenticated catalog.
Claude Code offers the official Sonnet, Opus and Haiku aliases after CLI login.
Use **Refresh models** to reload the choices. Each report uses and saves its selected
model; the server validates selections against the current catalog. Catalog entries
may still be subject to account access and generation limits. Leaving the default
selected uses the configured server/CLI model. Searching now requires a working AI connection
(API or CLI subscription) because it extracts keywords before querying paper providers.

Settings includes an **Interface language** switch for English and Traditional Chinese.
The choice is saved in this browser and is independent of the report's output language.

1. Connect AI in settings, then enter a topic or research description (up to 10,000 characters),
   optionally select a subject area and year range, and search. The selected AI extracts
   1–4 short English keyword phrases (at most ten words total); the paper providers search
   these terms rather than the original description. It also infers subject area, year range
   and an explicitly requested result count (1–10). The results show the extracted keywords
   and actual filters, and update the filter controls.
   Each search uses your API credits or CLI allowance, even when provider results are cached.
   Failed extraction returns an error rather than silently searching the original text.
   The original description remains the report topic; history saves it alongside the keywords.
2. Select up to five papers. Choose **Literature review** or **Introduction draft**
   and Traditional Chinese or English. Introduction drafts accept your working
   title, motivation, research question, objectives, context, units, proposed method
   and contribution; missing details are explicitly marked for you to supply.
   Click **Generate review** or **Generate introduction**. Progress appears while
   the background job runs; you can continue searching.
3. Read the thematic synthesis, comparison and evidence-bounded research gaps,
   or the introduction draft. Expand **Evidence checks** to inspect citation IDs,
   supplied page numbers and recorded evidence coverage. These mechanical checks do not prove
   that a claim is supported by its citation or that the prose meets every rule.
   Download Markdown, source evidence JSON (including structured per-paper notes),
   or saved PDFs.
4. Click **Show history** to expand saved searches and reviews, then **Open result**
   to restore one. Reopening a saved review does not generate it again or use API credits.

**Search sources.** Open **+ Filters** and choose any of OpenAlex, Semantic Scholar and arXiv
(at least one; all three by default; the choice is remembered in the browser). The selected sources
are queried in parallel and merged: papers are matched by DOI, arXiv ID or link, ranks are interleaved
because citation counts and scores are not comparable across catalogs, and the merged record keeps the
journal, ISSN, DOI, longest abstract and an arXiv PDF when one exists. Each result shows its catalogs,
journal, DOI and whether an open PDF exists; papers without one are analysed from the abstract only
(and a paper with neither abstract nor PDF is flagged so the model makes no claims about it). If some
sources fail the others' results are still shown with a per-source status; only when every selected
source fails does the search return an error. Open PDFs from publishers or repositories are downloaded
only over public HTTPS (each redirect re-checked, the connection pinned to the verified IP, 20 MB limit).

Search filters apply to every selected source. Leave either
year blank for an open-ended range. Manually changed fields take priority over AI inference
until **Reset filters**, which clears the overrides, subject and years, and resets the result
count to 5. Subsequent searches infer unpinned fields afresh, without retaining old AI filters.
**Last 5 calendar years** sets the current year and previous four years;
you can still select older theoretical or historical sources. The results header records the filters used for the last search. Years use
arXiv submission dates or each catalog's publication year. Subject taxonomies
differ: biology maps to arXiv quantitative biology, and electrical engineering maps
to arXiv eess versus Semantic Scholar's broader Engineering field.

For example, `我想找linux網路相關的推薦一下，2025-2026的` asks the AI for English
keywords such as `Linux` and `networking`, subject `computer_science`, and years
2025–2026. This uses validated structured AI output: the backend validates the proposed
parameters and calls the search providers. It does not require an autonomous tool-use loop.
History stores the effective filters, including result count.

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
- `backend/search_keywords.py`: AI keyword extraction through the selected OpenAI API or official CLI, with validated structured output.
- `backend/paper_search.py`: arXiv queries, Atom parsing, shared request pacing, and caching.
- `backend/search_filters.py`: validated subject/year filters and provider-specific mappings.
- `backend/semantic_search.py`: Semantic Scholar search with its own pacing and cache; keeps papers without an arXiv ID (DOI or publisher link, open-access PDF, venue).
- `backend/openalex_search.py`: OpenAlex works search (journals, proceedings, preprints) with abstract reconstruction, ISSN/venue and open-access PDF extraction.
- `backend/search_catalog.py`: runs the selected sources concurrently, merges duplicates and reports per-source status.
- `backend/paper_urls.py`: public-HTTPS URL checks, DOI normalisation and the DNS-pinned PDF downloader.
- `backend/model_catalog.py`: model discovery with the OpenAI SDK.
- `backend/pdf_reading.py`: bounded PDF download, full-page rendering, batched visual reading and hierarchical evidence reduction.
- `backend/ai_reading.py`: structured text/image calls through the selected API or CLI.
- `backend/literature.py`: collect per-paper evidence digests, then synthesize and write
  through two sequential CrewAI agents or two official CLI calls.
- `backend/review_guidelines.py`: evidence schema, writing requirements, study options
  and mechanical citation checks.
- `backend/ai_backend.py`: server-side backend settings and official CLI adapters.

Python dependencies, the uv lockfile, environment template, and tests also live
in `backend/`. The Vue project and its dependencies live in `frontend/`.

`backend/requirement.txt` provides pinned runtime dependencies exported from
`uv.lock` for pip installation (Python 3.12 or 3.13):

```sh
python -m pip install -r backend/requirement.txt
```

Regenerate it after changing Python dependencies:

```sh
uv export --directory backend --frozen --offline --no-cache --no-dev --no-emit-project --no-hashes --no-annotate --output-file requirement.txt --quiet
```

`POST /api/review` returns **202 Accepted** and a job ID immediately. The frontend
polls `/api/reviews/{id}` every two seconds, with a finite timeout on each request.
API model requests have a 120-second timeout; CLI stages default to 600 seconds.
Connection failures show a **Retry status
check** button; the job keeps running on the backend. The current job ID is stored
in the browser so refreshing reconnects to it. Completed results can always be
opened from history.

SQLite is created automatically at **`backend/data/history.sqlite3`**. To change
the path, set `HISTORY_DB_PATH` in `backend/.env`; relative paths are resolved from
`backend/`. History includes successful searches, selected papers, the configured
model, AI backend, study options, citation checks, review Markdown, and source evidence.
Existing SQLite databases are migrated automatically without removing history.
PDFs downloaded for reviews are stored
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
upstream limit. When arXiv is rate-limited or unavailable, extracted keyword searches
automatically fall back to Semantic Scholar's bulk-search API. The UI labels the
source and returns arXiv-linked papers from the first batch (up to 1,000 records),
ordered by citation count. The search box accepts natural-language research descriptions; it no longer passes through
arXiv field operators. AI extracts plain terms, which arXiv combines with AND.
This is AI-assisted keyword retrieval, not embedding-based similarity search.
PDFs come from arXiv or the open-access link a catalog reports; blocked or missing PDFs use the returned abstracts.
Invalid queries, timeouts, and connectivity failures are reported
separately rather than hidden behind one generic error.

If every selected source is rate-limited, wait for the displayed cooldown. You can also
set optional `SEMANTIC_SCHOLAR_API_KEY` and `OPENALEX_API_KEY` in `backend/.env` and restart the backend
to use dedicated credentials. Request keys through
[Semantic Scholar](https://www.semanticscholar.org/product/api) and [OpenAlex](https://docs.openalex.org/how-to-use-the-api/api-overview).

PDF downloads remain limited to 20 MB. Each PDF page is now rendered to an RGB PNG
(longest edge at most 2,000 pixels, reduced further if a PNG exceeds 4 MB) and submitted with its extracted text to the selected
vision-capable model. OpenAI uses Responses image inputs; Codex uses image attachments;
Claude Code uses image content blocks through stream-JSON input. Subscription modes
retain their CLI authentication and do not fall back to API billing. A model accepting
text-only requests may reject image or structured-output requests; choose a compatible model.

`PDF_BATCH_PAGES` defaults to 4 page entries per call (1–8). Text is bounded to 24,000
characters and 12 MB of PNG data per batch. A dense page is split into 12,000-character text parts with the
same page image; all parts are processed rather than silently truncated. Original PDF
page numbers are preserved across batches. `PDF_MAX_PAGES` defaults to 200 (1–1,000);
exceeding it stops generation explicitly, rather than sampling pages. Both settings
can be changed in `backend/.env` followed by recreating the container.

Each page record includes readability, text/figure/table/equation observations, and
limitations. Scanned pages are sent as images even when text extraction returns nothing.
Large sets of notes are condensed in multiple bounded stages before cross-paper synthesis;
the full per-page text and observations remain in Evidence JSON. Digests can omit details,
and passing page/citation checks does not establish semantic support for a claim.
The report shows page counts, batches and expandable page reading details. All-pages
coverage means all pages were submitted and accounted for, not that all visual details
were recognized accurately. Small labels, complex tables and formulas still need review.

Only download/opening failures fall back to labelled abstracts. A failed model call,
missing page result or invalid citation stops the job. Page images are transient and
are not saved in history; the original PDF remains cached. Each batch and reduction
uses AI allowance, so long documents take longer and cost more. API reading calls time
out after 120 seconds each; CLI calls use `CLI_TIMEOUT_SECONDS`. There is no automatic
resume of a partially read document after failure. The Compose shutdown grace period
is 35 minutes; a longer active job may be interrupted during container recreation.

Standalone OCR, embeddings/RAG, SCI-index verification,
Zotero, and BibTeX export are outside this minimal version.
arXiv includes preprints, and generated claims still need human review. Generating
a review sends paper text and rendered page images to the model provider and uses API credits or your own
CLI plan allowance according to the configured backend. Closing
the tab does not cancel an already-running backend review.

## Test

```sh
uv run --directory backend pytest
pnpm --dir frontend test    # vue-tsc type check, then Vitest
pnpm --dir frontend build   # type check, then production build
```

Tests use local PDFs and mocked services; they do not need API keys or credits.

References: [Vue](https://vuejs.org/guide/quick-start.html),
[FastAPI](https://fastapi.tiangolo.com/),
[OpenAI model listing](https://developers.openai.com/api/reference/resources/models),
[CrewAI tasks](https://docs.crewai.com/en/concepts/tasks), and
[arXiv search](https://info.arxiv.org/help/api/user-manual.html).
