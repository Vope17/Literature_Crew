SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
PNPM ?= pnpm

.PHONY: help env install start backend frontend build serve test

help:
	@printf '%s\n' \
	  'make install   Install Python and frontend dependencies; create backend/.env if missing' \
	  'make start     Start backend (:8000) and frontend (:5173); Ctrl+C stops both' \
	  'make backend   Start only the backend with reload' \
	  'make frontend  Start only the Vue development server' \
	  'make build     Build the frontend' \
	  'make serve     Build Vue and serve the app on :8000' \
	  'make test      Run backend and frontend tests'

env:
	@umask 077; if [ ! -e backend/.env ]; then cp backend/.env.example backend/.env; fi

install: env
	$(UV) sync --directory backend
	$(PNPM) --dir frontend install --frozen-lockfile

start: env
	@UV="$(UV)" PNPM="$(PNPM)" bash scripts/start-services.sh

backend: env
	$(UV) run --directory backend uvicorn app:app --reload --host 127.0.0.1 --port 8000

frontend:
	$(PNPM) --dir frontend dev --host 127.0.0.1 --port 5173 --strictPort

build:
	$(PNPM) --dir frontend build

serve: env build
	$(UV) run --directory backend uvicorn app:app --host 127.0.0.1 --port 8000

test:
	$(UV) run --directory backend pytest
	$(PNPM) --dir frontend test
