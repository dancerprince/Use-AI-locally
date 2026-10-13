.PHONY: setup dev backend frontend test lint format build run clean package install-local binary

BACKEND := backend
FRONTEND := frontend

setup:            ## Install all dependencies
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && npm ci

backend:          ## Run API with reload on :8000
	cd $(BACKEND) && uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000

frontend:         ## Run Vite dev server on :5173 (proxies /api)
	cd $(FRONTEND) && npm run dev

dev:              ## Run backend + frontend together
	$(MAKE) -j2 backend frontend

test:             ## Run all tests
	cd $(BACKEND) && uv run pytest -q
	cd $(FRONTEND) && npm test

lint:             ## Lint + type-check everything
	cd $(BACKEND) && uv run ruff check app tests && uv run ruff format --check app tests && uv run mypy app
	cd $(FRONTEND) && npm run lint && npm run typecheck && npm run format:check

format:
	cd $(BACKEND) && uv run ruff check --fix app tests && uv run ruff format app tests
	cd $(FRONTEND) && npm run format

build:            ## Build the UI (served by the backend)
	cd $(FRONTEND) && npm run build
	rm -rf $(BACKEND)/app/static   # stale bundled UI would shadow frontend/dist

run: build        ## Production-style single process on :8000
	cd $(BACKEND) && uv run python -m app.main

package:          ## Build distributable wheel + sdist with the UI bundled inside
	python3 scripts/build_release.py

install-local: package  ## Install the built wheel as the `offline-ai` command
	uv tool install --force $(BACKEND)/dist/*.whl

binary:           ## Standalone executable via PyInstaller (dist/offline-ai/)
	cd $(FRONTEND) && npm run build:bundle
	uv run --project $(BACKEND) --with pyinstaller pyinstaller --noconfirm packaging/offline-ai.spec

clean:
	rm -rf $(FRONTEND)/dist $(BACKEND)/app/static $(BACKEND)/dist build dist $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
