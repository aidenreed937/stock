"""多日期产物共享上下文测试。"""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import polars as pl

import stock_analytics.pipelines.multi_date as multi_date


def test_run_multi_date_artifacts_serializes_and_shares_batch_state(
    monkeypatch, tmp_path: Path
) -> None:
    dates = (date(2026, 8, 18), date(2026, 8, 19))
    calls: list[tuple[str, date]] = []
    catalog_calls: list[tuple[str, int]] = []

    class _Catalog:
        data_source = "tushare"

        def __init__(self, **_: object) -> None:
            pass

        def latest_trade_dates(self, dataset: str, n: int = 1, **_: object):
            catalog_calls.append((dataset, n))
            return dates

    class _Store:
        def __init__(self, **_: object) -> None:
            pass

        def get_market_daily(self, **_: object) -> pl.DataFrame:
            return pl.DataFrame({"trade_date": list(dates), "return_20d": [0.1, 0.2]})

    def _market_temperature(**kwargs: object):
        target = kwargs["target_date"]
        assert isinstance(target, date)
        calls.append(("market", target))
        assert kwargs["update_latest"] is False
        assert kwargs["market_daily"] is not None
        assert kwargs["dataset_cache"] is shared_cache
        assert max(kwargs["trade_dates"]) <= target  # type: ignore[arg-type]
        return SimpleNamespace(paths=SimpleNamespace(run_dir=tmp_path / f"market-{target}"))

    def _industry_structure(**kwargs: object):
        target = kwargs["target_date"]
        assert isinstance(target, date)
        calls.append(("industry", target))
        assert kwargs["update_latest"] is False
        assert kwargs["dataset_cache"] is shared_cache
        assert max(kwargs["trade_dates"]) <= target  # type: ignore[arg-type]
        return SimpleNamespace(paths=SimpleNamespace(run_dir=tmp_path / f"industry-{target}"))

    def _investor_brief(**kwargs: object):
        target = kwargs["target_date"]
        assert isinstance(target, date)
        calls.append(("brief", target))
        assert kwargs["update_latest"] is False
        return SimpleNamespace(paths=SimpleNamespace(run_dir=tmp_path / f"brief-{target}"))

    shared_cache = None

    def _capture_contexts(target_dates, storage_dir, dataset_cache):
        nonlocal shared_cache
        shared_cache = dataset_cache
        assert tuple(target_dates) == dates
        assert storage_dir == tmp_path
        return {}

    monkeypatch.setattr(multi_date, "DataCatalog", _Catalog)
    monkeypatch.setattr(multi_date, "FeatureStore", _Store)
    monkeypatch.setattr(multi_date, "_build_metric_contexts", _capture_contexts)
    monkeypatch.setattr(multi_date, "run_market_temperature", _market_temperature)
    monkeypatch.setattr(multi_date, "run_industry_structure", _industry_structure)
    monkeypatch.setattr(multi_date, "run_investor_brief", _investor_brief)

    summaries = multi_date.run_multi_date_artifacts(
        [dates[1], dates[0], dates[0]],
        storage_dir=tmp_path,
        update_latest=False,
    )

    assert [summary.as_of_date for summary in summaries] == list(dates)
    assert calls == [
        ("market", dates[0]),
        ("industry", dates[0]),
        ("brief", dates[0]),
        ("market", dates[1]),
        ("industry", dates[1]),
        ("brief", dates[1]),
    ]
    assert {dataset for dataset, _ in catalog_calls} == {"stock_daily_bar", "sw_daily"}
