"""Ember 全球发电结构采集与落盘门面类。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from stock_data.fetcher.energy.base import EnergyFetcherBase
from stock_data.fetcher.energy.common import (
    DEFAULT_CURATED_ENERGY_DIR,
    DEFAULT_RAW_ENERGY_DIR,
    save_curated_energy_fact,
)
from stock_data.fetcher.energy.ember.client import EmberClient
from stock_data.fetcher.energy.ember.parser import EmberParser
from stock_data.fetcher.energy.models import (
    GlobalPowerGenerationRecord,
    GlobalRenewableCapacityRecord,
    records_to_power_generation_frame,
    records_to_renewable_capacity_frame,
)

logger = logging.getLogger(__name__)


class EmberCollector(EnergyFetcherBase):
    """Ember 全球发电与清洁能源装机数据采集器。"""

    def __init__(
        self,
        raw_dir: Path | str = DEFAULT_RAW_ENERGY_DIR,
        curated_dir: Path | str = DEFAULT_CURATED_ENERGY_DIR,
    ) -> None:
        super().__init__(raw_dir=raw_dir, curated_dir=curated_dir)
        self.client = EmberClient(raw_dir=self.raw_dir)

    def fetch_raw(self, **kwargs: Any) -> str:
        """拉取 Ember 官方全量 CSV 数据。"""
        force = kwargs.get("force", False)
        return self.client.fetch_yearly_data(force=force)

    def parse(
        self, raw_data: str
    ) -> tuple[list[GlobalPowerGenerationRecord], list[GlobalRenewableCapacityRecord]]:
        """解析 Ember 官方 CSV 数据。"""
        return EmberParser.parse_yearly_csv(raw_data)

    def collect(
        self, **kwargs: Any
    ) -> tuple[list[GlobalPowerGenerationRecord], list[GlobalRenewableCapacityRecord]]:
        """执行全流程采集与解析。"""
        raw_csv = self.fetch_raw(**kwargs)
        if not raw_csv:
            return [], []
        return self.parse(raw_csv)

    def collect_and_save(self, **kwargs: Any) -> dict[str, int]:
        """采集、解析并将黄金事实表持久化落盘。"""
        gen_records, cap_records = self.collect(**kwargs)
        results: dict[str, int] = {}

        if gen_records:
            df_gen = records_to_power_generation_frame(gen_records)
            gen_target = self.curated_dir / "global_power_generation.parquet"
            saved_count = save_curated_energy_fact(
                new_df=df_gen,
                target_parquet_path=gen_target,
                primary_keys=["geo_code", "period", "technology", "source"],
                sort_keys=["geo_code", "trade_date", "technology"],
            )
            results["global_power_generation"] = saved_count
            logger.info("Ember 全球发电事实表落盘成功: %d 条记录", saved_count)

        if cap_records:
            df_cap = records_to_renewable_capacity_frame(cap_records)
            cap_target = self.curated_dir / "global_renewable_capacity.parquet"
            saved_count = save_curated_energy_fact(
                new_df=df_cap,
                target_parquet_path=cap_target,
                primary_keys=["geo_code", "year", "technology", "source"],
                sort_keys=["geo_code", "year", "technology"],
            )
            results["global_renewable_capacity"] = saved_count
            logger.info("Ember 全球装机事实表落盘成功: %d 条记录", saved_count)

        return results
