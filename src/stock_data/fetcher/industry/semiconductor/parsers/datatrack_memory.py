"""TrendForce DataTrack 内存现货月度基准价格 JSON 解析器。

数据源:
- DRAM: https://datatrack-finwhale.trendforce.com:8000/api/v1/data/column?fields=6105
- NAND Wafer: https://datatrack-finwhale.trendforce.com:8000/api/v1/data/column?fields=6106

严格保留源端原始字段 (value_raw, period_raw, indicator_id_raw 等)，
并将清洗后的数值与标准化月度日期供给 Curated 转换层。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
)
from stock_data.fetcher.industry.semiconductor.models import MemoryPriceBenchmarkRecord

logger = logging.getLogger(__name__)

PRODUCT_FAMILY_MAP = {
    6105: "DRAM",
    6106: "NAND",
}


def parse_datatrack_memory_price_json(
    content: str | bytes | dict[str, Any],
    *,
    source_url: str = "",
    collected_at: str = "",
    raw_content_sha256: str = "",
    raw_snapshot_path: str = "",
) -> list[MemoryPriceBenchmarkRecord]:
    """从 TrendForce DataTrack JSON 响应中解析各月份的基准现货价格记录。"""
    if isinstance(content, str | bytes):
        try:
            payload = json.loads(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DataTrack JSON 反序列化失败: %s", exc)
            return []
    elif isinstance(content, dict):
        payload = content
    else:
        return []

    if not isinstance(payload, dict):
        return []

    collect_time = collected_at or now_utc_iso()
    records: list[MemoryPriceBenchmarkRecord] = []

    for indicator_name, item_data in payload.items():
        if not isinstance(item_data, dict):
            continue

        indicator_id_val = item_data.get("indicator_id")
        indicator_id = int(indicator_id_val) if indicator_id_val is not None else 0
        product_family = PRODUCT_FAMILY_MAP.get(indicator_id)
        if product_family is None:
            name_lower = str(indicator_name).lower()
            product_family = (
                "DRAM" if "dram" in name_lower else ("NAND" if "nand" in name_lower else "MEMORY")
            )

        data_dict = item_data.get("data", {})
        if not isinstance(data_dict, dict):
            continue

        unit_str = str(item_data.get("unit") or "USD")
        freq_str = str(item_data.get("freq") or "M")
        data_source_str = str(item_data.get("data_source") or "TrendForce")
        inferenced_str = str(item_data.get("inferenced", False))

        for period_str, value_str in data_dict.items():
            report_month, trade_date, release_date = _parse_period(period_str)
            if report_month is None or trade_date is None:
                continue

            price_val = _parse_price_float(value_str)
            if price_val is None:
                continue

            records.append(
                MemoryPriceBenchmarkRecord(
                    report_month=report_month,
                    trade_date=trade_date,
                    product_family=product_family,
                    indicator_id=indicator_id,
                    indicator_name=str(indicator_name),
                    price_usd=price_val,
                    unit=unit_str,
                    source=data_source_str,
                    source_url=source_url,
                    release_date=release_date,
                    release_date_raw=None,
                    release_date_status="unavailable",
                    data_status="actual",
                    collected_at=collect_time,
                    raw_content_sha256=raw_content_sha256,
                    raw_snapshot_path=raw_snapshot_path,
                    indicator_id_raw=str(indicator_id_val),
                    indicator_name_raw=str(indicator_name),
                    period_raw=str(period_str),
                    value_raw=str(value_str),
                    freq_raw=freq_str,
                    unit_raw=unit_str,
                    data_source_raw=data_source_str,
                    inferenced_raw=inferenced_str,
                )
            )

    return sorted(records, key=lambda r: (r.product_family, r.indicator_id, r.report_month))


def _parse_period(period_raw: str) -> tuple[str | None, date | None, date | None]:
    """从源端统计期时间戳解析 report_month 与 trade_date。

    DataTrack 的 ``period`` 是观测期时间，不是发布日期。该源响应没有独立的
    发布时间字段，因此第三个返回值固定为 ``None``，避免将观测期误记为发布日。
    """
    match = re.match(r"^(\d{4})-(\d{2})", str(period_raw).strip())
    if not match:
        return None, None, None
    year = int(match.group(1))
    month = int(match.group(2))
    report_month = f"{year:04d}-{month:02d}"
    trade_date = get_month_end_date(year, month)

    return report_month, trade_date, None


def _parse_price_float(value_raw: Any) -> float | None:
    text = str(value_raw or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return round(float(text), 4)
    except (ValueError, TypeError):
        return None
