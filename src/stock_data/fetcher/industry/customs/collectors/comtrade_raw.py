"""Comtrade RAW JSON/CSV 快照回放能力。"""

from __future__ import annotations

import csv
import gzip
import json
import logging
from pathlib import Path
from typing import Any, cast

from stock_data.fetcher.industry.customs.collectors.comtrade_helpers import (
    infer_csv_trade_direction,
)
from stock_data.fetcher.industry.customs.models import CustomsTradeRecord
from stock_data.fetcher.industry.customs.parsers.catalog import parse_raw_csv_rows

logger = logging.getLogger(__name__)


class ComtradeRawMixin:
    """为 ComtradeCollector 提供离线 RAW 回放方法。"""

    def load_from_raw_json(self: Any, file_path: Path | str) -> list[CustomsTradeRecord]:
        """从本地 RAW JSON / JSON.GZ 文件中加载并标准化。"""
        path = Path(file_path)
        if not path.exists():
            return []
        try:
            if str(path).endswith(".gz"):
                with gzip.open(path, "rt", encoding="utf-8") as file_obj:
                    data = json.load(file_obj)
            else:
                with path.open("r", encoding="utf-8") as file_obj:
                    data = json.load(file_obj)
            items = data.get("data", []) if isinstance(data, dict) else data
            return cast(
                "list[CustomsTradeRecord]",
                self.parse_api_records(cast("list[dict[str, Any]]", items)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("加载 RAW JSON 快照失败 [%s]: %s", path, exc)
            return []

    def load_from_raw_csv(
        self: Any,
        file_path: Path | str,
        trade_direction: str | None = None,
    ) -> list[CustomsTradeRecord]:
        """从本地 RAW CSV 文件中加载并标准化。"""
        path = Path(file_path)
        if not path.exists():
            return []
        default_trade_direction = trade_direction or infer_csv_trade_direction(path)
        for encoding in ("utf-8-sig", "gb18030", "gbk", "utf-8"):
            try:
                with path.open("r", encoding=encoding) as file_obj:
                    reader = csv.DictReader(file_obj)
                    return parse_raw_csv_rows(
                        list(reader),
                        self._catalog_map,
                        default_trade_direction=default_trade_direction,
                    )
            except UnicodeDecodeError:
                continue
            except Exception as exc:  # noqa: BLE001
                logger.error("加载 RAW CSV 快照失败 [%s]: %s", path, exc)
                return []
        logger.error("无法使用支持的编码加载 RAW CSV 快照: %s", path)
        return []

    def load_from_raw_snapshots(self: Any) -> list[CustomsTradeRecord]:
        """加载本地 Comtrade JSON 快照并按业务主键去重。"""
        records_by_key: dict[tuple[str, str, str, str], CustomsTradeRecord] = {}
        files = sorted(self.raw_dir.glob("*.json.gz")) + sorted(self.raw_dir.glob("*.json"))
        for file_path in files:
            for record in self.load_from_raw_json(file_path):
                key = (
                    record.product_key,
                    record.hs_code,
                    record.report_month,
                    record.trade_direction,
                )
                records_by_key[key] = record
        records = list(records_by_key.values())
        records.sort(
            key=lambda record: (
                record.product_key,
                record.hs_code,
                record.trade_direction,
                record.trade_date,
            )
        )
        return records


__all__ = ["ComtradeRawMixin"]
