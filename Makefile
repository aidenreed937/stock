.PHONY: help install lint lint-rust format test test-rust-plugins check run scan realtime market-aggregate market-temperature industry-structure investor-brief quant-brief screen-stocks report-consistency market-cycle-review backfill baseline migrate-data migrate-curated cleanup-data backfill-accept repair-stock-daily-bar build-plugins

export UV_CACHE_DIR ?= .uv_cache
export UV_PYTHON_INSTALL_DIR ?= .uv_python
export POLARS_MAX_THREADS ?= 4

help:
	@echo "Available commands:"
	@echo "  make install  - Install dependencies and pre-commit hooks using uv"
	@echo "  make build-plugins - Build Rust Polars extension plugins using maturin"
	@echo "  make lint-rust - Run Rust format and Clippy checks"
	@echo "  make test-rust-plugins - Run Rust plugin unit tests without Python extension linking"
	@echo "  make lint     - Run ruff check and mypy"
	@echo "  make format   - Run ruff format and fix"
	@echo "  make test     - Run pytest with coverage"
	@echo "  make check    - Run format, lint, and test (recommended before commit)"
	@echo "  make run      - Run the main application"
	@echo "  make scan     - Run 4-layer market scan (e.g., make scan [DATE=YYYY-MM-DD])"
	@echo "  make realtime - Run Tencent core watchlist realtime monitor (e.g., make realtime WATCH=1)"
	@echo "  make market-aggregate - Run low-frequency A-share full-market aggregate monitor"
	@echo "  make market-temperature - Generate market temperature artifacts under data/analytics"
	@echo "  make industry-structure - Generate SW industry structure artifacts under data/analytics"
	@echo "  make screen-stocks - Generate stock screening artifacts under data/analytics"
	@echo "  make report-consistency - Validate report consistency across analytics artifacts"
	@echo "  make market-cycle-review - Generate cross-cycle market review from analytics artifacts"
	@echo "  make backfill - Backfill historical data (e.g., make backfill START=2026-08-01 END=2026-08-12)"
	@echo "  make baseline - Generate immutable data inventory"
	@echo "  make migrate-data [APPLY=1] - Preview/apply local dedup migration"
	@echo "  make migrate-curated [APPLY=1] - Preview/apply Curated Schema v2 migration"
	@echo "  make cleanup-data [APPLY=1] [OLDER_THAN_DAYS=7] - Preview/clean stale Parquet artifacts"
	@echo "  make backfill-accept ENDPOINT=stock_daily_bar - Run fail-closed backfill acceptance"
	@echo "  make repair-stock-daily-bar [APPLY=1] - Replay stock_daily_bar RAW into staged Curated"
	@echo "  make probe    - Run global data source connectivity probe"
	@echo "  make validate - Run offline data quality validator"
	@echo "  make filter-universe - Generate filtered stock universe based on liquidity"
	@echo "  make backfill-fundamental - Backfill fundamentals from lixinger based on universe"

build-plugins:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run maturin develop --release --manifest-path crates/stock_plugins/Cargo.toml

test-rust-plugins:
	cargo test --manifest-path crates/stock_plugins/Cargo.toml --no-default-features

install:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run mypy src
	uv run python scripts/lint_class_size.py

lint-rust:
	cargo fmt --all -- --check
	cargo clippy --manifest-path crates/stock_plugins/Cargo.toml --all-targets --all-features -- -D warnings

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	$(if $(TEST_PATH),uv run pytest $(TEST_PATH) --no-cov,uv run pytest)

check: format lint lint-rust test test-rust-plugins

run:
	uv run python -m stock_cli.main

realtime:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.realtime $(if $(WATCH),--watch) $(if $(INTERVAL),--interval $(INTERVAL)) $(if $(FORMAT),--format $(FORMAT)) $(if $(RECORD),--record) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR)) $(if $(RAW_ROOT),--raw-root $(RAW_ROOT))

market-aggregate:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.market_aggregate $(if $(WATCH),--watch) $(if $(INTERVAL),--interval $(INTERVAL)) $(if $(FORMAT),--format $(FORMAT)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(NO_LATEST),--no-latest) $(if $(RECORD),--record) $(if $(RAW_ROOT),--raw-root $(RAW_ROOT)) $(if $(BATCH_SIZE),--batch-size $(BATCH_SIZE),$(if $(PAGE_SIZE),--batch-size $(PAGE_SIZE))) $(if $(STRONG_MOVE_PCT),--strong-move-pct $(STRONG_MOVE_PCT))

sync:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.sync --source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(DATE),--date $(DATE)) $(if $(or $(ENDPOINT),$(ENDPOINTS)),--endpoints $(or $(ENDPOINT),$(ENDPOINTS))) $(if $(FORCE),--force) $(if $(NO_AUDIT),--no-audit) $(if $(WORKERS),--max-workers $(WORKERS))

backfill:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.backfill $(if $(START),--start $(START)) $(if $(END),--end $(END)) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(ENDPOINT),--endpoint $(ENDPOINT)) $(if $(SYMBOL),--symbol $(SYMBOL)) $(if $(FORCE_REFRESH),--force-refresh) $(if $(WORKERS),--max-workers $(WORKERS))


