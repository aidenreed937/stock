"""GACC 人工导出 CSV 导入与 RAW 回放采集器。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.contracts import IndustryCollectionResult
from stock_data.fetcher.industry.customs.collectors.gacc_helpers import (
    month_range as _month_range,
)
from stock_data.fetcher.industry.customs.collectors.gacc_helpers import (
    resolve_gacc_raw_dir as _resolve_gacc_raw_dir,
)
from stock_data.fetcher.industry.customs.collectors.gacc_import import import_gacc_csv
from stock_data.fetcher.industry.customs.collectors.gacc_storage import (
    GaccRawStore,
    load_gacc_raw_records,
)
from stock_data.fetcher.industry.customs.models import (
    DEFAULT_INDUSTRY_OUTPUT_FIELDS,
    GACC_BASE_URL,
    CustomsTradeRecord,
    GaccCurrency,
    GaccFlowType,
)
from stock_data.fetcher.industry.customs.parsers.catalog import load_hs_catalog
from stock_data.fetcher.industry.customs.parsers.gacc_catalog import derive_gacc_code_catalog
from stock_data.fetcher.industry.customs.transforms.customs_trade import (
    records_to_customs_trade_frame,
)

logger = logging.getLogger(__name__)
StatusCallback = Callable[[str], None]


class GaccCollector:
    """中国海关 GACC 2-Tier 采集器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry/customs/gacc",
        catalog_path: Path | str = "config/data/customs/good_h8_codes.csv",
        *,
        base_url: str | None = None,
    ) -> None:
        self.raw_root = Path(raw_dir)
        self.raw_store = GaccRawStore(_resolve_gacc_raw_dir(self.raw_root))
        self.catalog_path = Path(catalog_path)
        self.catalog_map = load_hs_catalog(self.catalog_path)
        gacc_code_map = derive_gacc_code_catalog(self.catalog_path)
        self.gacc_code_map: dict[str, dict[str, str]] | None = gacc_code_map or None
        self.base_url = (base_url or GACC_BASE_URL).rstrip("/")

    def collect(
        self,
        start_month: str | date | None = None,
        end_month: str | date | None = None,
        flow_type: GaccFlowType = "both",
        currency: GaccCurrency = "USD",
        force: bool = False,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        output_fields: tuple[str, ...] | None = None,
        split_by_month: bool = False,
        on_status: StatusCallback | None = None,
    ) -> IndustryCollectionResult:
        """从 GACC RAW manifest 快照回放目标范围，不发起网络请求。"""
        if currency != "USD":
            raise ValueError(
                "当前 customs_trade_gacc Curated 契约的金额字段为 export_value_usd，"
                "GACC 只能使用 USD；人民币查询需单独增加 CNY Schema。"
            )
        notify = on_status or (lambda message: logger.info(message))
        start_month = start_month or start_date
        end_month = end_month or end_date
        periods = (
            _month_range(start_month, end_month)
            if start_month is not None or end_month is not None
            else None
        )
        directions = ("export", "import") if flow_type == "both" else (flow_type,)
        del force, output_fields, split_by_month
        records = self.load_from_raw_snapshots()
        if periods is not None:
            allowed_months = {f"{year:04d}-{month:02d}" for year, month in periods}
            records = [
                record
                for record in records
                if record.trade_direction in directions and record.report_month in allowed_months
            ]
        else:
            records = [record for record in records if record.trade_direction in directions]

        requested_tokens = (
            [
                f"{direction}:{year:04d}-{month:02d}"
                for year, month in periods
                for direction in directions
            ]
            if periods is not None
            else []
        )
        available = {f"{record.trade_direction}:{record.report_month}" for record in records}
        cached = [token for token in requested_tokens if token in available]
        missing = [token for token in requested_tokens if token not in available]
        errors = [f"{token}: GACC RAW 中没有目录匹配商品" for token in missing]
        if records and not missing:
            status = "SUCCESS"
        elif records:
            status = "PARTIAL"
        elif missing:
            status = "MISSING_RANGE"
        else:
            status = "EMPTY"
        if records:
            notify(f"GACC RAW 回放完成: {len(records)} 条记录")
        return IndustryCollectionResult(
            records,
            status=status,
            fetched_periods=(),
            cached_periods=cached,
            missing_periods=missing,
            errors=errors,
            updated=False,
        )

    def import_csv(
        self,
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
        """导入人工从 GACC 官网导出的 CSV。"""
        return import_gacc_csv(
            self,
            csv_path,
            start_month=start_month,
            end_month=end_month,
            flow_type=flow_type,
            currency=currency,
            force=force,
            split_by_month=split_by_month,
            output_fields=output_fields,
        )

    def load_from_raw_snapshots(self) -> list[CustomsTradeRecord]:
        """读取 GACC manifest 快照并按主键去重。"""
        return load_gacc_raw_records(
            self.raw_store,
            self.catalog_map,
            self.base_url,
            self.gacc_code_map,
        )

    def backfill(
        self,
        start_month: str | date,
        end_month: str | date | None = None,
        *,
        flow_type: GaccFlowType = "both",
        currency: GaccCurrency = "USD",
        force: bool = False,
        curated_path: Path | str = "data/curated/industry/customs_trade_gacc.parquet",
    ) -> int:
        """重放 GACC 指定历史范围并刷新 Curated。"""
        collection = self.collect(
            start_month=start_month,
            end_month=end_month or start_month,
            flow_type=flow_type,
            currency=currency,
            force=force,
        )
        if not collection.records:
            return 0
        return save_curated_fact(
            records_to_customs_trade_frame(collection.records),
            curated_path,
            primary_keys=[
                "product_key",
                "hs_code",
                "report_month",
                "trade_direction",
                "trade_value_currency",
            ],
        )


__all__ = ["GaccCollector"]
