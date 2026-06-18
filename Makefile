.PHONY: install test lint format serve scan backtest

install:        ## install runtime + dev deps
	pip install -r requirements.txt && pip install -e .

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
