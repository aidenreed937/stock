"""半导体产业 Curated/RAW Schema 与端点存储契约。"""

from typing import Any

import polars as pl

from stock_data.fetcher.industry.semiconductor.transforms.memory_benchmark import (
    MEMORY_BENCHMARK_CURATED_SCHEMA as MEMORY_BENCHMARK_CURATED_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.memory_benchmark import (
    MEMORY_BENCHMARK_RAW_SCHEMA as MEMORY_BENCHMARK_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.taiwan_memory import (
    TAIWAN_MEMORY_LEAD_CURATED_SCHEMA as TAIWAN_MEMORY_LEAD_CURATED_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.taiwan_memory import (
    TAIWAN_MEMORY_LEAD_RAW_SCHEMA as TAIWAN_MEMORY_LEAD_RAW_SCHEMA,
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
    "americas_yoy_growth": pl.Float64,
    "europe_yoy_growth": pl.Float64,
    "japan_yoy_growth": pl.Float64,
    "asia_pacific_yoy_growth": pl.Float64,
    "yoy_growth": pl.Float64,
    "mom_growth": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}
SEMICONDUCTOR_LEAD_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "tsmc_revenue_ntd_million": pl.Float64,
    "tsmc_revenue_usd_million": pl.Float64,
    "tsmc_revenue_yoy": pl.Float64,
    "tsmc_revenue_mom": pl.Float64,
    "tsmc_revenue_3mma_usd": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

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

SEMICONDUCTOR_EQUIPMENT_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "billings_3mma_jpy": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

FOUNDRY_RAW_SCHEMA = {
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "tsmc_utilization_raw": pl.String,
    "tsmc_wafer_shipments_12in_kpcs_raw": pl.String,
    "tsmc_capacity_12in_kpcs_raw": pl.String,
    "tsmc_utilization_status": pl.String,
    "smic_utilization_raw": pl.String,
    "smic_monthly_capacity_raw": pl.String,
    "smic_wafer_shipment_raw": pl.String,
    "smic_utilization_status": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
    "tsmc_source_url": pl.String,
    "tsmc_release_date": pl.Date,
    "tsmc_raw_content_sha256": pl.String,
    "tsmc_raw_snapshot_path": pl.String,
    "smic_source_url": pl.String,
    "smic_release_date": pl.Date,
    "smic_raw_content_sha256": pl.String,
    "smic_raw_snapshot_path": pl.String,
}

FOUNDRY_CURATED_SCHEMA = {
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "tsmc_utilization_pct": pl.Float64,
    "tsmc_wafer_shipments_12in_kpcs": pl.Float64,
    "tsmc_capacity_12in_kpcs": pl.Float64,
    "tsmc_utilization_status": pl.String,
    "smic_utilization_pct": pl.Float64,
    "smic_monthly_capacity_8inch_kw": pl.Float64,
    "smic_wafer_shipment_kw": pl.Float64,
    "smic_utilization_status": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "tsmc_source_url": pl.String,
    "tsmc_release_date": pl.Date,
    "smic_source_url": pl.String,
    "smic_release_date": pl.Date,
    "foundry_proxy_utilization_pct": pl.Float64,
    "foundry_weighted_utilization_pct": pl.Float64,
    "proxy_method": pl.String,
    "proxy_status": pl.String,
    "utilization_regime": pl.String,
}

SEMICONDUCTOR_SALES_RAW_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "worldwide_raw": pl.String,
    "americas_raw": pl.String,
    "europe_raw": pl.String,
    "japan_raw": pl.String,
    "asia_pacific_raw": pl.String,
    "china_sales_raw": pl.String,
    "china_yoy_growth_raw": pl.String,
    "china_mom_growth_raw": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

SEMICONDUCTOR_LEAD_RAW_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "month_raw": pl.String,
    "net_revenue_raw": pl.String,
    "yoy_change_raw": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

CHIP_LEAD_TIME_RAW_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "lead_time_raw": pl.String,
    "sku_details_raw": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "sales_3mma_raw": pl.String,
    "mom_growth_3mma_raw": pl.String,
    "yoy_growth_3mma_raw": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

SEMI_EQUIPMENT_RAW_SCHEMA = {
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "source_record_type": pl.String,
    "report_year": pl.String,
    "global_billings_raw": pl.String,
    "china_billings_raw": pl.String,
    "annual_billings_raw": pl.String,
    "yoy_growth_raw": pl.String,
    "qoq_growth_raw": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

SEMI_EQUIPMENT_CURATED_SCHEMA = {
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "global_billings_billion_usd": pl.Float64,
    "china_billings_billion_usd": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "yoy_growth": pl.Float64,
    "qoq_growth": pl.Float64,
    "china_share_pct": pl.Float64,
}

INVENTORY_RAW_SCHEMA = {
    "symbol": pl.String,
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "subsector": pl.String,
    "source_period_end": pl.Date,
    "fiscal_period_raw": pl.String,
    "inventory_usd_raw": pl.String,
    "cost_of_revenue_usd_raw": pl.String,
    "cost_of_revenue_annual_raw": pl.String,
    "cost_of_revenue_derivation": pl.String,
    "ds_revenue_krw_raw": pl.String,
    "ds_operating_profit_krw_raw": pl.String,
    "cost_of_revenue_source": pl.String,
    "inventory_scope": pl.String,
    "memory_inventory_status": pl.String,
    "release_date": pl.Date,
    "source": pl.String,
    "source_url": pl.String,
    "unit": pl.String,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

INVENTORY_CURATED_SCHEMA = {
    "symbol": pl.String,
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "inventory_usd_million": pl.Float64,
    "cost_of_revenue_usd_million": pl.Float64,
    "cost_of_revenue_source": pl.String,
    "inventory_scope": pl.String,
    "memory_inventory_status": pl.String,
    "release_date": pl.Date,
    "source": pl.String,
    "unit": pl.String,
    "data_status": pl.String,
    "collected_at": pl.String,
    "doi_days": pl.Float64,
    "total_inventory_usd_million": pl.Float64,
    "total_cost_of_revenue_usd_million": pl.Float64,
    "idm_equal_doi_days": pl.Float64,
    "idm_weighted_doi_days": pl.Float64,
    "inventory_regime": pl.String,
    "subsector": pl.String,
    "analog_weighted_doi_days": pl.Float64,
    "memory_weighted_doi_days": pl.Float64,
}

CHANNEL_INVENTORY_RAW_SCHEMA = {
    "company": pl.String,
    "symbol": pl.String,
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "fiscal_year_raw": pl.String,
    "fiscal_period_raw": pl.String,
    "inventory_usd_raw": pl.String,
    "cost_of_revenue_usd_raw": pl.String,
    "form_raw": pl.String,
    "accession_raw": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

CHANNEL_INVENTORY_CURATED_SCHEMA = {
    "company": pl.String,
    "symbol": pl.String,
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "inventory_usd_million": pl.Float64,
    "cost_of_revenue_usd_million": pl.Float64,
    "channel_doi_days": pl.Float64,
    "channel_total_inventory_usd_million": pl.Float64,
    "channel_total_cost_of_revenue_usd_million": pl.Float64,
    "channel_equal_doi_days": pl.Float64,
    "channel_weighted_doi_days": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

MEMORY_PRICE_RAW_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "updated_at_raw": pl.String,
    "product_family": pl.String,
    "price_scope": pl.String,
    "page_slug": pl.String,
    "table_index": pl.Int64,
    "table_title": pl.String,
    "item_raw": pl.String,
    "daily_high_raw": pl.String,
    "daily_low_raw": pl.String,
    "session_high_raw": pl.String,
    "session_low_raw": pl.String,
    "session_average_raw": pl.String,
    "high_raw": pl.String,
    "low_raw": pl.String,
    "average_raw": pl.String,
    "session_change_raw": pl.String,
    "average_change_raw": pl.String,
    "low_change_raw": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

MEMORY_PRICE_CURATED_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "updated_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "product_family": pl.String,
    "price_scope": pl.String,
    "page_slug": pl.String,
    "table_index": pl.Int64,
    "table_title": pl.String,
    "item": pl.String,
    "daily_high_usd": pl.Float64,
    "daily_low_usd": pl.Float64,
    "session_high_usd": pl.Float64,
    "session_low_usd": pl.Float64,
    "session_average_usd": pl.Float64,
    "high_usd": pl.Float64,
    "low_usd": pl.Float64,
    "average_usd": pl.Float64,
    "session_change": pl.Float64,
    "average_change": pl.Float64,
    "low_change": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

TSMC_ADV_PKG_REVENUE_RAW_SCHEMA = pl.Schema(
    {
        "symbol": pl.String,
        "report_quarter": pl.String,
        "trade_date": pl.Date,
        "release_date": pl.Date,
        "net_revenue_ntd_bn": pl.Float64,
        "net_revenue_usd_bn": pl.Float64,
        "advanced_wafer_pct": pl.Float64,
        "hpc_platform_pct": pl.Float64,
        "packaging_testing_others_pct": pl.Float64,
        "data_status": pl.String,
        "source": pl.String,
        "source_url": pl.String,
        "collected_at": pl.String,
        "raw_content_sha256": pl.String,
        "raw_snapshot_path": pl.String,
    }
)

TSMC_ADV_PKG_REVENUE_CURATED_SCHEMA = pl.Schema(
    {
        "symbol": pl.String,
        "report_quarter": pl.String,
        "trade_date": pl.Date,
        "release_date": pl.Date,
        "net_revenue_ntd_bn": pl.Float64,
        "net_revenue_usd_bn": pl.Float64,
        "packaging_testing_others_ntd_bn": pl.Float64,
        "advanced_wafer_pct": pl.Float64,
        "hpc_platform_pct": pl.Float64,
        "packaging_testing_others_pct": pl.Float64,
        "revenue_yoy": pl.Float64,
        "revenue_qoq": pl.Float64,
        "unit": pl.String,
        "source": pl.String,
        "source_url": pl.String,
        "data_status": pl.String,
        "collected_at": pl.String,
    }
)

COWOS_CAPACITY_ESTIMATES_RAW_SCHEMA = pl.Schema(
    {
        "symbol": pl.String,
        "report_quarter": pl.String,
        "trade_date": pl.Date,
        "agency": pl.String,
        "published_date": pl.Date,
        "monthly_capacity_kwpm": pl.Float64,
        "lead_time_months": pl.Float64,
        "data_status": pl.String,
        "source": pl.String,
        "source_url": pl.String,
        "collected_at": pl.String,
        "raw_content_sha256": pl.String,
        "raw_snapshot_path": pl.String,
    }
)

COWOS_CAPACITY_ESTIMATES_CURATED_SCHEMA = pl.Schema(
    {
        "symbol": pl.String,
        "report_quarter": pl.String,
        "trade_date": pl.Date,
        "agency": pl.String,
        "published_date": pl.Date,
        "monthly_capacity_kwpm": pl.Float64,
        "lead_time_months": pl.Float64,
        "capacity_yoy": pl.Float64,
        "capacity_qoq": pl.Float64,
        "bottleneck_regime": pl.String,
        "unit": pl.String,
        "source": pl.String,
        "source_url": pl.String,
        "data_status": pl.String,
        "collected_at": pl.String,
    }
)

SEMICONDUCTOR_EQUIPMENT_GM_SCHEMA = pl.Schema(
    {
        "report_quarter": pl.String,
        "trade_date": pl.Date,
        "net_sales_eur_m": pl.Float64,
        "gross_profit_eur_m": pl.Float64,
        "gross_margin_pct": pl.Float64,
        "net_income_eur_m": pl.Float64,
        "ibm_sales_eur_m": pl.Float64,
        "new_litho_units": pl.Float64,
        "used_litho_units": pl.Float64,
        "net_bookings_eur_m": pl.Float64,
        "systems_backlog_eur_m": pl.Float64,
        "gm_guidance_next_pct": pl.Float64,
        "net_sales_guidance_next_eur_m": pl.Float64,
        "release_date": pl.Date,
        "source": pl.String,
        "source_url": pl.String,
        "data_status": pl.String,
        "collected_at": pl.String,
    }
)

SEMICONDUCTOR_EQUIPMENT_GM_MULTI_SCHEMA = pl.Schema(
    {
        "company": pl.String,
        "report_quarter": pl.String,
        "release_date": pl.Date,
        "gross_margin_pct": pl.Float64,
        "gm_guidance_next_pct": pl.Float64,
        "services_share_pct": pl.Float64,
        "source": pl.String,
        "data_status": pl.String,
    }
)

EQUIPMENT_GM_ATOMIC_SCHEMA = pl.Schema(
    {
        "company": pl.String,
        "report_quarter": pl.String,
        "report_period_end": pl.Date,
        "release_date": pl.Date,
        "gross_margin_pct": pl.Float64,
        "gm_guidance_next_pct": pl.Float64,
        "services_share_pct": pl.Float64,
        "source": pl.String,
        "data_status": pl.String,
    }
)

TEL_GM_QUARTERLY_SCHEMA = pl.Schema(
    {
        "company": pl.String,
        "report_quarter": pl.String,
        "fiscal_year": pl.Int64,
        "fy_q": pl.Int32,
        "period_end": pl.Date,
        "net_sales_jpy_m": pl.Float64,
        "gross_profit_jpy_m": pl.Float64,
        "gross_margin_pct": pl.Float64,
        "release_date": pl.Date,
        "file": pl.String,
    }
)
