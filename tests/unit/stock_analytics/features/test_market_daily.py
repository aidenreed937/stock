"""MarketDailyBuilder 单元测试。"""

from datetime import date, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from stock_analytics.features.builders.market_daily import MarketDailyBuilder
from stock_analytics.features.builders.market_daily_ops import build_breadth_and_turnover
from stock_analytics.features.store import FeatureStore
from stock_analytics.metrics import MetricContext, MetricEngine
from stock_analytics.metrics.calculators.breadth import _calculate_breadth_columns
from stock_core.contracts import MarketDataCatalog
from stock_data.catalog import DataCatalog


def _prepare_mock_catalog_data(storage_dir: Path) -> None:
    # 1. stock_daily_bar
    bar_dir = storage_dir / "tushare/market=CN/stock_daily_bar/year=2026/month=08"
    bar_dir.mkdir(parents=True, exist_ok=True)
    bars_data = []
    for d in range(1, 15):
        t_date = date(2026, 8, d)
        bars_data.extend(
            [
                {
                    "symbol": "000001.SZ",
                    "trade_date": t_date,
                    "close": 10.0 + d * 0.1,
                    "amount": 100000.0,
                    "schema_version": "v2",
                    "market": "CN",
                },
                {
                    "symbol": "000002.SZ",
                    "trade_date": t_date,
                    "close": 20.0 - d * 0.05,
                    "amount": 200000.0,
                    "schema_version": "v2",
                    "market": "CN",
                },
            ]
        )
    pl.DataFrame(bars_data).write_parquet(bar_dir / "data.parquet")

    # 2. margin
    margin_dir = storage_dir / "tushare/market=CN/margin/year=2026/month=08"
    margin_dir.mkdir(parents=True, exist_ok=True)
    margin_data = []
    for d in range(1, 15):
        for ex in ("SSE", "SZSE", "BSE"):
            margin_data.append(
                {
                    "trade_date": date(2026, 8, d),
                    "exchange_id": ex,
                    "rzrqye": 500000.0,
                    "rzmre": 10000.0,
                    "schema_version": "v2",
                    "market": "CN",
                }
            )
    pl.DataFrame(margin_data).write_parquet(margin_dir / "data.parquet")

    # 3. daily_basic
    basic_dir = storage_dir / "tushare/market=CN/daily_basic/year=2026/month=08"
    basic_dir.mkdir(parents=True, exist_ok=True)
    basic_data = []
    for d in range(1, 15):
        t_date = date(2026, 8, d)
        basic_data.extend(
            [
                {
                    "symbol": "000001.SZ",
                    "trade_date": t_date,
                    "turnover_rate_f": 2.5,
                    "circ_mv": 1_000_000.0,
                    "schema_version": "v2",
                    "market": "CN",
                },
                {
                    "symbol": "000002.SZ",
                    "trade_date": t_date,
                    "turnover_rate_f": 1.5,
                    "circ_mv": 1_000_000.0,
                    "schema_version": "v2",
                    "market": "CN",
                },
            ]
        )
    pl.DataFrame(basic_data).write_parquet(basic_dir / "data.parquet")


def test_market_daily_builder_full(tmp_path: Path) -> None:
    _prepare_mock_catalog_data(tmp_path)
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    store = FeatureStore(mart_dir=tmp_path / "mart")

    builder = MarketDailyBuilder(catalog=catalog, store=store)
    df = builder.build(start_date=date(2026, 8, 1), end_date=date(2026, 8, 14), save=True)

    assert not df.is_empty()
    assert len(df) == 14
    assert "total_turnover" in df.columns
    assert "adv_dec_ratio" in df.columns
    assert "advance_ratio" in df.columns
    assert "above_ma20_ratio" in df.columns
    assert "return_20d" in df.columns
    assert "rsi_14d" in df.columns
    assert "ma_bias_20d" in df.columns
    assert "margin_balance" in df.columns
    assert "margin_buy_ratio" in df.columns
    assert "market_turnover_rate" in df.columns

    # 验证 FeatureStore 已保存
    persisted = store.get_market_daily()
    assert len(persisted) == 14
    assert persisted["total_turnover"][0] == 300000.0
    assert persisted["market_turnover_rate"][0] == pytest.approx(15.0)
    assert store.get_market_daily_metadata()["definition_fingerprint"]
    feature_values = store.values.get(feature_ids=["total_turnover"])
    assert len(feature_values) == 14
    assert feature_values["definition_version"].unique().to_list() == ["v1"]


def test_market_daily_breadth_matches_metric_engine_semantics() -> None:
    start = date(2025, 1, 1)
    rows: list[dict[str, object]] = []
    for index in range(260):
        trade_date = start + timedelta(days=index)
        rows.append(
            {
                "trade_date": trade_date,
                "symbol": "A",
                "close": 10.0 + index,
                "amount": 100.0,
            }
        )
    rows.append(
        {
            "trade_date": start + timedelta(days=259),
            "symbol": "NEW",
            "close": 20.0,
            "amount": 100.0,
        }
    )
    bars = pl.DataFrame(rows)

    class _Catalog:
        def load_bars(self, **_: object) -> pl.DataFrame:
            return bars

    mart = build_breadth_and_turnover(_Catalog(), start, start + timedelta(days=259))  # type: ignore[arg-type]
    engine = _calculate_breadth_columns(bars)
    latest_mart = mart.sort("trade_date").tail(1)
    latest_engine = engine.sort("trade_date").tail(1)

    assert latest_mart["advance_ratio"][0] == pytest.approx(latest_engine["advance_share"][0])
    assert latest_mart["above_ma20_ratio"][0] == pytest.approx(latest_engine["above_ma20_share"][0])
    assert latest_mart["new_high_252d_ratio"][0] == pytest.approx(
        latest_engine["new_high_share_252d"][0]
    )


def test_market_daily_technical_metrics_match_metric_engine_medians() -> None:
    start = date(2025, 1, 1)
    rows: list[dict[str, object]] = []
    for index in range(45):
        trade_date = start + timedelta(days=index)
        rows.extend(
            [
                {
                    "trade_date": trade_date,
                    "symbol": "A",
                    "close": 10.0 + index * 0.2,
                    "amount": 100.0,
                },
                {
                    "trade_date": trade_date,
                    "symbol": "B",
                    "close": 30.0 - index * 0.1 + (index % 3) * 0.05,
                    "amount": 100.0,
                },
            ]
        )
    bars = pl.DataFrame(rows)
    end = start + timedelta(days=44)

    class _Catalog:
        data_source = "tushare"

        def load_bars(self, **_: object) -> pl.DataFrame:
            return bars

        def load_dataset(self, dataset: str, **_: object) -> pl.DataFrame:
            return bars if dataset == "stock_daily_bar" else pl.DataFrame()

    mart = build_breadth_and_turnover(
        _Catalog(),
        start,
        end,  # type: ignore[arg-type]
    ).filter(pl.col("trade_date") == end)
    engine = MetricEngine()
    results = engine.compute(
        ["return_20d", "rsi_14d", "ma_bias_20d"],
        context=MetricContext(
            catalog=cast("MarketDataCatalog", _Catalog()),
            target_date=end,
            start_date=start,
            end_date=end,
        ),
    )

    for result in results:
        expected = result.frame.filter(pl.col("trade_date") == end)[result.metric_id].median()
        assert expected is not None
        assert mart[result.metric_id][0] == pytest.approx(expected)
