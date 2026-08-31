"""垂直产业景气指标 2-Tier ETL 统一同步管道。"""

import logging
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.agriculture import (
    AgriculturePorkCollector,
    records_to_agriculture_pork_frame,
)
from stock_data.fetcher.industry.automotive import NevCollector, records_to_nev_frame
from stock_data.fetcher.industry.chemicals import (
    ChemicalsCollector,
    records_to_chemical_market_frame,
)
from stock_data.fetcher.industry.cloud import CloudCapexCollector, records_to_cloud_capex_frame
from stock_data.fetcher.industry.coal import (
    CoalMarketCollector,
    records_to_coal_market_frame,
)
from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.consumer import (
    LiquorWholesaleCollector,
    records_to_liquor_wholesale_frame,
)
from stock_data.fetcher.industry.customs import ComtradeCollector, records_to_customs_trade_frame
from stock_data.fetcher.industry.electronics import (
    ConsumerElectronicsCollector,
    records_to_consumer_electronics_frame,
)
from stock_data.fetcher.industry.machinery import MachineryCollector, records_to_machinery_frame
from stock_data.fetcher.industry.metals import NonFerrousCollector, records_to_metals_frame
from stock_data.fetcher.industry.pharma import PharmaBdCollector, records_to_pharma_bd_frame
from stock_data.fetcher.industry.power import (
    PvPriceChainCollector,
    SolarCollector,
    records_to_solar_frame,
    records_to_solar_price_chain_frame,
)
from stock_data.fetcher.industry.semiconductor import (
    ChipLeadTimeCollector,
    SemiconductorCollector,
    TsmcLeadCollector,
    records_to_chip_lead_time_frame,
    records_to_semiconductor_frame,
    records_to_semiconductor_lead_frame,
)
from stock_data.fetcher.industry.shipping import ShippingCollector, records_to_shipping_frame

logger = logging.getLogger(__name__)


