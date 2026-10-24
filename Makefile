# TRACELESS — one-command workflows. Works in Git Bash / any POSIX shell.
PY := backend/.venv/Scripts/python
ifeq ($(wildcard $(PY)),)
PY := backend/.venv/bin/python
endif
export PYTHONUTF8 := 1

.PHONY: setup models web dev demo test lint bench bench-quick iris clean-sessions

setup: ## install everything (backend venv, model weights, web build)
	cd backend && uv sync
	$(PY) scripts/fetch_models.py
	cd web && pnpm install && pnpm build

models:
	$(PY) scripts/fetch_models.py

web:
	cd web && pnpm build

demo: web ## serve API + web app on :8000 (open http://localhost:8000)
	cd backend && .venv/Scripts/python -m traceless.server || .venv/bin/python -m traceless.server

dev: ## backend only; run `cd web && pnpm dev` alongside for hot reload
	cd backend && .venv/Scripts/python -m traceless.server

test:
	cd backend && .venv/Scripts/python -m pytest -q

test-golden: ## slow: full pipeline on every fixture photo
	cd backend && .venv/Scripts/python -m pytest -q -m golden

lint:
	cd backend && .venv/Scripts/python -m ruff check traceless tests
	cd web && pnpm typecheck

bench: ## benchmark on Im2GPS3k subset -> bench/results/latest.json (+ README tables)
	$(PY) bench/run_bench.py --n 300 --clue-rich 100

bench-quick:
	$(PY) bench/run_bench.py --n 40 --clue-rich 20

iris: ## measure the eye-reflection readability threshold
	$(PY) bench/iris_threshold.py

clean-sessions: ## delete every uploaded photo and derived file
	rm -rf sessions
