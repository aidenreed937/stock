.PHONY: help install lint format test check run backfill baseline migrate-data backfill-accept

help:
	@echo "Available commands:"
	@echo "  make install  - Install dependencies and pre-commit hooks using uv"
	@echo "  make lint     - Run ruff check and mypy"
	@echo "  make format   - Run ruff format and fix"
	@echo "  make test     - Run pytest with coverage"
	@echo "  make check    - Run format, lint, and test (recommended before commit)"
	@echo "  make run      - Run the main application"
	@echo "  make backfill - Backfill historical data (e.g., make backfill START=2026-08-01 END=2026-08-12)"
	@echo "  make baseline - Generate immutable data inventory"
	@echo "  make migrate-data [APPLY=1] - Preview/apply local dedup migration"
	@echo "  make backfill-accept ENDPOINT=stock_daily_bar - Run fail-closed backfill acceptance"
	@echo "  make probe    - Run global data source connectivity probe"
	@echo "  make validate - Run offline data quality validator"
	@echo "  make filter-universe - Generate filtered stock universe based on liquidity"
	@echo "  make backfill-fundamental - Backfill fundamentals from lixinger based on universe"

install:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run mypy src
	uv run python scripts/lint_class_size.py

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

check: format lint test

run:
	uv run python -m stock.main

backfill:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock.data.backfill --start $(START) --end $(END) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(ENDPOINT),--endpoint $(ENDPOINT)) $(if $(SYMBOL),--symbol $(SYMBOL)) $(if $(FORCE_REFRESH),--force-refresh)

baseline:
	uv run python -m stock.data.audit.baseline --root $(or $(ROOT),data) --output $(or $(OUTPUT),data/audit/baseline.json)

migrate-data:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock.data.ops.migration --root $(or $(ROOT),data) $(if $(APPLY),--apply) $(if $(REPAIR_LINEAGE),--repair-lineage)

backfill-accept:
	uv run python -m stock.data.audit.backfill_acceptance --root $(or $(ROOT),data/curated) --endpoint $(ENDPOINT) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(START),--start $(START)) $(if $(END),--end $(END))

probe:
	uv run python -m stock.data.ops.probe

validate:
	uv run python -m stock.data.quality.gate
	uv run python -m stock.data.validator --endpoint $(or $(ENDPOINT),stock_daily_bar) --strict

audit:
	uv run python -m stock.cli.audit --type $(or $(TYPE),master) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(DATE),--date $(DATE))

master-audit:
	uv run python -m stock.cli.audit --type master

filter-universe:
	uv run python -m stock.data.domain.universe

backfill-fundamental:
	uv run python -m stock.data.backfill --start $(START) --end $(END) --data-source lixinger --endpoint company_fundamental --universe $(or $(UNIVERSE),watchlist)

backfill-fs:
	uv run python -m stock.data.backfill --start $(START) --end $(END) --data-source lixinger --endpoint fs_non_financial --universe $(or $(UNIVERSE),watchlist)

backfill-pledge:
	uv run python -m stock.data.backfill --start $(START) --end $(END) --data-source lixinger --endpoint pledge_info --universe $(or $(UNIVERSE),watchlist)

monitor:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python scripts/monitor_resources.py $(if $(WATCH),--watch) $(if $(INTERVAL),--interval $(INTERVAL))
