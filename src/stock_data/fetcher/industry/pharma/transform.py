"""中国创新药海外 License-out (BD) 交易与实体层 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.pharma.models import (
    PharmaBdAssetRecord,
    PharmaBdDealRecord,
    PharmaBdEventRecord,
    PharmaLicenseOutRecord,
)

PHARMA_LICENSE_OUT_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "upfront_cash_million_usd": pl.Float64,
    "potential_total_deal_million_usd": pl.Float64,
    "monthly_upfront_million_usd": pl.Float64,  # 兼容别名
    "monthly_total_deal_million_usd": pl.Float64,  # 兼容别名
    "deal_count": pl.Int64,
    "asset_count": pl.Int64,
    "mnc_deal_count": pl.Int64,
    "global_deal_count": pl.Int64,
    "median_upfront_million_usd": pl.Float64,
    "avg_upfront_million_usd": pl.Float64,
    "upfront_to_total_ratio": pl.Float64,
    "upfront_3mma": pl.Float64,
    "total_deal_3mma": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
    "global_rights_ratio": pl.Float64,
    "mnc_ratio": pl.Float64,
    "late_stage_ratio": pl.Float64,
    "adc_asset_count": pl.Int64,
    "bispecific_asset_count": pl.Int64,
    "metabolic_glp1_asset_count": pl.Int64,
    "small_molecule_asset_count": pl.Int64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

PHARMA_BD_DEAL_SCHEMA = {
    "deal_id": pl.String,
    "licensor": pl.String,
    "licensor_type": pl.String,
    "licensee": pl.String,
    "is_mnc": pl.Boolean,
    "transaction_type": pl.String,
    "territory_scope": pl.String,
    "announcement_date": pl.Date,
    "effective_date": pl.Date,
    "source_filing": pl.String,
    "source_url": pl.String,
}

PHARMA_BD_ASSET_SCHEMA = {
    "asset_id": pl.String,
    "deal_id": pl.String,
    "drug_name_code": pl.String,
    "target": pl.String,
    "modality": pl.String,
    "stage": pl.String,
    "indication": pl.String,
}

PHARMA_BD_EVENT_SCHEMA = {
    "event_id": pl.String,
    "deal_id": pl.String,
    "event_type": pl.String,
    "event_date": pl.Date,
    "upfront_cash_usd": pl.Float64,
    "equity_investment_usd": pl.Float64,
    "option_payment_usd": pl.Float64,
    "near_term_milestone_usd": pl.Float64,
    "potential_total_deal_usd": pl.Float64,
    "equity_stake_pct": pl.Float64,
    "original_currency": pl.String,
    "notes": pl.String,
}


def empty_pharma_license_out() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=PHARMA_LICENSE_OUT_SCHEMA)


def records_to_pharma_bd_frame(records: Sequence[PharmaLicenseOutRecord]) -> pl.DataFrame:
    """将创新药海外 BD 授权记录转换为强类型 Polars DataFrame，并自动计算 4 维量化特征。"""
    if not records:
        return empty_pharma_license_out()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "upfront_cash_million_usd": [
            r.upfront_cash_million_usd
            if r.upfront_cash_million_usd is not None
            else (r.monthly_upfront_million_usd or 0.0)
            for r in records
        ],
        "potential_total_deal_million_usd": [
            r.potential_total_deal_million_usd
            if r.potential_total_deal_million_usd is not None
            else (r.monthly_total_deal_million_usd or 0.0)
            for r in records
        ],
        "monthly_upfront_million_usd": [
            r.upfront_cash_million_usd
            if r.upfront_cash_million_usd is not None
            else (r.monthly_upfront_million_usd or 0.0)
            for r in records
        ],
        "monthly_total_deal_million_usd": [
            r.potential_total_deal_million_usd
            if r.potential_total_deal_million_usd is not None
            else (r.monthly_total_deal_million_usd or 0.0)
            for r in records
        ],
        "deal_count": [r.deal_count for r in records],
        "asset_count": [r.asset_count for r in records],
        "mnc_deal_count": [r.mnc_deal_count for r in records],
        "global_deal_count": [r.global_deal_count for r in records],
        "median_upfront_million_usd": [r.median_upfront_million_usd for r in records],
        "avg_upfront_million_usd": [r.avg_upfront_million_usd for r in records],
        "upfront_to_total_ratio": [r.upfront_to_total_ratio for r in records],
        "upfront_3mma": [r.upfront_3mma for r in records],
        "total_deal_3mma": [r.total_deal_3mma for r in records],
        "yoy_growth_3mma": [r.yoy_growth_3mma for r in records],
        "mom_growth_3mma": [r.mom_growth_3mma for r in records],
        "global_rights_ratio": [r.global_rights_ratio for r in records],
        "mnc_ratio": [r.mnc_ratio for r in records],
        "late_stage_ratio": [r.late_stage_ratio for r in records],
        "adc_asset_count": [r.adc_asset_count for r in records],
        "bispecific_asset_count": [r.bispecific_asset_count for r in records],
        "metabolic_glp1_asset_count": [r.metabolic_glp1_asset_count for r in records],
        "small_molecule_asset_count": [r.small_molecule_asset_count for r in records],
        "unit": [r.unit or "million_usd" for r in records],
        "source": [r.source or "PharmaCube/Filings/PR" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=PHARMA_LICENSE_OUT_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )

    # 自动计算首付款 3MMA 与总交易额 3MMA (平滑大单脉冲)
    if df["upfront_3mma"].null_count() == len(df):
        df = df.with_columns(
            pl.col("upfront_cash_million_usd")
            .rolling_mean(window_size=3, min_samples=1)
            .alias("upfront_3mma"),
            pl.col("potential_total_deal_million_usd")
            .rolling_mean(window_size=3, min_samples=1)
            .alias("total_deal_3mma"),
        )
    elif df["total_deal_3mma"].null_count() == len(df):
        df = df.with_columns(
            pl.col("potential_total_deal_million_usd")
            .rolling_mean(window_size=3, min_samples=1)
            .alias("total_deal_3mma")
        )

    # 衍生同比与环比斜率
    if df["yoy_growth_3mma"].null_count() == len(df):
        prev_12 = pl.col("upfront_3mma").shift(12)
        prev_1 = pl.col("upfront_3mma").shift(1)
        df = df.with_columns(
            pl.when(prev_12 > 0)
            .then(pl.col("upfront_3mma") / prev_12 - 1.0)
            .when(prev_12 == 0)
            .then(pl.when(pl.col("upfront_3mma") > 0).then(1.0).otherwise(0.0))
            .otherwise(None)
            .alias("yoy_growth_3mma"),
            pl.when(prev_1 > 0)
            .then(pl.col("upfront_3mma") / prev_1 - 1.0)
            .when(prev_1 == 0)
            .then(pl.when(pl.col("upfront_3mma") > 0).then(1.0).otherwise(0.0))
            .otherwise(None)
            .alias("mom_growth_3mma"),
        )

    # 衍生比例指标
    df = df.with_columns(
        pl.when(pl.col("potential_total_deal_million_usd") > 0)
        .then(pl.col("upfront_cash_million_usd") / pl.col("potential_total_deal_million_usd"))
        .otherwise(0.0)
        .alias("upfront_to_total_ratio"),
        pl.when(pl.col("deal_count") > 0)
        .then(pl.col("global_deal_count") / pl.col("deal_count"))
        .otherwise(0.0)
        .alias("global_rights_ratio"),
        pl.when(pl.col("deal_count") > 0)
        .then(pl.col("mnc_deal_count") / pl.col("deal_count"))
        .otherwise(0.0)
        .alias("mnc_ratio"),
    )

    return df


def deals_to_frame(records: Sequence[PharmaBdDealRecord]) -> pl.DataFrame:
    """转换为协议层 Polars DataFrame。"""
    if not records:
        return pl.DataFrame(schema=PHARMA_BD_DEAL_SCHEMA)
    data = {
        "deal_id": [r.deal_id for r in records],
        "licensor": [r.licensor for r in records],
        "licensor_type": [r.licensor_type for r in records],
        "licensee": [r.licensee for r in records],
        "is_mnc": [r.is_mnc for r in records],
        "transaction_type": [r.transaction_type for r in records],
        "territory_scope": [r.territory_scope for r in records],
        "announcement_date": [r.announcement_date for r in records],
        "effective_date": [r.effective_date for r in records],
        "source_filing": [r.source_filing for r in records],
        "source_url": [r.source_url for r in records],
    }
    return (
        pl.DataFrame(data, schema=PHARMA_BD_DEAL_SCHEMA)
        .unique(subset=["deal_id"], keep="last")
        .sort("announcement_date")
    )


def assets_to_frame(records: Sequence[PharmaBdAssetRecord]) -> pl.DataFrame:
    """转换为资产/管线层 Polars DataFrame。"""
    if not records:
        return pl.DataFrame(schema=PHARMA_BD_ASSET_SCHEMA)
    data = {
        "asset_id": [r.asset_id for r in records],
        "deal_id": [r.deal_id for r in records],
        "drug_name_code": [r.drug_name_code for r in records],
        "target": [r.target for r in records],
        "modality": [r.modality for r in records],
        "stage": [r.stage for r in records],
        "indication": [r.indication for r in records],
    }
    return pl.DataFrame(data, schema=PHARMA_BD_ASSET_SCHEMA).unique(
        subset=["asset_id"], keep="last"
    )


def events_to_frame(records: Sequence[PharmaBdEventRecord]) -> pl.DataFrame:
    """转换为事件流 Polars DataFrame。"""
    if not records:
        return pl.DataFrame(schema=PHARMA_BD_EVENT_SCHEMA)
    data = {
        "event_id": [r.event_id for r in records],
        "deal_id": [r.deal_id for r in records],
        "event_type": [r.event_type for r in records],
        "event_date": [r.event_date for r in records],
        "upfront_cash_usd": [r.upfront_cash_usd for r in records],
        "equity_investment_usd": [r.equity_investment_usd for r in records],
        "option_payment_usd": [r.option_payment_usd for r in records],
        "near_term_milestone_usd": [r.near_term_milestone_usd for r in records],
        "potential_total_deal_usd": [r.potential_total_deal_usd for r in records],
        "equity_stake_pct": [r.equity_stake_pct for r in records],
        "original_currency": [r.original_currency for r in records],
        "notes": [r.notes for r in records],
    }
    return (
        pl.DataFrame(data, schema=PHARMA_BD_EVENT_SCHEMA)
        .unique(subset=["event_id"], keep="last")
        .sort("event_date")
    )
