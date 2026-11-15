FROM node:22-bookworm-slim AS frontend-base
WORKDIR /app/frontend
RUN npm install --global pnpm@10
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./

FROM frontend-base AS frontend-test
CMD ["pnpm", "test"]

FROM frontend-base AS frontend-build
RUN pnpm build

FROM nginx:stable-alpine AS proxy
# Rendered to /etc/nginx/conf.d/default.conf by the image's entrypoint (envsubst of defined variables only).
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
ENV LITERATURE_FRAME_ANCESTORS=

FROM python:3.12-slim-bookworm AS backend-base
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /usr/local/bin/
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-install-project
COPY backend/ ./

FROM backend-base AS backend-test
CMD ["uv", "run", "--locked", "pytest"]

FROM backend-base AS runtime
# Run the official CLIs unchanged. Each user signs in through their own CLI flow.
COPY --from=frontend-base /usr/local/ /usr/local/
RUN npm install --global @openai/codex @anthropic-ai/claude-code \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/backend/data /home/app/.codex /home/app/.claude \
    && chown -R app:app /app/backend/data /home/app
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
ENV HOME=/home/app \
    CLAUDE_CONFIG_DIR=/home/app/.claude \
    AI_BACKEND=openai_api \
    MODEL=openai/gpt-4o-mini
USER app
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
