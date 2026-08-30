"""UN Comtrade 联合国商品贸易数据采集适配器 (ComtradeCollector)。"""

from __future__ import annotations

import csv
import gzip
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, cast

from stock_data.core.settings import data_settings
from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.customs.catalog import (
    get_hs6_query_list,
    load_hs_catalog,
    parse_comtrade_items,
    parse_raw_csv_rows,
)
from stock_data.fetcher.industry.customs.transform import records_to_customs_trade_frame
from stock_data.fetcher.industry.models import CustomsTradeRecord

logger = logging.getLogger(__name__)

_DEFAULT_CATALOG_CSV = "config/data/customs/hs_codes_catalog.csv"
_DEFAULT_CURATED_PARQUET = "data/curated/industry/customs_trade.parquet"


class ComtradeCollector:
    """UN Comtrade 官方贸易数据采集适配器 (支持 gzip 紧凑压缩快照)。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry/customs/comtrade",
        catalog_path: Path | str = _DEFAULT_CATALOG_CSV,
        subscription_key: str | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.catalog_path = Path(catalog_path)
        self.subscription_key = (
            subscription_key
            or os.environ.get("COMTRADE_SUBSCRIPTION_KEY", "")
            or getattr(data_settings, "comtrade_subscription_key", "")
        )
        self._catalog_map = load_hs_catalog(self.catalog_path)

    def get_hs6_query_list(self) -> list[str]:
        """从字典表中提取去重后的 6 位国际通用 HS 编码列表。"""
        return get_hs6_query_list(self.catalog_path)

    def collect(self) -> list[CustomsTradeRecord]:
        """执行数据采集: 扫描本地 RAW 快照 (*.json.gz / *.json) -> 标准化为 CustomsTradeRecord 列表。"""
        records: list[CustomsTradeRecord] = []
        if self.raw_dir.exists():
            # 优先收集 *.json.gz 与 *.json (去重同名基础名)
            seen_stems: set[str] = set()
            all_files = sorted(
                list(self.raw_dir.glob("*.json.gz")) + list(self.raw_dir.glob("*.json"))
            )
            for file_path in all_files:
                base_stem = file_path.name.replace(".json.gz", "").replace(".json", "")
                if base_stem in seen_stems:
                    continue
                seen_stems.add(base_stem)
                records.extend(self.load_from_raw_json(file_path))

            if not records:
                for csv_file in sorted(self.raw_dir.glob("*.csv")):
                    records.extend(self.load_from_raw_csv(csv_file))
        return records

    def parse_api_records(self, items: list[dict[str, Any]]) -> list[CustomsTradeRecord]:
        """将 API 返回的字典列表转换为标准 CustomsTradeRecord。"""
        return parse_comtrade_items(items, self._catalog_map)

    def fetch_api(
        self,
        period: str | list[str],
        output_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """调用 UN Comtrade 官方 SDK 批量拉取数据并保存本地 RAW Gzip 压缩快照。"""
        try:
            import comtradeapicall
        except ImportError:
            logger.error("未安装 comtradeapicall，请先执行 `pip install comtradeapicall`")
            return []

        hs_codes = self.get_hs6_query_list()
        if not hs_codes:
            logger.warning("HS 编码列表为空，取消请求")
            return []

        period_param = ",".join(period) if isinstance(period, list | tuple) else str(period)
        cmd_param = ",".join(hs_codes)
        save_stem = output_name or period_param.replace(",", "_")

        logger.info(
            "正在请求 UN Comtrade 官方 API: periods=%s, cmdCodes=%d 个",
            period_param,
            len(hs_codes),
        )
        try:
            df = comtradeapicall.getFinalData(
                subscription_key=self.subscription_key,
                typeCode="C",
                freqCode="M",
                clCode="HS",
                period=period_param,
                reporterCode="156",
                cmdCode=cmd_param,
                flowCode="X",
                partnerCode="0",
                partner2Code="0",
                customsCode="C00",
                motCode="0",
                maxRecords=250000,
                format_output="JSON",
            )
            if df is None or df.empty:
                logger.warning("Comtrade API 返回空数据: period=%s", period)
                return []

            records_dict: list[dict[str, Any]] = cast(
                "list[dict[str, Any]]", df.to_dict(orient="records")
            )
            logger.info("Comtrade API 查询成功: period=%s, records=%d", period, len(records_dict))
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            snapshot_file = self.raw_dir / f"{save_stem}.json.gz"
            with gzip.open(snapshot_file, "wt", encoding="utf-8") as f:
                json.dump({"data": records_dict}, f, ensure_ascii=False)
            return records_dict
        except Exception as e:
            logger.error("Comtrade API 请求失败: %s", e)
            return []

    def backfill(
        self,
        start_year: int = 2015,
        end_year: int = 2024,
        force: bool = False,
        curated_path: Path | str = _DEFAULT_CURATED_PARQUET,
    ) -> int:
        """跨年度全量历史高效回填流水线。"""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        cur_file = Path(curated_path)

        for year in range(start_year, end_year + 1):
            year_months = [f"{year}{m:02d}" for m in range(1, 13)]
            year_period_str = ",".join(year_months)
            snapshot_gz = self.raw_dir / f"{year}_full.json.gz"
            snapshot_json = self.raw_dir / f"{year}_full.json"
            snapshot_legacy = self.raw_dir / f"{year}.json"
            snapshot_legacy_gz = self.raw_dir / f"{year}.json.gz"

            exists = (
                snapshot_gz.exists()
                or snapshot_json.exists()
                or snapshot_legacy.exists()
                or snapshot_legacy_gz.exists()
            )
            if exists and not force:
                logger.info("年份 %d 本地 RAW 快照已存在，跳过网络请求", year)
                continue

            logger.info("=== 正在回填 %d 年 (12个月合并请求) ===", year)
            api_records = self.fetch_api(period=year_period_str, output_name=f"{year}_full")
            if api_records:
                logger.info("年份 %d 快照压缩保存完成: %d 条记录", year, len(api_records))
            time.sleep(1.0)

        all_records = self.collect()
        if not all_records:
            logger.warning("未加载到任何有效海关记录，跳过落盘")
            return 0

        df_customs = records_to_customs_trade_frame(all_records)
        count = save_curated_fact(
            df_customs,
            cur_file,
            primary_keys=["product_key", "hs_code", "report_month"],
        )
        logger.info("海关黄金事实表回填落盘成功: %s, 总条数=%d", cur_file, count)
        return count

    def load_from_raw_json(self, file_path: Path | str) -> list[CustomsTradeRecord]:
        """从本地 RAW JSON / JSON.GZ 文件中加载并标准化。"""
        p = Path(file_path)
        if not p.exists():
            return []
        try:
            if str(p).endswith(".gz"):
                with gzip.open(p, "rt", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            items = data.get("data", []) if isinstance(data, dict) else data
            return self.parse_api_records(items)
        except Exception as e:
            logger.error("加载 RAW JSON 快照失败 [%s]: %s", p, e)
            return []

    def load_from_raw_csv(self, file_path: Path | str) -> list[CustomsTradeRecord]:
        """从本地 RAW CSV 文件中加载并标准化。"""
        p = Path(file_path)
        if not p.exists():
            return []
        with p.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return parse_raw_csv_rows(list(reader), self._catalog_map)