def execute_single_industry_task(
    endpoint: str,
    start_date: date | None = None,
    end_date: date | None = None,
    force_refresh: bool = False,
    raw_dir: Path | str = "data/raw/industry",
    curated_dir: Path | str = "data/curated/industry",
) -> int:
    """执行单个垂直产业 Task 采集、清洗、增量合并与 Parquet 落盘。"""
    raw_path = Path(raw_dir)
    curated_path = Path(curated_dir)
    curated_path.mkdir(parents=True, exist_ok=True)

    if endpoint == "semiconductor_sales":
        rec_semi = SemiconductorCollector(raw_dir=raw_path).collect()
        if not rec_semi:
            return 0
        df = records_to_semiconductor_frame(rec_semi)
        count = save_curated_fact(df, curated_path / "semiconductor_sales.parquet")
        _backfill_semiconductor_china(curated_path)
        return count

    if endpoint == "nev_monthly_sales":
        rec_nev = NevCollector(raw_dir=raw_path).collect()
        if not rec_nev:
            return 0
        return save_curated_fact(
            records_to_nev_frame(rec_nev),
            curated_path / "nev_monthly_sales.parquet",
        )

    if endpoint == "solar_capacity":
        rec_solar = SolarCollector(raw_dir=raw_path).collect(force=force_refresh)
        if not rec_solar:
            return 0
        return save_curated_fact(
            records_to_solar_frame(rec_solar),
            curated_path / "solar_capacity.parquet",
        )

    if endpoint == "non_ferrous_metals":
        rec_metals = NonFerrousCollector(raw_dir=raw_path).collect()
        if not rec_metals:
            return 0
        return save_curated_fact(
            records_to_metals_frame(rec_metals),
            curated_path / "non_ferrous_metals.parquet",
            primary_keys=["trade_date"],
        )

    if endpoint == "pharma_license_out":
        rec_pharma = PharmaBdCollector(raw_dir=raw_path).collect()
        if not rec_pharma:
            return 0
        return save_curated_fact(
            records_to_pharma_bd_frame(rec_pharma),
            curated_path / "pharma_license_out.parquet",
            primary_keys=["report_month"],
        )

    if endpoint == "cloud_capex_quarterly":
        rec_capex = CloudCapexCollector(raw_dir=raw_path).collect()
        if not rec_capex:
            return 0
        return save_curated_fact(
            records_to_cloud_capex_frame(rec_capex),
            curated_path / "cloud_capex_quarterly.parquet",
            primary_keys=["report_quarter"],
        )

    if endpoint == "construction_machinery":
        rec_mach = MachineryCollector(raw_dir=raw_path).collect()
        if not rec_mach:
            return 0
        return save_curated_fact(
            records_to_machinery_frame(rec_mach),
            curated_path / "construction_machinery.parquet",
            primary_keys=["report_month"],
        )

    if endpoint == "shipping_indices":
        rec_ship = ShippingCollector(raw_dir=raw_path).collect()
        if not rec_ship:
            return 0
        return save_curated_fact(
            records_to_shipping_frame(rec_ship),
            curated_path / "shipping_indices.parquet",
            primary_keys=["trade_date"],
        )

    if endpoint == "customs_trade":
        comtrade_raw = raw_path / "customs" / "comtrade"
        start_m = start_date.strftime("%Y-%m") if start_date else None
        end_m = end_date.strftime("%Y-%m") if end_date else None
        rec_customs = ComtradeCollector(raw_dir=comtrade_raw).collect(
            start_month=start_m, end_month=end_m
        )
        if not rec_customs:
            return 0
        return save_curated_fact(
            records_to_customs_trade_frame(rec_customs),
            curated_path / "customs_trade.parquet",
            primary_keys=["product_key", "hs_code", "report_month"],
        )

    if endpoint == "semiconductor_lead":
        rec_tsmc = TsmcLeadCollector(raw_dir=raw_path).collect()
        if not rec_tsmc:
            return 0
        return save_curated_fact(
            records_to_semiconductor_lead_frame(rec_tsmc),
            curated_path / "semiconductor_lead.parquet",
            primary_keys=["report_month"],
        )

    if endpoint == "chip_lead_time":
        rec_clt = ChipLeadTimeCollector(raw_dir=raw_path).collect()
        if not rec_clt:
            return 0
        return save_curated_fact(
            records_to_chip_lead_time_frame(rec_clt),
            curated_path / "chip_lead_time.parquet",
            primary_keys=["report_month"],
        )

    if endpoint == "chemical_market":
        rec_chem = ChemicalsCollector(raw_dir=raw_path).collect(force=force_refresh)
        if not rec_chem:
            return 0
        return save_curated_fact(
            records_to_chemical_market_frame(rec_chem),
            curated_path / "chemical_market.parquet",
            primary_keys=["report_month"],
        )

    if endpoint == "solar_price_chain":
        rec_pv = PvPriceChainCollector(raw_dir=raw_path).collect(force=force_refresh)
        if not rec_pv:
            return 0
        return save_curated_fact(
            records_to_solar_price_chain_frame(rec_pv),
            curated_path / "solar_price_chain.parquet",
            primary_keys=["report_date"],
        )

    if endpoint == "agriculture_pork":
        rec_pork = AgriculturePorkCollector(raw_dir=raw_path).collect(force=force_refresh)
        if not rec_pork:
            return 0
        return save_curated_fact(
            records_to_agriculture_pork_frame(rec_pork),
            curated_path / "agriculture_pork.parquet",
            primary_keys=["report_month"],
        )

    if endpoint == "liquor_wholesale":
        rec_liquor = LiquorWholesaleCollector(raw_dir=raw_path).collect()
        if not rec_liquor:
            return 0
        return save_curated_fact(
            records_to_liquor_wholesale_frame(rec_liquor),
            curated_path / "liquor_wholesale.parquet",
            primary_keys=["report_date"],
        )

    if endpoint == "consumer_electronics":
        rec_elec = ConsumerElectronicsCollector(raw_dir=raw_path).collect(force=force_refresh)
        if not rec_elec:
            return 0
        return save_curated_fact(
            records_to_consumer_electronics_frame(rec_elec),
            curated_path / "consumer_electronics.parquet",
            primary_keys=["report_quarter"],
        )

    if endpoint == "coal_market":
        rec_coal = CoalMarketCollector(raw_dir=raw_path).collect(force=force_refresh)
        if not rec_coal:
            return 0
        return save_curated_fact(
            records_to_coal_market_frame(rec_coal),
            curated_path / "coal_market.parquet",
            primary_keys=["report_date"],
        )

    logger.warning("未知的垂直产业任务端点: %s", endpoint)
    return 0


