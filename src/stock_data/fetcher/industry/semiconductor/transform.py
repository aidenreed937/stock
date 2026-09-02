"""全球半导体月度销售额 (SIA/WSTS) Schema 定义与转换器。"""

import calendar
from collections.abc import Sequence
from datetime import UTC, date, datetime

import polars as pl

from stock_data.fetcher.industry.models import (
    ChipLeadTimeRecord,
    SemiconductorEquipmentRecord,
    SemiconductorLeadRecord,
    SemiconductorSalesRecord,
)

SEMICONDUCTOR_SALES_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "global_sales_usd": pl.Float64,
    "china_sales_usd": pl.Float64,
    "china_yoy_growth": pl.Float64,
    "china_mom_growth": pl.Float64,
    "americas_sales_usd": pl.Float64,
    "europe_sales_usd": pl.Float64,
    "japan_sales_usd": pl.Float64,
    "asia_pacific_sales_usd": pl.Float64,
    "yoy_growth": pl.Float64,
    "mom_growth": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def compute_next_month_end(t_date: date) -> date:
    """计算次月最后一个自然日作为官方数据发布生效日 (release_date)。"""
    year = t_date.year
    month = t_date.month
    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1
    _, last_day = calendar.monthrange(next_year, next_month)
    return date(next_year, next_month, last_day)


def empty_semiconductor_sales() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_SALES_SCHEMA)


def records_to_semiconductor_frame(
    records: Sequence[SemiconductorSalesRecord],
) -> pl.DataFrame:
    """将半导体销售额记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_semiconductor_sales()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "global_sales_usd": [r.global_sales_usd for r in records],
        "china_sales_usd": [r.china_sales_usd for r in records],
        "china_yoy_growth": [r.china_yoy_growth for r in records],
        "china_mom_growth": [r.china_mom_growth for r in records],
        "americas_sales_usd": [r.americas_sales_usd for r in records],
        "europe_sales_usd": [r.europe_sales_usd for r in records],
        "japan_sales_usd": [r.japan_sales_usd for r in records],
        "asia_pacific_sales_usd": [r.asia_pacific_sales_usd for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
        "mom_growth": [r.mom_growth for r in records],
        "unit": [r.unit or "billion_usd" for r in records],
        "source": [r.source or "SIA/WSTS" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [
            r.release_date if r.release_date is not None else compute_next_month_end(r.trade_date)
            for r in records
        ],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    return (
        pl.DataFrame(data, schema=SEMICONDUCTOR_SALES_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )


SEMICONDUCTOR_LEAD_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "tsmc_revenue_ntd_million": pl.Float64,
    "tsmc_revenue_usd_million": pl.Float64,
    "tsmc_revenue_yoy": pl.Float64,
    "tsmc_revenue_mom": pl.Float64,
    "tsmc_revenue_3mma_usd": pl.Float64,
    "dram_dxi_index": pl.Float64,
    "dram_spot_price_usd": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_semiconductor_lead() -> pl.DataFrame:
    """构造半导体先导指标空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_LEAD_SCHEMA)


