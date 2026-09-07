"""重放 data/raw/industry 全部 RAW 数据到 Curated 黄金表 (离线, 不触发任何在线采集)。

背景: 采集器已统一为纯在线模式 (collect 不再读取本地 RAW CSV)。本脚本直接从现有
RAW 快照 (CSV / WSTS Excel / SEC EDGAR JSON / UN Comtrade JSON+GACC CSV) 重建/合并
16 张产业黄金事实表, 供手工回放或审计对账使用。

China 月度销售额序列 (semiconductor_china_series): 由 SIA raw 新闻重建, 并在
semiconductor_sales 重放后回填其 china_sales_usd 列 (两表一致性由 post_process 保证)。

用法:
    uv run python scripts/replay_industry_raw.py                # 全量重放
    uv run python scripts/replay_industry_raw.py --metric coal_market   # 单指标
    uv run python scripts/replay_industry_raw.py --dry-run      # 只预览不落盘
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.cloud.collector import CSP_CIK_MAP
from stock_data.fetcher.industry.cloud.parser import extract_sec_quarterly_capex
from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.semiconductor import (
    ChipLeadTimeCollector,
    records_to_chip_lead_time_frame,
)
from stock_data.fetcher.industry.semiconductor.china_series import (
    build_china_series,
    parse_sia_raw_dir,
)

logger = logging.getLogger(__name__)

RAW_ROOT = Path("data/raw/industry")
CURATED_ROOT = Path("data/curated/industry")


def _load_sia_china_records(raw_root: Path) -> list[dict[str, object]]:
    """从 SIA raw 新闻目录解析全部 China YoY/MoM 与年度锚点记录。"""
    sia_dir = Path(raw_root) / "sia"
    if not sia_dir.exists():
        return []
    return parse_sia_raw_dir(sia_dir)


def _to_china_series_frame(records: list[dict[str, object]]) -> pl.DataFrame:
    """将 SIA China 记录重建为连续月度推算序列。"""
    return build_china_series(records)


def _backfill_china_into_sales(curated_root: Path, series_path: Path, dry_run: bool = False) -> int:
    """将推算的 china_sales_usd 与增速回填到 semiconductor_sales 黄金表。"""
    sales_path = Path(curated_root) / "semiconductor_sales.parquet"
    if not series_path.exists() or not sales_path.exists():
        logger.info("[semiconductor_china_series] 依赖表缺失, 跳过回填")
        return 0
    series = pl.read_parquet(series_path)
    if series.is_empty():
        return 0
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
    if dry_run:
        filled = merged["china_sales_usd"].is_not_null().sum()
        logger.info(
            "[semiconductor_china_series] dry-run: 回填 %s 后 china_sales_usd 非空 %d 行",
            sales_path.name,
            filled,
        )
        return filled
    merged.write_parquet(sales_path)
    filled = merged["china_sales_usd"].is_not_null().sum()
    logger.info(
        "[semiconductor_china_series] 回填 %s 完成: china_sales_usd 非空 %d 行",
        sales_path.name,
        filled,
    )
    return filled


def _load_cloud_capex_from_raw(raw_root: Path) -> list[Any]:
    """从 SEC EDGAR JSON 缓存提取四家云厂商季度 CapEx 并构造记录 (参照 CloudCapexCollector.collect)。"""
    from stock_data.fetcher.industry.models import CloudCapexRecord

    company_data: dict[str, dict[str, float]] = {}
    for ticker in CSP_CIK_MAP:
        raw_file = raw_root / "cloud" / "sec_edgar" / f"{ticker}.json.gz"
        if not raw_file.exists():
            continue
        try:
            with gzip.open(raw_file, "rt", encoding="utf-8") as f:
                facts = json.load(f)
            company_data[ticker] = extract_sec_quarterly_capex(facts, ticker)
        except Exception as e:  # noqa: BLE001
            logger.warning("解析 SEC 快照失败 [%s]: %s", raw_file.name, e)

    if not company_data:
        return []

    all_quarters = sorted(
        {q for data in company_data.values() for q, v in data.items() if v > 0 and q >= "2018-Q1"}
    )
    records: list[CloudCapexRecord] = []
    for q_str in all_quarters:
        year, q_num = int(q_str.split("-Q")[0]), int(q_str.split("-Q")[1])
        month = q_num * 3
        t_date = date(year, month, 1)
        import calendar

        t_date = date(year, month, calendar.monthrange(year, month)[1])
        msft = company_data.get("MSFT", {}).get(q_str, 0.0)
        goog = company_data.get("GOOGL", {}).get(q_str, 0.0)
        meta = company_data.get("META", {}).get(q_str, 0.0)
        amzn = company_data.get("AMZN", {}).get(q_str, 0.0)
        records.append(
            CloudCapexRecord(
                report_quarter=q_str,
                trade_date=t_date,
                total_capex_billion_usd=round(msft + goog + meta + amzn, 3),
                msft_capex_billion_usd=round(msft, 3) if msft > 0 else None,
                goog_capex_billion_usd=round(goog, 3) if goog > 0 else None,
                meta_capex_billion_usd=round(meta, 3) if meta > 0 else None,
                amzn_capex_billion_usd=round(amzn, 3) if amzn > 0 else None,
                unit="billion_usd",
                source="SEC_EDGAR_10Q",
                source_url="https://www.sec.gov/edgar/",
                release_date=None,
                data_status="actual",
                collected_at="",
            )
        )
    return records


def _load_customs_from_raw(raw_root: Path) -> list[Any]:
    """从 UN Comtrade JSON 快照 + GACC CSV 聚合海关贸易记录 (GACC 优先去重)。"""
    from stock_data.fetcher.industry.customs.collectors.comtrade import ComtradeCollector
    from stock_data.fetcher.industry.models import CustomsTradeRecord

    comtrade_dir = raw_root / "customs" / "comtrade"
    if not comtrade_dir.exists():
        return []
    collector = ComtradeCollector(raw_dir=comtrade_dir)

    records: list[CustomsTradeRecord] = []
    json_files = sorted(comtrade_dir.glob("*.json.gz")) + sorted(comtrade_dir.glob("*.json"))
    for f in json_files:
        try:
            records.extend(collector.load_from_raw_json(f))
        except Exception as e:  # noqa: BLE001
            logger.warning("解析 UN Comtrade 快照失败 [%s]: %s", f.name, e)
    for f in sorted(comtrade_dir.glob("*.csv")):
        try:
            records.extend(collector.load_from_raw_csv(f))
        except Exception as e:  # noqa: BLE001
            logger.warning("解析 GACC 快照失败 [%s]: %s", f.name, e)

    dedup: dict[tuple[str, str, str, str], CustomsTradeRecord] = {}
    for r in records:
        key = (r.product_key, r.hs_code, r.report_month, r.trade_direction)
        if key not in dedup or (dedup[key].source == "UN_Comtrade" and r.source == "GACC"):
            dedup[key] = r
    return list(dedup.values())


def _load_wsts_semiconductor(raw_root: Path) -> list[Any]:
    """从 WSTS Historical Billings Excel 缓存解析全球半导体月度销售额底表。"""
    from stock_data.fetcher.industry.semiconductor.collector import parse_wsts_excel_file

    excel_files = sorted((raw_root / "sia").glob("WSTS-Historical-Billings-Report-*.xlsx"))
    if not excel_files:
        return []
    return list(parse_wsts_excel_file(excel_files[-1]))


# metric -> (加载函数, records_to_frame 函数, curated 文件名, 主键)
def _build_metric_plan() -> dict[str, dict[str, Any]]:
    from stock_data.fetcher.industry.agriculture.collector import AgriculturePorkCollector
    from stock_data.fetcher.industry.agriculture.transform import records_to_agriculture_pork_frame
    from stock_data.fetcher.industry.automotive.collector import NevCollector
    from stock_data.fetcher.industry.automotive.transform import records_to_nev_frame
    from stock_data.fetcher.industry.chemicals.collector import ChemicalsCollector
    from stock_data.fetcher.industry.chemicals.transform import records_to_chemical_market_frame
    from stock_data.fetcher.industry.cloud.transform import records_to_cloud_capex_frame
    from stock_data.fetcher.industry.coal.collector import CoalMarketCollector
    from stock_data.fetcher.industry.coal.transform import records_to_coal_market_frame
    from stock_data.fetcher.industry.consumer.collector import LiquorWholesaleCollector
    from stock_data.fetcher.industry.consumer.transform import records_to_liquor_wholesale_frame
    from stock_data.fetcher.industry.customs.transforms.customs_trade import records_to_customs_trade_frame
    from stock_data.fetcher.industry.electronics.collector import ConsumerElectronicsCollector
    from stock_data.fetcher.industry.electronics.transform import (
        records_to_consumer_electronics_frame,
    )
    from stock_data.fetcher.industry.machinery.collector import MachineryCollector
    from stock_data.fetcher.industry.machinery.transform import records_to_machinery_frame
    from stock_data.fetcher.industry.metals.collector import NonFerrousCollector
    from stock_data.fetcher.industry.metals.transform import records_to_metals_frame
    from stock_data.fetcher.industry.pharma.collector import PharmaBdCollector
    from stock_data.fetcher.industry.pharma.transform import records_to_pharma_bd_frame
    from stock_data.fetcher.industry.power.collector import SolarCollector
    from stock_data.fetcher.industry.power.pv_price_collector import PvPriceChainCollector
    from stock_data.fetcher.industry.power.transform import (
        records_to_solar_frame,
        records_to_solar_price_chain_frame,
    )
    from stock_data.fetcher.industry.semiconductor.transform import (
        records_to_semiconductor_frame,
        records_to_semiconductor_lead_frame,
    )
    from stock_data.fetcher.industry.semiconductor.tsmc_collector import TsmcLeadCollector
    from stock_data.fetcher.industry.shipping.collector import ShippingCollector
    from stock_data.fetcher.industry.shipping.transform import records_to_shipping_frame

    def _csv_loader(collector_cls: type, rel_path: str) -> Any:
        def loader(raw_root: Path) -> list[Any]:
            collector = collector_cls(raw_dir=raw_root)
            return list(collector.load_from_raw_csv(raw_root / rel_path))

        return loader

    return {
        "semiconductor_sales": {
            "loader": _load_wsts_semiconductor,
            "to_frame": records_to_semiconductor_frame,
            "curated": "semiconductor_sales.parquet",
            "primary_keys": None,
        },
        "nev_monthly_sales": {
            "loader": _csv_loader(NevCollector, "cpca/nev_sales_real.csv"),
            "to_frame": records_to_nev_frame,
            "curated": "nev_monthly_sales.parquet",
            "primary_keys": None,
        },
        "solar_capacity": {
            "loader": _csv_loader(SolarCollector, "energy/cn_nea/solar_capacity.csv"),
            "to_frame": records_to_solar_frame,
            "curated": "solar_capacity.parquet",
            "primary_keys": None,
        },
        "non_ferrous_metals": {
            "loader": _csv_loader(NonFerrousCollector, "metals/commodity_prices.csv"),
            "to_frame": records_to_metals_frame,
            "curated": "non_ferrous_metals.parquet",
            "primary_keys": ["trade_date"],
        },
        "pharma_license_out": {
            "loader": _csv_loader(PharmaBdCollector, "pharma/license_out_monthly.csv"),
            "to_frame": records_to_pharma_bd_frame,
            "curated": "pharma_license_out.parquet",
            "primary_keys": ["report_month"],
        },
        "cloud_capex_quarterly": {
            "loader": _load_cloud_capex_from_raw,
            "to_frame": records_to_cloud_capex_frame,
            "curated": "cloud_capex_quarterly.parquet",
            "primary_keys": ["report_quarter"],
        },
        "construction_machinery": {
            "loader": _csv_loader(MachineryCollector, "machinery/excavator_monthly.csv"),
            "to_frame": records_to_machinery_frame,
            "curated": "construction_machinery.parquet",
            "primary_keys": ["report_month"],
        },
        "shipping_indices": {
            "loader": _csv_loader(ShippingCollector, "shipping/freight_indices_real.csv"),
            "to_frame": records_to_shipping_frame,
            "curated": "shipping_indices.parquet",
            "primary_keys": ["trade_date"],
        },
        "customs_trade": {
            "loader": _load_customs_from_raw,
            "to_frame": records_to_customs_trade_frame,
            "curated": "customs_trade.parquet",
            "primary_keys": ["product_key", "hs_code", "report_month"],
        },
        "semiconductor_lead": {
            "loader": _csv_loader(TsmcLeadCollector, "semiconductor/tsmc_monthly.csv"),
            "to_frame": records_to_semiconductor_lead_frame,
            "curated": "semiconductor_lead.parquet",
            "primary_keys": ["report_month"],
        },
        "chemical_market": {
            "loader": _csv_loader(ChemicalsCollector, "chemicals/chemical_operating_spreads.csv"),
            "to_frame": records_to_chemical_market_frame,
            "curated": "chemical_market.parquet",
            "primary_keys": ["report_month"],
        },
        "solar_price_chain": {
            "loader": _csv_loader(PvPriceChainCollector, "energy/pv_price_chain_weekly.csv"),
            "to_frame": records_to_solar_price_chain_frame,
            "curated": "solar_price_chain.parquet",
            "primary_keys": ["report_date"],
        },
        "agriculture_pork": {
            "loader": _csv_loader(
                AgriculturePorkCollector, "agriculture/pork_capacity_monthly.csv"
            ),
            "to_frame": records_to_agriculture_pork_frame,
            "curated": "agriculture_pork.parquet",
            "primary_keys": ["report_month"],
        },
        "liquor_wholesale": {
            "loader": _csv_loader(LiquorWholesaleCollector, "consumer/liquor_wholesale_weekly.csv"),
            "to_frame": records_to_liquor_wholesale_frame,
            "curated": "liquor_wholesale.parquet",
            "primary_keys": ["report_date"],
        },
        "consumer_electronics": {
            "loader": _csv_loader(
                ConsumerElectronicsCollector, "electronics/electronics_shipments_quarterly.csv"
            ),
            "to_frame": records_to_consumer_electronics_frame,
            "curated": "consumer_electronics.parquet",
            "primary_keys": ["report_quarter"],
        },
        "coal_market": {
            "loader": _csv_loader(CoalMarketCollector, "energy/coal_market_weekly.csv"),
            "to_frame": records_to_coal_market_frame,
            "curated": "coal_market.parquet",
            "primary_keys": ["report_date"],
        },
        "chip_lead_time": {
            "loader": lambda raw_root: ChipLeadTimeCollector(
                raw_dir=raw_root
            ).load_from_raw_snapshots(),
            "to_frame": records_to_chip_lead_time_frame,
            "curated": "chip_lead_time.parquet",
            "primary_keys": ["report_month"],
        },
        "semiconductor": {"_skip": True},  # 占位防误用 (semiconductor_sales 已覆盖)
        "semiconductor_china_series": {
            "loader": _load_sia_china_records,
            "to_frame": _to_china_series_frame,
            "curated": "semiconductor_china_series.parquet",
            "primary_keys": None,
            "post_process": _backfill_china_into_sales,
        },
    }


def replay_metric(
    metric: str,
    plan: dict[str, Any],
    raw_root: Path,
    curated_root: Path,
    dry_run: bool = False,
) -> int:
    """重放单个指标: 读 RAW -> transform -> 合并落盘 Curated, 返回处理记录数。"""
    loader = plan["loader"]
    to_frame = plan["to_frame"]
    curated_file = curated_root / plan["curated"]

    records = loader(raw_root)
    if not records:
        logger.info("[%s] RAW 无数据, 跳过", metric)
        return 0

    df = to_frame(records)
    if dry_run:
        logger.info(
            "[%s] dry-run: RAW %d 条 -> 目标 %s (去重后 %d 行)",
            metric,
            len(records),
            plan["curated"],
            df.height,
        )
        post = plan.get("post_process")
        if post is not None:
            post(curated_root, curated_root / plan["curated"], dry_run=True)
        return len(records)

    curated_root.mkdir(parents=True, exist_ok=True)
    total = save_curated_fact(df, curated_file, primary_keys=plan["primary_keys"])
    logger.info(
        "[%s] 重放完成: RAW %d 条 -> %s 共 %d 行", metric, len(records), plan["curated"], total
    )

    # 后处理钩子 (如 China 序列回填 semiconductor_sales)
    post = plan.get("post_process")
    if post is not None:
        post(curated_root, curated_file, dry_run=False)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="重放 data/raw/industry RAW 数据到 Curated 黄金表")
    parser.add_argument("--metric", help="只重放指定指标 (默认全量)")
    parser.add_argument("--dry-run", action="store_true", help="只预览处理数量, 不落盘")
    parser.add_argument("--raw-root", default=str(RAW_ROOT), help="RAW 根目录")
    parser.add_argument("--curated-root", default=str(CURATED_ROOT), help="Curated 根目录")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    plan = _build_metric_plan()
    plan.pop("semiconductor", None)
    if args.metric:
        if args.metric not in plan:
            logger.error("未知指标: %s (可选: %s)", args.metric, ", ".join(sorted(plan)))
            raise SystemExit(1)
        plan = {args.metric: plan[args.metric]}

    raw_root = Path(args.raw_root)
    curated_root = Path(args.curated_root)
    total_records = 0
    # 依赖顺序: semiconductor_sales 需先于 semiconductor_china_series (China 回填其 china 列)
    ordered = sorted(plan)
    if "semiconductor_china_series" in plan and "semiconductor_sales" in plan:
        ordered.remove("semiconductor_china_series")
        ordered.insert(ordered.index("semiconductor_sales") + 1, "semiconductor_china_series")
    for metric in ordered:
        total_records += replay_metric(metric, plan[metric], raw_root, curated_root, args.dry_run)

    mode = "dry-run 预览" if args.dry_run else "重放"
    logger.info("全部完成: %s %d 个指标, 共处理 %d 条 RAW 记录", mode, len(plan), total_records)


if __name__ == "__main__":
    main()