def sync_all_industry_metrics(
    raw_dir: Path | str = "data/raw/industry",
    curated_dir: Path | str = "data/curated/industry",
    metrics: list[str] | None = None,
    bundle: str | None = None,
    force: bool = False,
    target_date: date | None = None,
    max_workers: int | None = None,
) -> dict[str, int]:
    """统一同步并落盘垂直产业黄金事实表 (支持任务包编排、并发线程池与智能跳过)。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from stock_data.core.task_bundles import expand_task_targets
    from stock_data.pipeline.sync import DailySyncEngine

    endpoints = list(metrics) if metrics else []
    if bundle:
        endpoints.extend(expand_task_targets("industry", [bundle]))

    engine = DailySyncEngine(data_source="industry", max_workers=max_workers)
    plan = engine.build_sync_plan(
        target_date=target_date,
        endpoints=endpoints if endpoints else None,
        force=force,
    )
    pending = [task for task in plan if task.status == "PENDING"]
    if not pending:
        return {}

    results: dict[str, int] = {}
    workers = min(engine.max_workers, len(pending))

    def _worker(task: object) -> tuple[str, int]:
        endpoint = getattr(task, "endpoint", "")
        start_d = getattr(task, "start_date", None)
        end_d = getattr(task, "end_date", None)
        refresh_raw = getattr(task, "refresh_raw_cache", False)
        c = execute_single_industry_task(
            endpoint=endpoint,
            start_date=start_d,
            end_date=end_d,
            force_refresh=force or refresh_raw,
            raw_dir=raw_dir,
            curated_dir=curated_dir,
        )
        return endpoint, c

    if workers <= 1:
        for task in pending:
            ep, count = _worker(task)
            if count > 0:
                results[ep] = count
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker, task) for task in pending]
            for fut in as_completed(futures):
                ep, count = fut.result()
                if count > 0:
                    results[ep] = count

    return results


def _backfill_semiconductor_china(curated_path: Path) -> int:
    """从 SIA raw 新闻重建 China 月度序列并回填 semiconductor_sales 黄金表。

    独立于主半导体采集 (WSTS 不含中国独立列): 失败仅告警, 不阻塞 pipeline。
    """
    try:
        from stock_data.fetcher.industry.semiconductor.china_series import (
            build_china_series,
            parse_sia_raw_dir,
            save_china_series,
        )

        raw_sia = curated_path.parent.parent / "raw" / "industry" / "sia"
        records = parse_sia_raw_dir(raw_sia)
        if not records:
            return 0
        series = build_china_series(records)
        if series.is_empty():
            return 0

        # 1. 保存独立的 semiconductor_china_series.parquet 黄金表
        save_china_series(series, curated_path / "semiconductor_china_series.parquet")

        # 2. 联合回填主表 semiconductor_sales.parquet
        sales_path = curated_path / "semiconductor_sales.parquet"
        sales = pl.read_parquet(sales_path)
        china_map = series.select(
            ["report_month", "china_sales_usd", "china_yoy_growth", "china_mom_growth"]
        ).rename(
            {
                "china_sales_usd": "_c_sales",
                "china_yoy_growth": "_c_yoy",
                "china_mom_growth": "_c_mom",
            }
        )
        merged = (
            sales.join(china_map, on="report_month", how="left")
            .with_columns(
                [
                    pl.coalesce([pl.col("_c_sales"), pl.col("china_sales_usd")]).alias(
                        "china_sales_usd"
                    ),
                    pl.coalesce([pl.col("_c_yoy"), pl.col("china_yoy_growth")]).alias(
                        "china_yoy_growth"
                    ),
                    pl.coalesce([pl.col("_c_mom"), pl.col("china_mom_growth")]).alias(
                        "china_mom_growth"
                    ),
                ]
            )
            .drop(["_c_sales", "_c_yoy", "_c_mom"])
        )
        merged.write_parquet(sales_path)
        filled = int(merged["china_sales_usd"].is_not_null().sum())
        logger.info("semiconductor_sales China 回填完成: %d 个月", filled)
        return filled
    except Exception as exc:  # noqa: BLE001
        logger.warning("semiconductor_sales China 回填失败 (非阻塞): %s", exc)
        return 0
