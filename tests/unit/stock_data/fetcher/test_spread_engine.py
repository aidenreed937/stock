"""化学价差计算引擎（配置驱动）测试。

覆盖：价格面板加载与多源优先级合并、按 cost_models.yaml 系数计算、
必需输入缺失时的跳过行为、以及计算结果与存量事实行的合并优先级。
"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.spreads import (
    SPREAD_PRODUCT_SPECS,
    ChemicalSpreadCalculator,
    PriceInput,
    _coalesce_price_sources,
    _load_raw_spread_frame,
    _merge_spread_frames,
)

_DATES = [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19)]  # 三个连续 ISO 周


def _write_engine_inputs(root: Path, *, include_px: bool = True) -> Path:
    """构造最小可用的 RAW/Curated 布局，返回 raw_dir。"""
    raw_dir = root / "data" / "raw" / "industry"
    curated_dir = root / "data" / "curated" / "industry"
    curated_dir.mkdir(parents=True)

    spot: dict[str, list[float]] = {
        "SA_light": [1300.0, 1310.0, 1320.0],
        "UR": [1700.0, 1710.0, 1720.0],
        "SH": [700.0, 710.0, 720.0],
        "TA": [5000.0, 5010.0, 5020.0],
        "MA": [2500.0, 2510.0, 2520.0],
        "TiO2": [14000.0, 14100.0, 14200.0],
        "H2SO4": [400.0, 410.0, 420.0],
    }
    if include_px:
        spot["PX"] = [7000.0, 7010.0, 7020.0]

    rows = [
        {"symbol": symbol, "trade_date": trade_date, "spot_price_cny": price}
        for symbol, prices in spot.items()
        for trade_date, price in zip(_DATES, prices, strict=True)
    ]
    pl.DataFrame(rows).write_parquet(curated_dir / "chemical_spot_price.parquet")

    pl.DataFrame(
        {
            "trade_date": _DATES,
            "q5500_fob_price_cny": [700.0, 710.0, 720.0],
        }
    ).write_parquet(curated_dir / "coal_market.parquet")
    return raw_dir


def _computed_by_product(frame: pl.DataFrame) -> dict[str, float]:
    latest = (
        frame.sort("trade_date")
        .group_by("product_name")
        .agg(pl.col("spread_margin_cny_raw").last().alias("margin"))
    )
    return {row["product_name"]: float(row["margin"]) for row in latest.to_dicts()}


def test_computed_spreads_use_config_coefficients_and_local_prices(tmp_path: Path) -> None:
    calc = ChemicalSpreadCalculator(raw_dir=_write_engine_inputs(tmp_path))

    computed = calc.build_computed_spreads()

    assert len(SPREAD_PRODUCT_SPECS) == 6
    # 3 周 × 6 品种
    assert computed.height == 18
    assert set(computed["product_name"].unique().to_list()) == {
        "纯碱",
        "烧碱",
        "PTA",
        "钛白粉",
        "甲醇",
        "尿素",
    }
    # 校验必需文本字段非空（质检门禁要求）
    for column in ("product_name", "symbol", "process_type", "source"):
        assert computed[column].null_count() == 0
        assert all(value.strip() for value in computed[column].unique().to_list())

    margins = _computed_by_product(computed)
    # 双吨利润 = 纯碱 1320 + 氯化铵(1720*0.45=774) - 原料(1.2*280+0.135*1720*1.15+0.4*720) - 450
    raw_cost = 1.2 * 280.0 + 0.135 * 1720.0 * 1.15 + 0.4 * 720.0
    assert margins["纯碱"] == round(1320.0 + 774.0 - raw_cost - 450.0, 2)
    # PTA 加工费 = 5020 - 0.655 * 7020
    assert margins["PTA"] == round(5020.0 - 0.655 * 7020.0, 2)
    # 钛白粉：钛精矿取显式回退 2200、硫酸取 420
    assert margins["钛白粉"] == round(14200.0 - (2.0 * 2200.0 + 3.5 * 420.0) - 3800.0, 2)


def test_computed_spreads_skips_product_without_required_input(tmp_path: Path) -> None:
    """PX 为 PTA 的必需输入且无恒量回退，缺失时不得产出 PTA 行。"""
    calc = ChemicalSpreadCalculator(raw_dir=_write_engine_inputs(tmp_path, include_px=False))

    computed = calc.build_computed_spreads()

    assert "PTA" not in set(computed["product_name"].unique().to_list())
    assert computed.height == 15


def test_coalesce_price_sources_prefers_earlier_source_and_never_backfills() -> None:
    """优先级靠前的来源优先；来源启用之前的历史缺口不得反向填充。"""
    preferred = pl.DataFrame(
        {"trade_date": [date(2026, 1, 12), date(2026, 1, 19)], "price": [200.0, 210.0]}
    )
    fallback = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19)],
            "price": [100.0, 100.0, 100.0],
        }
    )

    merged = _coalesce_price_sources([preferred, fallback])

    assert merged["trade_date"].to_list() == _DATES
    # 2026-01-05 早于首选来源的启用日，必须回落到次选来源而不是反向填充 200.0
    assert merged["price"].to_list() == [100.0, 200.0, 210.0]


def test_load_price_input_series_reads_constant_as_no_series(tmp_path: Path) -> None:
    calc = ChemicalSpreadCalculator(raw_dir=_write_engine_inputs(tmp_path))

    series = calc.load_price_input_series(PriceInput(key="salt_price", constant=280.0))

    assert series.is_empty()


def test_merge_spread_frames_prefers_computed_and_retains_uncovered(tmp_path: Path) -> None:
    calc = ChemicalSpreadCalculator(raw_dir=_write_engine_inputs(tmp_path))
    computed = calc.build_computed_spreads()

    existing = pl.DataFrame(
        [
            {
                "trade_date": date(2026, 1, 5),
                "product_name": "纯碱",
                "symbol": "SA",
                "process_type": "联碱法双吨",
                "product_price_cny_raw": "1",
                "byproduct_price_cny_raw": "1",
                "raw_material_cost_cny_raw": "1",
                "spread_margin_cny_raw": "1",
                "cash_breakeven_cost_cny_raw": "1",
                "margin_regime_raw": "near_breakeven",
                "source": "Longzhong_Oilchem",
                "release_date": date(2026, 1, 5),
                "collected_at": "2026-01-05T00:00:00Z",
                "data_status": "actual",
            },
            {
                "trade_date": date(2026, 1, 5),
                "product_name": "醋酸",
                "symbol": "AA",
                "process_type": "甲醇羰基化",
                "product_price_cny_raw": "1",
                "byproduct_price_cny_raw": "0",
                "raw_material_cost_cny_raw": "1",
                "spread_margin_cny_raw": "1",
                "cash_breakeven_cost_cny_raw": "1",
                "margin_regime_raw": "profitable",
                "source": "Longzhong_Oilchem",
                "release_date": date(2026, 1, 5),
                "collected_at": "2026-01-05T00:00:00Z",
                "data_status": "actual",
            },
        ]
    )

    merged = _merge_spread_frames(computed, existing)

    # 计算覆盖的（纯碱, SA, 联碱法双吨）整体以计算值为准，存量同键行被丢弃
    soda = merged.filter(pl.col("product_name") == "纯碱")
    assert soda["source"].unique().to_list() == ["Derived/Config_Cost_Model+Local_Spot"]
    # 未覆盖的存量品种（醋酸）予以保留
    assert "醋酸" in set(merged["product_name"].unique().to_list())
    assert merged.height == computed.height + 1


def test_load_raw_spread_frame_normalizes_process_alias(tmp_path: Path) -> None:
    raw_file = tmp_path / "chemical_spreads.csv"
    raw_file.write_text(
        "trade_date,product_name,symbol,process_type,product_price_cny,byproduct_price_cny,"
        "raw_material_cost_cny,spread_margin_cny,cash_breakeven_cost_cny,margin_regime,"
        "source,release_date,collected_at,data_status\n"
        "2026-01-05,钛白粉,TiO2,硫酸法金红石型,1,,1,1,1,profitable,raw,"
        "2026-01-05,2026-01-05T00:00:00Z,actual\n",
        encoding="utf-8",
    )

    loaded = _load_raw_spread_frame(raw_file)

    assert loaded["process_type"].to_list() == ["硫酸法金红石"]
