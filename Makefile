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
	uv run python -m stock.data.backfill --start $(START) --end $(END)
