.PHONY: install test lint format check safe-push serve scan backtest migrate seed-demo migration migration-check db-history

install:        ## install runtime + dev deps
	pip install -r requirements.txt && pip install -e .

check:          ## the full quality gate (format-check + lint + types + tests + migration drift)
	ruff format --check src tests
	ruff check src tests
	MYPYPATH=src python -m mypy --strict src/momentum
	PYTHONPATH=src python -m pytest tests -q
	@tmp=$$(mktemp -u --suffix=.db); DATABASE_URL="sqlite:///$$tmp" PYTHONPATH=src alembic upgrade head >/dev/null && DATABASE_URL="sqlite:///$$tmp" PYTHONPATH=src alembic check; rm -f "$$tmp"

safe-push:      ## gate + rebase + re-gate + push (refuses a red branch)
	bash scripts/safe-push.sh

migrate:        ## apply all database migrations
	alembic upgrade head

seed-demo:      ## seed a demo dataset for the UI (50 trades, 100 signals, snapshots, regimes)
	python scripts/seed_demo.py

migration:      ## autogenerate a migration:  make migration m="add X"
	alembic revision --autogenerate -m "$(m)"

migration-check: ## CI guard: fail if models drift from migrations
	alembic check

db-history:     ## show the migration timeline
	alembic history --verbose

test:           ## run the test suite
	pytest

lint:           ## static checks
	ruff check src tests && python -m mypy src

format:         ## auto-format
	ruff format src tests

serve:          ## launch the FastAPI service
	uvicorn momentum.api.app:create_app --factory --reload

scan:           ## run the end-of-day scan pipeline (research)
	mrp scan

backtest:       ## run a backtest from config
	mrp backtest