def records_to_semiconductor_lead_frame(
    records: Sequence[SemiconductorLeadRecord],
) -> pl.DataFrame:
    """将半导体先导指标记录转换为强类型 Polars DataFrame，并计算 3MMA。"""
    if not records:
        return empty_semiconductor_lead()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "tsmc_revenue_ntd_million": [r.tsmc_revenue_ntd_million for r in records],
        "tsmc_revenue_usd_million": [r.tsmc_revenue_usd_million for r in records],
        "tsmc_revenue_yoy": [r.tsmc_revenue_yoy for r in records],
        "tsmc_revenue_mom": [r.tsmc_revenue_mom for r in records],
        "tsmc_revenue_3mma_usd": [r.tsmc_revenue_3mma_usd for r in records],
        "dram_dxi_index": [r.dram_dxi_index for r in records],
        "dram_spot_price_usd": [r.dram_spot_price_usd for r in records],
        "unit": [r.unit or "million_ntd/usd" for r in records],
        "source": [r.source or "TSMC/DRAMeXchange" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    df = (
        pl.DataFrame(data, schema=SEMICONDUCTOR_LEAD_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )

    if (
        df["tsmc_revenue_3mma_usd"].is_null().all()
        and df["tsmc_revenue_usd_million"].is_not_null().any()
    ):
        df = df.with_columns(
            pl.col("tsmc_revenue_usd_million")
            .rolling_mean(window_size=3, min_samples=1)
            .round(2)
            .alias("tsmc_revenue_3mma_usd")
        )

    return df


CHIP_LEAD_TIME_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "avg_lead_time_weeks": pl.Float64,
    "mcu_lead_time_weeks": pl.Float64,
    "analog_lead_time_weeks": pl.Float64,
    "discrete_lead_time_weeks": pl.Float64,
    "compute_lead_time_weeks": pl.Float64,
    "lead_time_yoy_weeks": pl.Float64,
    "lead_time_mom_weeks": pl.Float64,
    "lead_time_status": pl.String,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_chip_lead_time() -> pl.DataFrame:
    """构造芯片交期先导指标空事实表骨架。"""
    return pl.DataFrame(schema=CHIP_LEAD_TIME_SCHEMA)


def records_to_chip_lead_time_frame(
    records: Sequence[ChipLeadTimeRecord],
) -> pl.DataFrame:
    """将芯片交期记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_chip_lead_time()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "avg_lead_time_weeks": [r.avg_lead_time_weeks for r in records],
        "mcu_lead_time_weeks": [r.mcu_lead_time_weeks for r in records],
        "analog_lead_time_weeks": [r.analog_lead_time_weeks for r in records],
        "discrete_lead_time_weeks": [r.discrete_lead_time_weeks for r in records],
        "compute_lead_time_weeks": [r.compute_lead_time_weeks for r in records],
        "lead_time_yoy_weeks": [r.lead_time_yoy_weeks for r in records],
        "lead_time_mom_weeks": [r.lead_time_mom_weeks for r in records],
        "lead_time_status": [r.lead_time_status for r in records],
        "unit": [r.unit or "weeks" for r in records],
        "source": [r.source or "Susquehanna/Distributor" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    df = (
        pl.DataFrame(data, schema=CHIP_LEAD_TIME_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    if len(df) > 1:
        df = df.with_columns(
            (pl.col("avg_lead_time_weeks") - pl.col("avg_lead_time_weeks").shift(1))
            .round(2)
            .alias("lead_time_mom_weeks"),
            (pl.col("avg_lead_time_weeks") - pl.col("avg_lead_time_weeks").shift(12))
            .round(2)
            .alias("lead_time_yoy_weeks"),
        )
    return df


SEMICONDUCTOR_EQUIPMENT_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "billings_jpy_billion": pl.Float64,
    "billings_3mma_jpy": pl.Float64,
    "yoy_growth": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_semiconductor_equipment() -> pl.DataFrame:
    """构造半导体设备出货空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_EQUIPMENT_SCHEMA)


def records_to_semiconductor_equipment_frame(
    records: Sequence[SemiconductorEquipmentRecord],
) -> pl.DataFrame:
    """将半导体设备出货记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_semiconductor_equipment()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "billings_jpy_billion": [r.billings_jpy_billion for r in records],
        "billings_3mma_jpy": [r.billings_3mma_jpy for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
        "yoy_growth_3mma": [r.yoy_growth_3mma for r in records],
        "mom_growth_3mma": [r.mom_growth_3mma for r in records],
        "unit": [r.unit or "billion_jpy" for r in records],
        "source": [r.source or "SEAJ" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    df = (
        pl.DataFrame(data, schema=SEMICONDUCTOR_EQUIPMENT_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    # 防御性门禁: 检测并自动修正百万円/億円导致的 10x 异常量纲 (日本半导体设备月出货量正常区间 100~800 十亿日元)
    df = df.with_columns(
        pl.when(pl.col("billings_jpy_billion") > 1500.0)
        .then((pl.col("billings_jpy_billion") / 10.0).round(2))
        .otherwise(pl.col("billings_jpy_billion"))
        .alias("billings_jpy_billion"),
        pl.when(pl.col("billings_3mma_jpy") > 1500.0)
        .then((pl.col("billings_3mma_jpy") / 10.0).round(2))
        .otherwise(pl.col("billings_3mma_jpy"))
        .alias("billings_3mma_jpy"),
    )
    # 自动计算 3MMA 与 YoY 增速（若输入为 null 时补全）
    if len(df) >= 3:
        df = (
            df.with_columns(
                pl.col("billings_jpy_billion")
                .rolling_mean(window_size=3, min_samples=1)
                .round(2)
                .alias("_3mma")
            )
            .with_columns(
                pl.when(pl.col("billings_3mma_jpy").is_null())
                .then(pl.col("_3mma"))
                .otherwise(pl.col("billings_3mma_jpy"))
                .alias("billings_3mma_jpy")
            )
            .drop("_3mma")
        )
    if len(df) >= 13:
        df = (
            df.with_columns(
                pl.col("billings_jpy_billion").pct_change(12).round(4).alias("_yoy"),
                pl.col("billings_3mma_jpy").pct_change(12).round(4).alias("_yoy_3mma"),
                pl.col("billings_3mma_jpy").pct_change(1).round(4).alias("_mom_3mma"),
            )
            .with_columns(
                pl.when(pl.col("yoy_growth").is_null())
                .then(pl.col("_yoy"))
                .when(pl.col("yoy_growth").abs() > 2.0)  # 处理历史百分制残留 (如 46.9 -> 0.469)
                .then((pl.col("yoy_growth") / 100.0).round(4))
                .otherwise(pl.col("yoy_growth"))
                .alias("yoy_growth"),
                pl.when(pl.col("yoy_growth_3mma").is_null())
                .then(pl.col("_yoy_3mma"))
                .when(pl.col("yoy_growth_3mma").abs() > 2.0)
                .then((pl.col("yoy_growth_3mma") / 100.0).round(4))
                # 残留百分制值 (abs<=2 绕过 /100, 且与自算 3MMA 同比偏差>0.3, 自算值可信): 用自算覆盖
                .when(
                    (pl.col("yoy_growth_3mma").abs() < 2.0)
                    & (pl.col("_yoy_3mma").abs() < 2.0)
                    & ((pl.col("yoy_growth_3mma") - pl.col("_yoy_3mma")).abs() > 0.3)
                )
                .then(pl.col("_yoy_3mma"))
                .otherwise(pl.col("yoy_growth_3mma"))
                .alias("yoy_growth_3mma"),
                pl.when(pl.col("mom_growth_3mma").is_null())
                .then(pl.col("_mom_3mma"))
                .when(pl.col("mom_growth_3mma").abs() > 2.0)
                .then((pl.col("mom_growth_3mma") / 100.0).round(4))
                .otherwise(pl.col("mom_growth_3mma"))
                .alias("mom_growth_3mma"),
            )
            .drop(["_yoy", "_yoy_3mma", "_mom_3mma"])
        )

    return df
