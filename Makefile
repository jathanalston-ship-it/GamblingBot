.PHONY: install test lint format serve scan backtest migrate migration migration-check db-history

install:        ## install runtime + dev deps
	pip install -r requirements.txt && pip install -e .

migrate:        ## apply all database migrations
	alembic upgrade head

migration:      ## autogenerate a migration:  make migration m="add X"
	alembic revision --autogenerate -m "$(m)"

migration-check: ## CI guard: fail if models drift from migrations
	alembic check

db-history:     ## show the migration timeline
	alembic history --verbose

test:           ## run the test suite
	pytest

lint:           ## static checks
	ruff check src tests && mypy src

format:         ## auto-format
	ruff format src tests

serve:          ## launch the FastAPI service
	uvicorn momentum.api.app:create_app --factory --reload

scan:           ## run the end-of-day scan pipeline (research)
	mrp scan

backtest:       ## run a backtest from config
	mrp backtest
