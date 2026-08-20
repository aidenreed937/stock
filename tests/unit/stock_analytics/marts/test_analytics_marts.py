"""行业与市场温度分析 Mart 测试。"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl

import stock_analytics.marts.market_temperature as market_temperature_mart
from stock_analytics.features.store import FeatureStore
from stock_analytics.marts.industry_structure import build_industry_daily_frame
from stock_analytics.marts.market_temperature import (
    build_market_temperature_derived_facts_mart,
)
from stock_reporting.interpretation.industry_structure.config import (
    FundamentalBlendConfig,
    IndustryStructureConfig,
    ScoreWeights,
)
from stock_reporting.interpretation.market_temperature.config import MarketTemperatureConfig


class _Catalog:
    data_source = "tushare"
    storage_dir: Path | None = None

    def load_dataset(self, dataset: str, **_: object) -> pl.DataFrame:
        del dataset
        return pl.DataFrame()


def test_industry_daily_frame_materializes_unique_daily_facts() -> None:
    config = IndustryStructureConfig(
        schema_version=1,
        title="测试行业结构",
        artifact_root=Path("data/analytics/industry_structure"),
        main_window=5,
        short_windows=(2,),
        medium_windows=(5,),
        classification="SW2021",
        benchmark="",
        score_weights=ScoreWeights(),
        fundamental_blend=FundamentalBlendConfig(),
        datasets=(),
    )
    start = date(2026, 8, 1)
    raw = pl.DataFrame(
        [
            {
                "symbol": f"801{industry:03d}.SI",
                "trade_date": start + timedelta(days=offset),
                "name": f"行业{industry}",
                "close": float(100 + industry + offset),
                "amount": 1_000_000.0,
                "classification": "SW2021",
                "industry_level": "L1",
            }
            for offset in range(6)
            for industry in (1, 2)
        ]
    )

    result = build_industry_daily_frame(raw, config, _Catalog())

    assert result.height == 12
    assert result.unique(subset=["trade_date", "industry_code"]).height == result.height
    assert result["return_5d"].drop_nulls().len() == 2
    assert result["ma_bias_20d"].drop_nulls().len() == 4
    assert result.schema["amount_yi"] == pl.Float64
    assert result.schema["tcr_percentile"] == pl.Float64


def test_market_temperature_facts_mart_persists_build_stage_rows(
    tmp_path: Path, monkeypatch
) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    trade_dates = (date(2026, 8, 1), date(2026, 8, 2))
    store.save_market_daily(
        pl.DataFrame(
            {
                "trade_date": trade_dates,
                "advance_ratio": [0.5, 0.6],
            }
        ),
        overwrite=True,
    )
    config = MarketTemperatureConfig.from_mapping(
        {
            "main_window": 2,
            "short_windows": [2],
            "metric_values": {"enabled": True},
            "dimensions": [],
            "datasets": [],
        }
    )

    def fake_derived_rows(**kwargs: object) -> list[dict[str, object]]:
        as_of_date = kwargs["as_of_date"]
        assert isinstance(as_of_date, date)
        return [
            {
                "fact_id": f"metric.derived.{as_of_date.isoformat()}",
                "category": "metric_value",
                "dimension": "derived",
                "data_source": "mart",
                "dataset": "curated",
                "as_of_date": as_of_date,
                "window": 0,
                "metric_id": "derived_metric",
                "value_float": 42.0,
                "value_text": "",
                "unit": "temperature",
                "sample_size": 1,
                "source": "test",
                "status": "ok",
                "note": "test",
            }
        ]

    monkeypatch.setattr(market_temperature_mart, "collect_derived_metric_rows", fake_derived_rows)
    monkeypatch.setattr(market_temperature_mart, "collect_metric_engine_rows", lambda *_, **__: [])
    monkeypatch.setattr(market_temperature_mart, "collect_short_term_rows", lambda *_, **__: [])

    result = build_market_temperature_derived_facts_mart(
        _Catalog(),
        store,
        config,
        start_date=trade_dates[0],
        end_date=trade_dates[-1],
        overwrite=True,
    )

    assert result.height == 2
    assert store.get_market_temperature_derived_facts(trade_dates[-1]).height == 1
