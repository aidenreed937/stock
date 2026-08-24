.PHONY: help install lint lint-rust format test test-rust-plugins check run scan realtime market-aggregate market-temperature industry-structure investor-brief quant-brief multi-date screen-stocks report-consistency market-cycle-review artifact-index cleanup-analytics backfill baseline migrate-data migrate-curated cleanup-data backfill-accept repair-stock-daily-bar build-plugins

export UV_CACHE_DIR ?= .uv_cache
export UV_PYTHON_INSTALL_DIR ?= .uv_python
export PRE_COMMIT_HOME ?= $(CURDIR)/.pre_commit_cache
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
	@echo "  make multi-date - Generate and publish four analytics artifacts for multiple trade dates"
	@echo "  make screen-stocks - Generate stock screening artifacts under data/analytics"
	@echo "  make report-consistency - Validate report consistency across analytics artifacts"
	@echo "  make market-cycle-review - Generate cross-cycle market review from analytics artifacts"
	@echo "  make artifact-index ROOT=data/analytics/market_temperature - Rebuild analytics run index"
	@echo "  make cleanup-analytics ROOT=data/analytics/market_temperature [APPLY=1] [RUN_CLASS=experiment] - Preview/clean old runs"
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
	uv run maturin develop --release --manifest-path crates/stock_plugins/Cargo.toml

test-rust-plugins:
	cargo test --manifest-path crates/stock_plugins/Cargo.toml --no-default-features

install:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run mypy src
	uv run python scripts/lint_class_size.py
	uv run python scripts/lint_analytics_boundaries.py

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
	uv run python -m stock_cli.realtime $(if $(WATCH),--watch) $(if $(INTERVAL),--interval $(INTERVAL)) $(if $(FORMAT),--format $(FORMAT)) $(if $(RECORD),--record) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR)) $(if $(RAW_ROOT),--raw-root $(RAW_ROOT))

market-aggregate:
	uv run python -m stock_cli.market_aggregate $(if $(WATCH),--watch) $(if $(INTERVAL),--interval $(INTERVAL)) $(if $(FORMAT),--format $(FORMAT)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS)) $(if $(NO_LATEST),--no-latest) $(if $(RECORD),--record) $(if $(RAW_ROOT),--raw-root $(RAW_ROOT)) $(if $(BATCH_SIZE),--batch-size $(BATCH_SIZE),$(if $(PAGE_SIZE),--batch-size $(PAGE_SIZE))) $(if $(STRONG_MOVE_PCT),--strong-move-pct $(STRONG_MOVE_PCT)) $(if $(SKIP_INDUSTRY),--skip-industry)

sync:
	uv run python -m stock_cli.sync --source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(DATE),--date $(DATE)) $(if $(or $(ENDPOINT),$(ENDPOINTS)),--endpoints $(or $(ENDPOINT),$(ENDPOINTS))) $(if $(FORCE),--force) $(if $(NO_AUDIT),--no-audit) $(if $(WORKERS),--max-workers $(WORKERS))

backfill:
	uv run python -m stock_cli.backfill $(if $(START),--start $(START)) $(if $(END),--end $(END)) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(ENDPOINT),--endpoint $(ENDPOINT)) $(if $(SYMBOL),--symbol $(SYMBOL)) $(if $(FORCE_REFRESH),--force-refresh) $(if $(WORKERS),--max-workers $(WORKERS))


baseline:
	uv run python -m stock_data.governance.audit.baseline --root $(or $(ROOT),data) --output $(or $(OUTPUT),data/audit/baseline.json)

migrate-data:
	uv run python -m stock_data.governance.ops.migration --root $(or $(ROOT),data) $(if $(APPLY),--apply) $(if $(REPAIR_LINEAGE),--repair-lineage)

migrate-curated:
	uv run python scripts/migrate_curated_schema_v2.py --root $(or $(CURATED_ROOT),data/curated) $(if $(APPLY),--apply)

cleanup-data:
	uv run python -m stock_data.governance.ops.cleanup_artifacts --root $(or $(ROOT),data) --older-than-days $(or $(OLDER_THAN_DAYS),7) $(if $(filter 1 true yes,$(APPLY)),--apply)

backfill-accept:
	uv run python -m stock_data.governance.audit.backfill_acceptance --root $(or $(ROOT),data/curated) --raw-root $(or $(RAW_ROOT),data/raw) --endpoint $(ENDPOINT) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(START),--start $(START)) $(if $(END),--end $(END))

repair-stock-daily-bar:
	uv run python -m stock_data.governance.ops.rebuild_stock_daily_bar \
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
	uv run python -m stock_data.governance.quality.gate
	uv run python -m stock_data.governance.validator --endpoint $(or $(ENDPOINT),stock_daily_bar) --strict

audit:
	uv run python -m stock_cli.audit --type $(or $(TYPE),master) --data-source $(or $(SOURCE),$(DATA_SOURCE),tushare) $(if $(DATE),--date $(DATE)) $(if $(START),--start $(START)) $(if $(END),--end $(END)) $(if $(DOMAIN),--domain $(DOMAIN)) $(if $(FREQ),--frequency $(FREQ))

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
	uv run python scripts/monitor_resources.py $(if $(WATCH),--watch) $(if $(INTERVAL),--interval $(INTERVAL))

