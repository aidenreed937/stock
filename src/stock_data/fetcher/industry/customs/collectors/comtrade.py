"""UN Comtrade 联合国商品贸易数据采集适配器。"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from stock_data.core.settings import data_settings
from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.customs.collectors.comtrade_api import ComtradeApiMixin
from stock_data.fetcher.industry.customs.collectors.comtrade_helpers import (
    _IMPORT_REQUIRED_PRODUCT_KEYS,
)
from stock_data.fetcher.industry.customs.collectors.comtrade_helpers import (
    calculate_periods as _calculate_periods,
)
from stock_data.fetcher.industry.customs.collectors.comtrade_helpers import (
    chunk_hs_codes as _chunk_hs_codes,
)
from stock_data.fetcher.industry.customs.collectors.comtrade_helpers import (
    infer_csv_trade_direction as _infer_csv_trade_direction,
)
from stock_data.fetcher.industry.customs.collectors.comtrade_helpers import (
    normalize_flow_code as _normalize_flow_code,
)
from stock_data.fetcher.industry.customs.collectors.comtrade_helpers import (
    snapshot_exists as _snapshot_exists,
)
from stock_data.fetcher.industry.customs.collectors.comtrade_raw import ComtradeRawMixin
from stock_data.fetcher.industry.customs.models import CustomsTradeRecord
from stock_data.fetcher.industry.customs.parsers.catalog import get_hs6_query_list, load_hs_catalog
from stock_data.fetcher.industry.customs.transforms.customs_trade import (
    records_to_customs_trade_frame,
)

logger = logging.getLogger(__name__)

_DEFAULT_CATALOG_CSV = "config/data/customs/good_h8_codes.csv"
_DEFAULT_CURATED_PARQUET = "data/curated/industry/customs_trade.parquet"


class ComtradeCollector(ComtradeApiMixin, ComtradeRawMixin):
    """UN Comtrade 官方贸易数据采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry/customs/comtrade",
        catalog_path: Path | str = _DEFAULT_CATALOG_CSV,
        subscription_key: str | None = None,
        tariffline_raw_dir: Path | str | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.catalog_path = Path(catalog_path)
        self.tariffline_raw_dir = (
            Path(tariffline_raw_dir)
            if tariffline_raw_dir
            else (self.raw_dir.parent / "comtrade_tariffline")
        )
        self.subscription_key = (
            subscription_key
            or os.environ.get("COMTRADE_SUBSCRIPTION_KEY", "")
            or getattr(data_settings, "comtrade_subscription_key", "")
        )
        self._catalog_map = load_hs_catalog(self.catalog_path)

    def get_hs6_query_list(self) -> list[str]:
        """从字典表中提取去重后的 6 位国际通用 HS 编码列表。"""
        return get_hs6_query_list(self.catalog_path)

    def get_tariffline_query_list(self) -> list[str]:
        """获取 Tariffline 父级查询码，由 API 展开为实际八位税则线。"""
        return self.get_hs6_query_list()

    def collect(
        self,
        lookback_months: int = 12,
        start_month: str | None = None,
        end_month: str | None = None,
        flow_code: str | None = None,
    ) -> list[CustomsTradeRecord]:
        """执行数据采集：在线拉取 UN Comtrade 数据并落盘。"""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        if not self.subscription_key:
            logger.warning("未配置 COMTRADE_SUBSCRIPTION_KEY，无法在线拉取 UN Comtrade 数据")
            return []

        periods = _calculate_periods(lookback_months, start_month, end_month)
        if not periods:
            return []
        requested_flow = flow_code or (
            "M,X"
            if any(
                row.get("product_key") in _IMPORT_REQUIRED_PRODUCT_KEYS
                for row in self._catalog_map.values()
            )
            else "X"
        )
        api_records = self.fetch_api(period=periods, flow_code=requested_flow)
        if not api_records:
            logger.warning("在线拉取 UN Comtrade 数据失败")
            return []
        records = self.parse_api_records(api_records)
        records.sort(key=lambda record: (record.product_key, record.hs_code, record.trade_date))
        return records

    def backfill(
        self,
        start_year: int = 2015,
        end_year: int = 2024,
        force: bool = False,
        curated_path: Path | str = _DEFAULT_CURATED_PARQUET,
    ) -> int:
        """跨年度全量历史高效回填流水线。"""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        curated_file = Path(curated_path)
        for year in range(start_year, end_year + 1):
            year_period = ",".join(f"{year}{month:02d}" for month in range(1, 13))
            flow_codes = (
                ("X", "M")
                if any(
                    row.get("product_key") in _IMPORT_REQUIRED_PRODUCT_KEYS
                    for row in self._catalog_map.values()
                )
                else ("X",)
            )
            fetched = False
            for flow in flow_codes:
                if _snapshot_exists(self.raw_dir, year, flow) and not force:
                    continue
                logger.info("=== 正在回填 %d 年 (12个月合并请求, flow=%s) ===", year, flow)
                api_records = self.fetch_api(
                    period=year_period,
                    output_name=f"{year}_full",
                    flow_code=flow,
                )
                fetched = True
                if api_records:
                    logger.info(
                        "年份 %d/%s 快照压缩保存完成: %d 条记录", year, flow, len(api_records)
                    )
            if fetched:
                time.sleep(1.0)

        all_records = self.load_from_raw_snapshots()
        if not all_records:
            logger.warning("未加载到任何有效海关记录，跳过落盘")
            return 0
        count = save_curated_fact(
            records_to_customs_trade_frame(all_records),
            curated_file,
            primary_keys=["product_key", "hs_code", "report_month", "trade_direction"],
        )
        logger.info("海关黄金事实表回填落盘成功: %s, 总条数=%d", curated_file, count)
        return count


__all__ = [
    "ComtradeCollector",
    "_calculate_periods",
    "_chunk_hs_codes",
    "_infer_csv_trade_direction",
    "_normalize_flow_code",
    "_snapshot_exists",
]
