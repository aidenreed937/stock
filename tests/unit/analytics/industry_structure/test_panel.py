"""行业结构面板构建测试。"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from stock.analytics.industry_structure.config import (
    FundamentalBlendConfig,
    IndustryStructureConfig,
    ScoreWeights,
)
from stock.analytics.industry_structure.panel import build_industry_panel


def test_build_industry_panel_adds_fast_fundamental_fields(tmp_path: Path) -> None:
    storage_dir = tmp_path / "curated"
    as_of_date = date(2026, 8, 14)
    trade_dates = tuple(as_of_date - timedelta(days=offset) for offset in range(19, -1, -1))
    _write_sw_daily(storage_dir, as_of_date)
    _write_index_classify(storage_dir)
    _write_index_member(storage_dir)
    _write_lixinger_constituents_with_conflict(storage_dir)
    _write_fast_fundamental_inputs(storage_dir)

    panel = build_industry_panel(
        _config(),
        as_of_date=as_of_date,
        trade_dates=trade_dates,
        storage_dir=storage_dir,
    )

    assert panel.height == 2
    coal = panel.filter(pl.col("industry_code") == "801001.SI").to_dicts()[0]
    bank = panel.filter(pl.col("industry_code") == "801002.SI").to_dicts()[0]
    assert coal["forecast_sample_size"] == 1
    assert coal["forecast_positive_share"] == 100.0
    assert coal["forecast_p_change_mid_median"] == 75.0
    assert coal["express_sample_size"] == 1
    assert coal["express_profit_growth_median"] == 50.0
    assert coal["report_rc_sample_size"] == 1
    assert coal["report_rc_revision_ratio"] == 100.0
    assert coal["report_rc_up_count"] == 1
    assert coal["report_rc_down_count"] == 0
    assert bank["forecast_positive_share"] == 0.0
    assert bank["report_rc_revision_ratio"] == 0.0


def _config() -> IndustryStructureConfig:
    return IndustryStructureConfig(
        schema_version=1,
        title="测试行业结构",
        artifact_root=Path("data/analytics/industry_structure"),
        main_window=20,
        short_windows=(5, 10),
        medium_windows=(60, 120),
        classification="SW2021",
        benchmark="",
        score_weights=ScoreWeights(),
        fundamental_blend=FundamentalBlendConfig(),
        datasets=(),
    )


def _write_sw_daily(storage_dir: Path, as_of_date: date) -> None:
    rows = []
    for offset in range(80):
        trade_date = as_of_date - timedelta(days=79 - offset)
        for industry_index, name in ((1, "煤炭"), (2, "银行")):
            close = 10.0 + industry_index + offset * 0.1
            rows.append(
                {
                    "symbol": f"801{industry_index:03d}.SI",
                    "trade_date": trade_date,
                    "close": close,
                    "amount": 1_000_000_000.0 + industry_index * 100_000_000.0,
                    "name": name,
                }
            )
    _write_dataset(storage_dir, "tushare", "sw_daily", rows)


def _write_index_classify(storage_dir: Path) -> None:
    _write_dataset(
        storage_dir,
        "tushare",
        "index_classify",
        [
            {
                "index_code": "801001.SI",
                "industry_code": "270000",
                "industry_name": "煤炭",
                "level": "L1",
                "src": "SW2021",
            },
            {
                "index_code": "801002.SI",
                "industry_code": "280000",
                "industry_name": "银行",
                "level": "L1",
                "src": "SW2021",
            },
        ],
    )


def _write_index_member(storage_dir: Path) -> None:
    _write_dataset(
        storage_dir,
        "tushare",
        "index_member",
        [
            {
                "index_code": "801001.SI",
                "con_code": "000001.SZ",
                "in_date": "20200101",
                "out_date": "",
            },
            {
                "index_code": "801002.SI",
                "con_code": "000002.SZ",
                "in_date": "20200101",
                "out_date": "",
            },
        ],
    )


def _write_lixinger_constituents_with_conflict(storage_dir: Path) -> None:
    _write_dataset(
        storage_dir,
        "lixinger",
        "sw_2021_constituents",
        [
            {
                "symbol": "000001.SZ",
                "industryCode": "280000",
            },
        ],
    )


def _write_fast_fundamental_inputs(storage_dir: Path) -> None:
    _write_dataset(
        storage_dir,
        "tushare",
        "forecast",
        [
            {
                "symbol": "000001.SZ",
                "ann_date": "20260805",
                "end_date": "20260630",
                "type": "预增",
                "p_change_min": 50.0,
                "p_change_max": 100.0,
            },
            {
                "symbol": "000002.SZ",
                "ann_date": "20260805",
                "end_date": "20260630",
                "type": "预减",
                "p_change_min": -40.0,
                "p_change_max": -20.0,
            },
        ],
    )
    _write_dataset(
        storage_dir,
        "tushare",
        "express",
        [
            {
                "symbol": "000001.SZ",
                "ann_date": "20260806",
                "end_date": "20260630",
                "n_income": 150.0,
                "yoy_net_profit": 100.0,
                "diluted_roe": 10.0,
            },
            {
                "symbol": "000002.SZ",
                "ann_date": "20260806",
                "end_date": "20260630",
                "n_income": 90.0,
                "yoy_net_profit": 100.0,
                "diluted_roe": 4.0,
            },
        ],
    )
    _write_dataset(
        storage_dir,
        "tushare",
        "report_rc",
        [
            {
                "symbol": "000001.SZ",
                "report_date": "20260701",
                "org_name": "机构A",
                "quarter": "2026Q2",
                "np": 100.0,
            },
            {
                "symbol": "000001.SZ",
                "report_date": "20260805",
                "org_name": "机构A",
                "quarter": "2026Q2",
                "np": 120.0,
            },
            {
                "symbol": "000002.SZ",
                "report_date": "20260701",
                "org_name": "机构B",
                "quarter": "2026Q2",
                "np": 100.0,
            },
            {
                "symbol": "000002.SZ",
                "report_date": "20260805",
                "org_name": "机构B",
                "quarter": "2026Q2",
                "np": 80.0,
            },
        ],
    )


def _write_dataset(
    storage_dir: Path,
    data_source: str,
    dataset: str,
    rows: list[dict[str, object]],
) -> None:
    path = storage_dir / data_source / dataset
    path.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path / "data.parquet")