scan:
	uv run python -m stock_cli.market_temperature $(if $(DATE),--date $(DATE)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS))
	uv run python -m stock_cli.industry_structure $(if $(DATE),--date $(DATE)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS))
	uv run python -m stock_cli.investor_brief $(if $(DATE),--date $(DATE)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS))
	uv run python -m stock_cli.quant_brief $(if $(DATE),--date $(DATE)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS))

features-build:
	uv run python -m stock_cli.features build $(if $(TARGET),--target $(TARGET)) $(if $(START),--start $(START)) $(if $(END),--end $(END)) $(if $(OVERWRITE),--overwrite) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR))

market-temperature:
	uv run python -m stock_cli.market_temperature $(if $(DATE),--date $(DATE)) $(if $(COMPARE_DATE),--compare-date $(COMPARE_DATE)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS)) $(if $(NO_LATEST),--no-latest) $(if $(SKIP_METRICS),--skip-metrics)

industry-structure:
	uv run python -m stock_cli.industry_structure $(if $(DATE),--date $(DATE)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS)) $(if $(NO_LATEST),--no-latest)

investor-brief:
	uv run python -m stock_cli.investor_brief $(if $(DATE),--date $(DATE)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS)) $(if $(NO_LATEST),--no-latest)

quant-brief:
	uv run python -m stock_cli.quant_brief $(if $(DATE),--date $(DATE)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS)) $(if $(NO_LATEST),--no-latest)

multi-date:
	uv run python -m stock_cli.multi_date $(if $(DATES),--dates $(DATES),$(if $(LAST_N),--last-n $(LAST_N),$(if $(START),--start $(START)))) $(if $(END),--end $(END)) $(if $(REFRESH_MART),--refresh-mart) $(if $(MART_START),--mart-start $(MART_START)) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR)) $(if $(ANALYTICS_ROOT),--analytics-root $(ANALYTICS_ROOT)) $(if $(PUBLISH_DATE),--publish-date $(PUBLISH_DATE)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS)) $(if $(SKIP_METRICS),--skip-metrics) $(if $(NO_PUBLISH_LATEST),--no-publish-latest) $(if $(DRY_RUN),--dry-run)

screen-stocks:
	uv run python -m stock_cli.stock_screen $(if $(DATE),--as-of $(DATE)) $(if $(CONFIG),--config $(CONFIG)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS)) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR)) $(if $(SYMBOLS),--symbols $(SYMBOLS)) $(if $(NO_LATEST),--no-latest)

artifact-index:
	uv run python -m stock_cli.artifact_ops index --root $(ROOT)

cleanup-analytics:
	uv run python -m stock_cli.artifact_ops cleanup --root $(ROOT) $(if $(LATEST_ROOT),--latest-root $(LATEST_ROOT)) $(if $(OLDER_THAN_DAYS),--older-than-days $(OLDER_THAN_DAYS)) $(if $(RUN_CLASS),--run-class $(RUN_CLASS)) $(if $(NO_KEEP_LATEST),--no-keep-latest) $(if $(filter 1 true yes,$(APPLY)),--apply)

report-consistency:
	uv run python scripts/report_consistency.py $(if $(DATE),--date $(DATE)) $(if $(START),--start $(START)) $(if $(END),--end $(END)) $(if $(ANALYTICS_ROOT),--analytics-root $(ANALYTICS_ROOT)) $(if $(OUTPUT),--output $(OUTPUT))

market-cycle-review:
	uv run python scripts/market_cycle_review.py --start $(START) --end $(END) $(if $(ANALYTICS_ROOT),--analytics-root $(ANALYTICS_ROOT)) $(if $(OUTPUT_ROOT),--output-root $(OUTPUT_ROOT)) $(if $(NO_LATEST),--no-latest) $(if $(SKIP_CONSISTENCY),--skip-consistency)

diagnose:
	uv run python -m stock_cli.diagnose --symbol $(SYMBOL) $(if $(DATE),--as-of $(DATE)) $(if $(FORMAT),--format $(FORMAT)) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR))

industry-diagnose:
	uv run python -m stock_cli.industry_diagnose --industry $(INDUSTRY) $(if $(DATE),--as-of $(DATE)) $(if $(FORMAT),--format $(FORMAT)) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR))

scan-watchlist:
	uv run python -m stock_cli.scan_watchlist $(if $(DATE),--as-of $(DATE)) $(if $(FORMAT),--format $(FORMAT)) $(if $(CONFIG),--config $(CONFIG)) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR)) $(if $(SAVE),--save)

daily-review:
	uv run python -m stock_cli.daily_review $(if $(DATE),--as-of $(DATE)) $(if $(OUTPUT),--output-dir $(OUTPUT))

thesis-review:
	uv run python -m stock_cli.thesis_review --symbol $(SYMBOL) $(if $(THESIS_DATE),--thesis-date $(THESIS_DATE)) $(if $(DATE),--as-of $(DATE)) $(if $(FORMAT),--format $(FORMAT)) $(if $(STORAGE_DIR),--storage-dir $(STORAGE_DIR)) $(if $(NO_SAVE),--no-save)
