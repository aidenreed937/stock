"""GACC 人工导出 CSV 导入流程。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.contracts import IndustryCollectionResult
from stock_data.fetcher.industry.customs.collectors.gacc_helpers import month_range, parse_month
from stock_data.fetcher.industry.customs.collectors.gacc_storage import parse_gacc_manifest
from stock_data.fetcher.industry.customs.models import (
    DEFAULT_INDUSTRY_OUTPUT_FIELDS,
    GaccCurrency,
    GaccFlowType,
    GaccQueryParams,
)
from stock_data.fetcher.industry.customs.parsers.gacc import parse_gacc_csv


def import_gacc_csv(
    collector: Any,
    csv_path: Path | str,
    *,
    start_month: str | date,
    end_month: str | date | None = None,
    flow_type: GaccFlowType,
    currency: GaccCurrency = "USD",
    force: bool = False,
    split_by_month: bool = True,
    output_fields: tuple[str, ...] = DEFAULT_INDUSTRY_OUTPUT_FIELDS,
) -> IndustryCollectionResult:
    """导入人工从 GACC 官网导出的 CSV 并生成规范 RAW manifest。"""
    if flow_type == "both":
        raise ValueError("单个 GACC CSV 必须明确指定 import 或 export 方向")
    source_path = Path(csv_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"未找到 GACC 导出 CSV: {source_path}")
    start_year, start_number = parse_month(start_month)
    end_year, end_number = parse_month(end_month or start_month)
    if start_year != end_year:
        raise ValueError("单个 GACC CSV 只能对应一个年份，请按年份分别导入")
    params = GaccQueryParams(
        flow_type=flow_type,
        currency=currency,
        year=start_year,
        month_start=start_number,
        month_end=end_number,
        split_by_month=split_by_month,
        output_fields=tuple(output_fields),
    )
    token = f"{flow_type}:{params.period}"
    if not force:
        cached = collector.raw_store.find_cached(params)
        if cached is not None:
            records = parse_gacc_manifest(
                cached,
                collector.raw_store,
                collector.catalog_map,
                collector.gacc_code_map,
            )
            if records:
                return IndustryCollectionResult(
                    records,
                    status="SUCCESS",
                    cached_periods=(token,),
                    updated=False,
                )

    records = parse_gacc_csv(
        source_path,
        params=params,
        catalog_map=collector.catalog_map,
        gacc_code_map=collector.gacc_code_map,
        source_url=collector.base_url,
    )
    allowed_months = {
        f"{year:04d}-{month:02d}"
        for year, month in month_range(start_month, end_month or start_month)
    }
    if not records:
        raise ValueError(f"GACC CSV 没有匹配当前启用目录的有效记录: {source_path}")
    if any(record.report_month not in allowed_months for record in records):
        raise ValueError(f"GACC CSV 数据年月超出导入范围 {params.period}: {source_path}")

    manifest = collector.raw_store.save_download(
        params,
        source_path,
        source_url=collector.base_url,
        downloaded_at=now_utc_iso(),
    )
    imported = parse_gacc_manifest(
        manifest,
        collector.raw_store,
        collector.catalog_map,
        collector.gacc_code_map,
    )
    if not imported:
        raise ValueError(f"GACC CSV 导入后没有可回放记录: {source_path}")
    return IndustryCollectionResult(
        imported,
        status="SUCCESS",
        fetched_periods=(token,),
        updated=True,
    )


__all__ = ["import_gacc_csv"]
