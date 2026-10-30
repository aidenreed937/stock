"""国家能源局 (NEA) 光伏装机容量 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.power.models import (
    SolarCapacityRecord,
)
from stock_data.fetcher.industry.power.schemas import (
    POLYSILICON_BALANCE_MONTHLY_SCHEMA,
    POLYSILICON_INVENTORY_MONTHLY_SCHEMA,
    POLYSILICON_SUPPLY_MONTHLY_SCHEMA,
    PV_WAFER_MONTHLY_SCHEMA,
    SILICON_WAFER_MONTHLY_SCHEMA,
    SILICON_WAFER_RAW_SCHEMA,
    SOLAR_CAPACITY_RAW_SCHEMA,
    SOLAR_CAPACITY_SCHEMA,
    SOLAR_CELL_NBS_RAW_SCHEMA,
    SOLAR_CELL_NBS_SCHEMA,
    SOLAR_PRICE_CHAIN_RAW_SCHEMA,
    SOLAR_PRICE_CHAIN_SCHEMA,
    SOLAR_SUPPLY_DEMAND_SCHEMA,
)
from stock_data.fetcher.industry.power.transforms.balance import (
    build_polysilicon_balance_frame,
    empty_polysilicon_balance,
)
from stock_data.fetcher.industry.power.transforms.cell import (
    empty_raw_solar_cell_nbs,
    empty_solar_cell_nbs,
    records_to_raw_solar_cell_nbs_frame,
    records_to_solar_cell_nbs_frame,
)
from stock_data.fetcher.industry.power.transforms.polysilicon import (
    empty_polysilicon_inventory,
    empty_polysilicon_supply,
    empty_pv_wafer,
    records_to_polysilicon_inventory_frame,
    records_to_polysilicon_supply_frame,
    records_to_pv_wafer_frame,
)
from stock_data.fetcher.industry.power.transforms.price import (
    empty_raw_solar_price_chain,
    empty_solar_price_chain,
    records_to_raw_solar_price_chain_frame,
    records_to_solar_price_chain_frame,
)
from stock_data.fetcher.industry.power.transforms.silicon import (
    build_solar_supply_demand_frame,
    empty_raw_silicon_wafer_monthly,
    empty_silicon_wafer_monthly,
    empty_solar_supply_demand,
    get_silicon_consumption_ratio,
    records_to_raw_silicon_wafer_monthly_frame,
    records_to_silicon_wafer_monthly_frame,
)

__all__ = [
    "POLYSILICON_BALANCE_MONTHLY_SCHEMA",
    "POLYSILICON_INVENTORY_MONTHLY_SCHEMA",
    "POLYSILICON_SUPPLY_MONTHLY_SCHEMA",
    "PV_WAFER_MONTHLY_SCHEMA",
    "SILICON_WAFER_MONTHLY_SCHEMA",
    "SILICON_WAFER_RAW_SCHEMA",
    "SOLAR_CAPACITY_RAW_SCHEMA",
    "SOLAR_CAPACITY_SCHEMA",
    "SOLAR_CELL_NBS_RAW_SCHEMA",
    "SOLAR_CELL_NBS_SCHEMA",
    "SOLAR_PRICE_CHAIN_RAW_SCHEMA",
    "SOLAR_PRICE_CHAIN_SCHEMA",
    "SOLAR_SUPPLY_DEMAND_SCHEMA",
    "build_polysilicon_balance_frame",
    "build_solar_supply_demand_frame",
    "empty_polysilicon_balance",
    "empty_polysilicon_inventory",
    "empty_polysilicon_supply",
    "empty_pv_wafer",
    "empty_raw_silicon_wafer_monthly",
    "empty_raw_solar_capacity",
    "empty_raw_solar_cell_nbs",
    "empty_raw_solar_price_chain",
    "empty_silicon_wafer_monthly",
    "empty_solar_capacity",
    "empty_solar_cell_nbs",
    "empty_solar_price_chain",
    "empty_solar_supply_demand",
    "get_silicon_consumption_ratio",
    "records_to_polysilicon_inventory_frame",
    "records_to_polysilicon_supply_frame",
    "records_to_pv_wafer_frame",
    "records_to_raw_silicon_wafer_monthly_frame",
    "records_to_raw_solar_cell_nbs_frame",
    "records_to_raw_solar_frame",
    "records_to_raw_solar_price_chain_frame",
    "records_to_silicon_wafer_monthly_frame",
    "records_to_solar_cell_nbs_frame",
    "records_to_solar_frame",
    "records_to_solar_price_chain_frame",
]


def _raw_text(raw_value: str | None, value: object = None) -> str | None:
    """优先保留采集器提供的源文本，兼容旧模型中的数值字段。"""
    if raw_value is not None and str(raw_value).strip():
        return str(raw_value)
    if value is None:
        return None
    return str(value)


def _raw_number(raw_value: str | None, fallback: float | None) -> float | None:
    """将 RAW 源数值解析为 Curated 数值；解析失败时使用兼容字段。"""
    if raw_value is not None and str(raw_value).strip():
        try:
            return float(str(raw_value).replace(",", "").strip())
        except ValueError:
            pass
    return fallback


def empty_raw_solar_capacity() -> pl.DataFrame:
    """构造光伏装机 RAW 空表骨架。"""
    return pl.DataFrame(schema=SOLAR_CAPACITY_RAW_SCHEMA)


def records_to_raw_solar_frame(records: Sequence[SolarCapacityRecord]) -> pl.DataFrame:
    """将 NEA 装机记录转换为只含源字段的 RAW 表。"""
    if not records:
        return empty_raw_solar_capacity()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "monthly_new_capacity_gw_raw": [
            _raw_text(
                r.monthly_new_capacity_gw_raw,
                None if r.cumulative_capacity_gw is not None else r.monthly_new_capacity_gw,
            )
            for r in records
        ],
        "cumulative_capacity_gw_raw": [
            _raw_text(r.cumulative_capacity_gw_raw, r.cumulative_capacity_gw) for r in records
        ],
        "yoy_growth_raw": [_raw_text(r.yoy_growth_raw, r.yoy_growth) for r in records],
        "source": [r.source or "NEA" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }
    return (
        pl.DataFrame(data, schema=SOLAR_CAPACITY_RAW_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )


def empty_solar_capacity() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=SOLAR_CAPACITY_SCHEMA)


def records_to_solar_frame(records: Sequence[SolarCapacityRecord]) -> pl.DataFrame:
    """将光伏装机容量记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_solar_capacity()

    ordered_records = sorted(records, key=lambda record: record.trade_date)
    now_iso = datetime.now(UTC).isoformat()
    cumulative_values = [
        _raw_number(r.cumulative_capacity_gw_raw, r.cumulative_capacity_gw) for r in ordered_records
    ]
    monthly_values: list[float | None] = []
    for index, record in enumerate(ordered_records):
        source_value = _raw_number(
            record.monthly_new_capacity_gw_raw,
            None,
        )
        if source_value is not None:
            monthly_values.append(source_value)
            continue
        cumulative = cumulative_values[index]
        previous = cumulative_values[index - 1] if index else None
        if cumulative is not None and previous is not None:
            monthly_values.append(round(cumulative - previous, 2))
        elif cumulative is None or record.cumulative_capacity_gw_raw is None:
            monthly_values.append(record.monthly_new_capacity_gw)
        else:
            monthly_values.append(None)

    data = {
        "report_month": [r.report_month for r in ordered_records],
        "trade_date": [r.trade_date for r in ordered_records],
        "monthly_new_capacity_gw": monthly_values,
        "monthly_new_capacity_3mma": [None] * len(ordered_records),
        "cumulative_capacity_gw": cumulative_values,
        "yoy_growth": [_raw_number(r.yoy_growth_raw, r.yoy_growth) for r in ordered_records],
        "yoy_growth_3mma": [None] * len(ordered_records),
        "mom_growth_3mma": [None] * len(ordered_records),
        "unit": ["gw/ratio" for _ in ordered_records],
        "source": [r.source or "NEA" for r in ordered_records],
        "source_url": [r.source_url or "" for r in ordered_records],
        "release_date": [r.release_date for r in ordered_records],
        "data_status": [r.data_status or "actual" for r in ordered_records],
        "collected_at": [r.collected_at or now_iso for r in ordered_records],
    }
    df = (
        pl.DataFrame(data, schema=SOLAR_CAPACITY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    # 差分、3MMA 和其增速均只在 Curated 转换阶段计算。
    df = df.with_columns(
        pl.col("monthly_new_capacity_gw")
        .rolling_mean(window_size=3, min_samples=1)
        .alias("monthly_new_capacity_3mma")
    ).with_columns(
        (
            pl.col("monthly_new_capacity_3mma") / pl.col("monthly_new_capacity_3mma").shift(12)
            - 1.0
        ).alias("yoy_growth_3mma"),
        (
            pl.col("monthly_new_capacity_3mma") / pl.col("monthly_new_capacity_3mma").shift(1) - 1.0
        ).alias("mom_growth_3mma"),
    )
    if df["yoy_growth"].null_count() > 0 and "cumulative_capacity_gw" in df.columns:
        df = df.with_columns(
            pl.when(pl.col("yoy_growth").is_null())
            .then(
                pl.col("cumulative_capacity_gw") / pl.col("cumulative_capacity_gw").shift(12) - 1.0
            )
            .otherwise(pl.col("yoy_growth"))
            .alias("yoy_growth")
        )
    return df