baseline:
	uv run python -m stock_data.governance.audit.baseline --root $(or $(ROOT),data) --output $(or $(OUTPUT),data/audit/baseline.json)

migrate-data:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_data.governance.ops.migration --root $(or $(ROOT),data) $(if $(APPLY),--apply) $(if $(REPAIR_LINEAGE),--repair-lineage)

migrate-curated:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python scripts/migrate_curated_schema_v2.py --root $(or $(CURATED_ROOT),data/curated) $(if $(APPLY),--apply)

cleanup-data:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_data.governance.ops.cleanup_artifacts --root $(or $(ROOT),data) --older-than-days $(or $(OLDER_THAN_DAYS),7) $(if $(filter 1 true yes,$(APPLY)),--apply)

backfill-accept:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_data.governance.audit.backfill_acceptance --root $(or $(ROOT),data/curated) --raw-root $(or $(RAW_ROOT),data/raw) --endpoint $(ENDPOINT) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(START),--start $(START)) $(if $(END),--end $(END))

repair-stock-daily-bar:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_data.governance.ops.rebuild_stock_daily_bar \
		$(if $(RAW_ROOT),--raw-root $(RAW_ROOT)) \
		$(if $(CURATED_ROOT),--curated-root $(CURATED_ROOT)) \
		$(if $(STOCK_BASIC),--stock-basic $(STOCK_BASIC)) \
		$(if $(TEMP_ROOT),--temp-root $(TEMP_ROOT)) \
		$(if $(QUARANTINE_ROOT),--quarantine-root $(QUARANTINE_ROOT)) \
		$(if $(BACKUP_ROOT),--backup-root $(BACKUP_ROOT)) \
		$(if $(filter 1 true yes,$(APPLY)),--apply)

probe:
	uv run python -m stock_data.governance.ops.probe

validate:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_data.governance.quality.gate
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_data.governance.validator --endpoint $(or $(ENDPOINT),stock_daily_bar) --strict

audit:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.audit --type $(or $(TYPE),master) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(DATE),--date $(DATE)) $(if $(START),--start $(START)) $(if $(END),--end $(END)) $(if $(DOMAIN),--domain $(DOMAIN)) $(if $(FREQ),--frequency $(FREQ))

master-audit:
	uv run python -m stock_cli.audit --type master

filter-universe:
	uv run python -m stock_data.governance.domain.universe

backfill-fundamental:
	uv run python -m stock_cli.backfill --start $(START) --end $(END) --data-source lixinger --endpoint company_fundamental --universe $(or $(UNIVERSE),watchlist)

backfill-fs:
	uv run python -m stock_cli.backfill --start $(START) --end $(END) --data-source lixinger --endpoint fs_non_financial --universe $(or $(UNIVERSE),watchlist)

backfill-pledge:
	uv run python -m stock_cli.backfill --start $(START) --end $(END) --data-source lixinger --endpoint pledge_info --universe $(or $(UNIVERSE),watchlist)

monitor:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python scripts/monitor_resources.py $(if $(WATCH),--watch) $(if $(INTERVAL),--interval $(INTERVAL))

scan:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.market_temperature $(if $(DATE),--date $(DATE))
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.industry_structure $(if $(DATE),--date $(DATE))
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.investor_brief $(if $(DATE),--date $(DATE))
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.quant_brief $(if $(DATE),--date $(DATE))

features-build:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.features build $(if $(TARGET),--target $(TARGET)) $(if $(START),--start $(START)) $(if $(END),--end $(END)) $(if $(OVERWRITE),--overwrite) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR))

market-temperature:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.market_temperature $(if $(DATE),--date $(DATE)) $(if $(COMPARE_DATE),--compare-date $(COMPARE_DATE)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(NO_LATEST),--no-latest) $(if $(SKIP_METRICS),--skip-metrics)

industry-structure:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.industry_structure $(if $(DATE),--date $(DATE)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(NO_LATEST),--no-latest)

investor-brief:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.investor_brief $(if $(DATE),--date $(DATE)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(NO_LATEST),--no-latest)

quant-brief:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.quant_brief $(if $(DATE),--date $(DATE)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(NO_LATEST),--no-latest)

screen-stocks:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.stock_screen $(if $(DATE),--as-of $(DATE)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR)) $(if $(SYMBOLS),--symbols $(SYMBOLS)) $(if $(NO_LATEST),--no-latest)

report-consistency:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python scripts/report_consistency.py $(if $(DATE),--date $(DATE)) $(if $(START),--start $(START)) $(if $(END),--end $(END)) $(if $(ANALYTICS_ROOT),--analytics-root $(ANALYTICS_ROOT)) $(if $(OUTPUT),--output $(OUTPUT))

market-cycle-review:
	UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python scripts/market_cycle_review.py --start $(START) --end $(END) $(if $(ANALYTICS_ROOT),--analytics-root $(ANALYTICS_ROOT)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(NO_LATEST),--no-latest) $(if $(SKIP_CONSISTENCY),--skip-consistency)
