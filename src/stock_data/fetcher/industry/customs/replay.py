"""海关产业 RAW → Curated 离线重放计划（不触发网络采集）。

路径来源：
- ``gacc_trade`` —— 取 :mod:`stock_data.fetcher.industry.customs.registry` 的端点声明；
- ``customs_trade`` —— 该端点在注册表中是**无 target_file 的函数式端点**（由
  UN Comtrade + Tariffline + GACC 三源聚合），故 Curated 路径在此显式声明。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.replay_support import replay_entry

logger = logging.getLogger(__name__)

__all__ = ["build_customs_replay_plan"]


def _load_customs_from_raw(raw_root: Path) -> list[Any]:
    """从 UN Comtrade JSON 与 GACC RAW 快照聚合海关记录 (GACC 优先去重)。"""
    from stock_data.fetcher.industry.customs.collectors.comtrade import ComtradeCollector
    from stock_data.fetcher.industry.customs.collectors.gacc import GaccCollector
    from stock_data.fetcher.industry.customs.models import CustomsTradeRecord
    from stock_data.fetcher.industry.customs.transforms.tariffline_gold import (
        load_tariffline_gold_records,
    )

    comtrade_dir = raw_root / "customs" / "comtrade"
    records: list[CustomsTradeRecord] = []
    if comtrade_dir.exists():
        collector = ComtradeCollector(raw_dir=comtrade_dir)
        json_files = sorted(comtrade_dir.glob("*.json.gz")) + sorted(comtrade_dir.glob("*.json"))
        for file in json_files:
            try:
                records.extend(collector.load_from_raw_json(file))
            except Exception as exc:  # noqa: BLE001
                logger.warning("解析 UN Comtrade 快照失败 [%s]: %s", file.name, exc)
    tariffline_dir = raw_root / "customs" / "comtrade_tariffline"
    try:
        tariffline_records, _, _ = load_tariffline_gold_records(
            tariffline_dir,
            catalog_path="config/data/customs/good_h8_codes.csv",
        )
        records.extend(tariffline_records)
    except Exception as exc:  # noqa: BLE001
        logger.warning("解析 Tariffline 快照失败: %s", exc)
    try:
        records.extend(GaccCollector(raw_dir=raw_root).load_from_raw_snapshots())
    except Exception as exc:  # noqa: BLE001
        logger.warning("解析 GACC 快照失败: %s", exc)

    dedup: dict[tuple[str, str, str, str, str], CustomsTradeRecord] = {}
    for record in records:
        key = (
            record.product_key,
            record.hs_code,
            record.report_month,
            record.trade_direction,
            record.trade_value_currency,
        )
        if key not in dedup or (dedup[key].source == "UN_Comtrade" and record.source == "GACC"):
            dedup[key] = record
    return list(dedup.values())


def _load_gacc_from_raw(raw_root: Path) -> list[Any]:
    """从 GACC CSV/manifest RAW 快照重放中国海关记录。"""
    from stock_data.fetcher.industry.customs.collectors.gacc import GaccCollector

    return GaccCollector(raw_dir=raw_root).load_from_raw_snapshots()


def build_customs_replay_plan() -> dict[str, dict[str, Any]]:
    """构建海关产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.customs.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.customs.transforms.customs_trade import (
        records_to_customs_trade_frame,
    )

    return {
        "customs_trade": replay_entry(
            "customs_trade",
            loader=_load_customs_from_raw,
            to_frame=records_to_customs_trade_frame,
            curated="customs_trade.parquet",
            primary_keys=["product_key", "hs_code", "report_month", "trade_direction"],
        ),
        "gacc_trade": replay_entry(
            "gacc_trade",
            loader=_load_gacc_from_raw,
            to_frame=records_to_customs_trade_frame,
            primary_keys=[
                "product_key",
                "hs_code",
                "report_month",
                "trade_direction",
                "trade_value_currency",
            ],
            specs=ENDPOINT_SPECS,
        ),
    }
