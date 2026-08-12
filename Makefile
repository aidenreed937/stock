.PHONY: help install lint format test check run backfill

help:
	@echo "Available commands:"
	@echo "  make install  - Install dependencies and pre-commit hooks using uv"
	@echo "  make lint     - Run ruff check and mypy"
	@echo "  make format   - Run ruff format and fix"
	@echo "  make test     - Run pytest with coverage"
	@echo "  make check    - Run format, lint, and test (recommended before commit)"
	@echo "  make run      - Run the main application"
	@echo "  make backfill - Backfill historical data (e.g., make backfill START=2026-08-01 END=2026-08-12)"
	@echo "  make probe    - Run global data source connectivity probe"
	@echo "  make validate - Run offline data quality validator"

install:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run mypy src

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

check: format lint test

run:
	uv run python -m stock.main

backfill:
	uv run python -m stock.data.backfill --start $(START) --end $(END) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare)

probe:
	uv run python -m stock.data.probe

validate:
	uv run python -m stock.data.validator --endpoint $(or $(ENDPOINT),daily)

audit:
	uv run python -m stock.data.audit $(if $(START),--start $(START)) $(if $(END),--end $(END)) $(if $(DATE),--date $(DATE)) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare)
