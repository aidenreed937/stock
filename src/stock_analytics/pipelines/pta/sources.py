"""PTA 全景对账管线数据源契约与加载器。

负责从本地 Curated 数据层和 YAML 配置文件装配原始事实表。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

import polars as pl
import yaml

from stock_analytics.marts.pta_company_panel import (
    build_pta_company_panel,
)

logger = logging.getLogger(__name__)


class DatasetReader(Protocol):
    """支持 load_dataset 契约的数据集读取协议。"""

    def load_dataset(self, dataset: str) -> pl.DataFrame: ...


def load_capacity_projects(config_path: Path | str) -> list[dict[str, Any]]:
    """加载 PTA 重大产能事件种子库。"""
    p = Path(config_path)
    if not p.exists():
        fallback = Path("config/industry/chemicals/pta/capacity_projects.yaml")
        if fallback.exists():
            p = fallback
        else:
            return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return list(data.get("projects", []))
    except Exception as exc:
        logger.warning(f"加载产能事件库失败: {exc}")
        return []


def load_pta_output(
    catalog: DatasetReader, dataset_name: str = "chemical_capacity_utilization_10y"
) -> pl.DataFrame:
    """加载 PTA 月度实物产量与名义利用率 (TA)。"""
    try:
        df = catalog.load_dataset(dataset_name)
        if df.is_empty():
            return pl.DataFrame()
        if "product_name" in df.columns:
            df = df.filter(pl.col("product_name") == "PTA")
        elif "symbol" in df.columns:
            df = df.filter(pl.col("symbol") == "TA")
        if "trade_date" in df.columns:
            df = df.with_columns(
                pl.col("trade_date").cast(pl.Utf8).str.slice(0, 7).alias("report_month")
            )
        elif "report_date" in df.columns:
            df = df.with_columns(
                pl.col("report_date").cast(pl.Utf8).str.slice(0, 7).alias("report_month")
            )
        return df.sort("report_month")
    except Exception as exc:
        logger.warning(f"加载 PTA 实物产量失败: {exc}")
        return pl.DataFrame()


def load_synthetic_fiber(
    catalog: DatasetReader,
    dataset_name: str = "chemical_capacity_utilization_10y",
    fallback_dataset: str | None = "chemical_market",
) -> pl.DataFrame:
    """加载 NBS 下游合成纤维/化纤月度实物产量 (优先采用包含 1-2 月天数加权拆分的官方底表)。"""
    for dname in (dataset_name, fallback_dataset):
        if not dname:
            continue
        try:
            df = catalog.load_dataset(dname)
            if df.is_empty():
                continue
            if "product_name" in df.columns:
                sub = df.filter(pl.col("product_name") == "合成纤维")
                if not sub.is_empty() and "actual_output_w_tons" in sub.columns:
                    if "trade_date" in sub.columns:
                        sub = sub.with_columns(
                            pl.col("trade_date").cast(pl.Utf8).str.slice(0, 7).alias("report_month")
                        )
                    elif "report_date" in sub.columns:
                        sub = sub.with_columns(
                            pl.col("report_date")
                            .cast(pl.Utf8)
                            .str.slice(0, 7)
                            .alias("report_month")
                        )
                    return sub.select(
                        [
                            "report_month",
                            pl.col("actual_output_w_tons").alias("synthetic_fiber_production"),
                        ]
                    ).sort("report_month")
            if "synthetic_fiber_production" in df.columns:
                if "report_month" not in df.columns:
                    if "trade_date" in df.columns:
                        df = df.with_columns(
                            pl.col("trade_date").cast(pl.Utf8).str.slice(0, 7).alias("report_month")
                        )
                    elif "report_date" in df.columns:
                        df = df.with_columns(
                            pl.col("report_date")
                            .cast(pl.Utf8)
                            .str.slice(0, 7)
                            .alias("report_month")
                        )
                return df.select(["report_month", "synthetic_fiber_production"]).sort(
                    "report_month"
                )
        except Exception as exc:
            logger.debug(f"从 {dname} 加载合成纤维产量失败: {exc}")
    logger.warning("加载合成纤维产量失败: 所有源均不可用")
    return pl.DataFrame()


def load_warehouse_receipts(
    catalog: DatasetReader, dataset_name: str = "futures_inventory"
) -> pl.DataFrame:
    """加载郑商所 CZCE PTA (TA) 注册仓单历史日频与月末快照。"""
    try:
        df = catalog.load_dataset(dataset_name)
        if df.is_empty():
            return pl.DataFrame()
        if "symbol" in df.columns:
            df = df.filter(pl.col("symbol") == "TA")
        if "trade_date" in df.columns:
            df = df.with_columns(
                pl.col("trade_date").cast(pl.Utf8).str.slice(0, 7).alias("report_month")
            )
            qty_col = (
                "inventory"
                if "inventory" in df.columns
                else ("receipt_qty" if "receipt_qty" in df.columns else None)
            )
            if qty_col is not None:
                monthly = (
                    df.sort("trade_date")
                    .group_by("report_month")
                    .last()
                    .select(["report_month", pl.col(qty_col).alias("warehouse_receipt_month_end")])
                    .sort("report_month")
                )
                return monthly
        return pl.DataFrame()
    except Exception as exc:
        logger.warning(f"加载郑商所 PTA 仓单失败: {exc}")
        return pl.DataFrame()


def load_futures_daily(
    catalog: DatasetReader, dataset_name: str = "chemical_futures_daily"
) -> pl.DataFrame:
    """加载郑商所 PTA 主力合约日频行情并聚合月度价格。"""
    try:
        df = catalog.load_dataset(dataset_name)
        if df.is_empty():
            return pl.DataFrame()
        if "symbol" in df.columns:
            df = df.filter(pl.col("symbol") == "TA")
        if "trade_date" in df.columns and "close" in df.columns:
            df = df.with_columns(
                pl.col("trade_date").cast(pl.Utf8).str.slice(0, 7).alias("report_month")
            )
            monthly = (
                df.group_by("report_month")
                .agg(
                    [
                        pl.col("close").mean().alias("futures_close_monthly_avg"),
                        pl.col("close").last().alias("futures_close_month_end"),
                    ]
                )
                .sort("report_month")
            )
            return monthly
        return pl.DataFrame()
    except Exception as exc:
        logger.warning(f"加载 PTA 期货行情失败: {exc}")
        return pl.DataFrame()


def load_spot_price(
    catalog: DatasetReader, dataset_name: str = "chemical_spot_price"
) -> pl.DataFrame:
    """加载生意社 100ppi PTA 现货基准出厂价并聚合月度均价。"""
    try:
        df = catalog.load_dataset(dataset_name)
        if df.is_empty():
            return pl.DataFrame()
        if "symbol" in df.columns:
            df = df.filter(pl.col("symbol") == "TA")
        if "trade_date" in df.columns and "spot_price_cny" in df.columns:
            df = df.with_columns(
                pl.col("trade_date").cast(pl.Utf8).str.slice(0, 7).alias("report_month")
            )
            monthly = (
                df.group_by("report_month")
                .agg(
                    [
                        pl.col("spot_price_cny").mean().alias("spot_price_monthly_avg"),
                        pl.col("spot_price_cny").last().alias("spot_price_month_end"),
                    ]
                )
                .sort("report_month")
            )
            return monthly
        return pl.DataFrame()
    except Exception as exc:
        logger.warning(f"加载 PTA 现货出厂价失败: {exc}")
        return pl.DataFrame()


def load_spreads(catalog: DatasetReader, dataset_name: str = "chemical_spreads") -> pl.DataFrame:
    """加载 PTA 与下游涤纶长丝 POY 理论加工费并聚合成月度均值。"""
    try:
        df = catalog.load_dataset(dataset_name)
        if df.is_empty() or "trade_date" not in df.columns or "spread_margin_cny" not in df.columns:
            return pl.DataFrame()

        df = df.with_columns(
            pl.col("trade_date").cast(pl.Utf8).str.slice(0, 7).alias("report_month")
        )

        # 1. 上游 PTA 加工差
        pta_sub = df.filter(pl.col("symbol") == "TA") if "symbol" in df.columns else pl.DataFrame()
        if not pta_sub.is_empty():
            pta_monthly = pta_sub.group_by("report_month").agg(
                [
                    pl.col("spread_margin_cny").mean().alias("spread_margin_monthly_avg"),
                    pl.col("spread_margin_cny").last().alias("spread_margin_month_end"),
                ]
            )
        else:
            pta_monthly = pl.DataFrame(
                schema={
                    "report_month": pl.Utf8,
                    "spread_margin_monthly_avg": pl.Float64,
                    "spread_margin_month_end": pl.Float64,
                }
            )

        # 2. 下游 POY 涤纶长丝加工差
        poy_sub = df.filter(pl.col("symbol") == "POY") if "symbol" in df.columns else pl.DataFrame()
        if not poy_sub.is_empty():
            poy_monthly = poy_sub.group_by("report_month").agg(
                [
                    pl.col("spread_margin_cny").mean().alias("poy_spread_monthly_avg"),
                    pl.col("spread_margin_cny").last().alias("poy_spread_month_end"),
                ]
            )
            result = pta_monthly.join(poy_monthly, on="report_month", how="full")
        else:
            result = pta_monthly.with_columns(
                [
                    pl.lit(None).cast(pl.Float64).alias("poy_spread_monthly_avg"),
                    pl.lit(None).cast(pl.Float64).alias("poy_spread_month_end"),
                ]
            )

        return result.sort("report_month")
    except Exception as exc:
        logger.warning(f"加载产业链加工差失败: {exc}")
        return pl.DataFrame()


def load_customs_export(
    catalog: DatasetReader,
    dataset_name: str = "customs_trade_gacc",
    fallback_dataset: str | None = None,
) -> pl.DataFrame:
    """加载 GACC 海关聚酯/化纤商品出口月度实物量 (万吨)。"""
    datasets = [d for d in (dataset_name, fallback_dataset) if d]
    for ds in datasets:
        try:
            df = catalog.load_dataset(ds)
            if df.is_empty():
                continue

            sub = pl.DataFrame()
            # 1. 优先采用 product_key 精准筛选聚酯化纤大类 (长丝 + 短纤)
            if "product_key" in df.columns:
                sub = df.filter(
                    pl.col("product_key").is_in(["polyester_filament", "polyester_staple"])
                )

            # 2. 次选 hs_code 筛选
            if sub.is_empty() and "hs_code" in df.columns:
                sub = df.filter(
                    pl.col("hs_code").cast(pl.Utf8).str.starts_with("5402")
                    | pl.col("hs_code").cast(pl.Utf8).str.starts_with("55032")
                    | pl.col("hs_code").cast(pl.Utf8).str.starts_with("55062")
                    | pl.col("hs_code").cast(pl.Utf8).str.starts_with("39076")
                    | pl.col("hs_code").cast(pl.Utf8).str.starts_with("291736")
                )

            # 3. 兜底按品名中文描述筛选
            if sub.is_empty():
                name_col = (
                    "hs_name"
                    if "hs_name" in df.columns
                    else ("goods_name" if "goods_name" in df.columns else None)
                )
                if name_col:
                    sub = df.filter(pl.col(name_col).str.contains("聚酯|涤纶|化纤|精对苯二甲酸"))

            if sub.is_empty() or "report_month" not in sub.columns:
                continue

            # 统一聚合为月度实物量 (万吨) 与出口金额 (百万美元)
            agg_exprs: list[pl.Expr] = []
            if "export_volume" in sub.columns:
                # customs_trade_gacc 单位为千克 (kg), 1e7 kg = 1 万吨
                agg_exprs.append(
                    (pl.col("export_volume").sum() / 1e7).alias("polyester_export_w_tons")
                )
            elif "export_qty_tons" in sub.columns:
                agg_exprs.append(
                    (pl.col("export_qty_tons").sum() / 10000.0).alias("polyester_export_w_tons")
                )
            elif "export_qty" in sub.columns:
                agg_exprs.append(
                    (pl.col("export_qty").sum() / 10000.0).alias("polyester_export_w_tons")
                )

            if "export_value_usd" in sub.columns:
                agg_exprs.append(
                    (pl.col("export_value_usd").sum() / 1e6).alias("export_value_m_usd")
                )

            if agg_exprs:
                monthly = sub.group_by("report_month").agg(agg_exprs).sort("report_month")
                return monthly
        except Exception as exc:
            logger.debug(f"尝试加载海关数据集 {ds} 失败: {exc}")
    return pl.DataFrame()


def load_company_panel(
    catalog: DatasetReader,
    dataset_name: str = "mart/pta_company_panel",
    companies_config_path: Path | str | None = None,
) -> pl.DataFrame:
    """加载 PTA 上市公司面板；若 Mart 不存在则自动使用 tushare 数据源构建。"""
    from stock_data.core.settings import data_settings

    curated_root = data_settings.runtime_context.curated_root
    mart_candidates = [
        curated_root / "mart/pta_company_panel.parquet",
        Path("data/analytics/pta/latest/pta_company_panel.parquet"),
    ]
    for p in mart_candidates:
        if p.exists():
            try:
                df = pl.read_parquet(p)
                if not df.is_empty():
                    return df
            except Exception:
                pass

    # 回退由 build_pta_company_panel 使用 tushare catalog 构建
    try:
        from stock_data.catalog import DataCatalog

        tushare_cat = DataCatalog("tushare")
        return build_pta_company_panel(catalog=tushare_cat, config_path=companies_config_path)
    except Exception as exc:
        logger.warning(f"构建 PTA 上市公司面板回退失败: {exc}")
        return pl.DataFrame()


def load_industry_market(
    catalog: DatasetReader, dataset_name: str = "mart/industry_l2_daily"
) -> pl.DataFrame:
    """加载化学纤维 (220400) 申万二级行业日频行情与估值分位数。"""
    try:
        df = catalog.load_dataset(dataset_name)
        if df.is_empty():
            return pl.DataFrame()
        if "industry_code" in df.columns:
            sub = df.filter(pl.col("industry_code") == "220400")
            if sub.is_empty():
                sub = df.filter(pl.col("industry_code") == "220200")  # 回退化学原料
            return sub.sort("trade_date")
        return df
    except Exception as exc:
        logger.warning(f"加载二级行业行情失败: {exc}")
        return pl.DataFrame()
