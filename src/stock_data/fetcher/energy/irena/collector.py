"""IRENA 可再生能源容量统计数据统一采集门面 (IrenaCollector)。"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from stock_data.fetcher.energy.base import EnergyFetcherBase
from stock_data.fetcher.energy.common import (
    DEFAULT_CURATED_ENERGY_DIR,
    DEFAULT_RAW_ENERGY_DIR,
    save_curated_energy_fact,
)
from stock_data.fetcher.energy.irena.client import IrenaClient
from stock_data.fetcher.energy.irena.parser import IrenaParser
from stock_data.fetcher.energy.models import (
    GlobalRenewableCapacityRecord,
    records_to_renewable_capacity_frame,
)

logger = logging.getLogger(__name__)


class IrenaCollector(EnergyFetcherBase):
    """IRENA (国际可再生能源署) 全球新能源装机统计数据采集门面。

    输出黄金事实表:
        data/curated/industry/energy/global_renewable_capacity.parquet
    """

    def __init__(
        self,
        raw_dir: Path | None = None,
        curated_dir: Path | None = None,
    ) -> None:
        raw_base = raw_dir or DEFAULT_RAW_ENERGY_DIR
        curated_base = curated_dir or DEFAULT_CURATED_ENERGY_DIR
        super().__init__(raw_dir=raw_base / "irena", curated_dir=curated_base)
        self.client = IrenaClient(raw_dir=self.raw_dir)

    def collect(self) -> list[GlobalRenewableCapacityRecord]:
        """采集并解析 IRENA 全球新能源装机数据记录。"""
        csv_files = self.client.fetch_or_load_dataset()
        if not csv_files:
            logger.info("未找到本地 IRENA 原始数据快照: %s", self.raw_dir)
            return []

        all_records: list[GlobalRenewableCapacityRecord] = []
        for csv_file in csv_files:
            logger.info("正在解析 IRENA 原始数据集: %s", csv_file.name)
            records = IrenaParser.parse_csv(csv_file)
            all_records.extend(records)

        logger.info("IRENA 数据集解析完成，共提取 %d 条装机记录", len(all_records))
        return all_records

    def collect_from_content(
        self, csv_content: str | io.StringIO
    ) -> list[GlobalRenewableCapacityRecord]:
        """直接从 CSV 文本内容解析装机记录。"""
        return IrenaParser.parse_csv(csv_content)

    def collect_and_save(self) -> dict[str, int]:
        """执行完整采集并落盘至 Curated 黄金事实表 (global_renewable_capacity.parquet)。"""
        records = self.collect()
        if not records:
            return {}

        df_cap = records_to_renewable_capacity_frame(records)
        target_path = self.curated_dir / "global_renewable_capacity.parquet"
        n_saved = save_curated_energy_fact(
            new_df=df_cap,
            target_parquet_path=target_path,
            primary_keys=["geo_code", "year", "technology", "source"],
        )

        return {"global_renewable_capacity": n_saved}
