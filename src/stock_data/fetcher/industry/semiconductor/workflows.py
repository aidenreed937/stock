"""半导体产业端点附加执行逻辑。"""

import logging
from pathlib import Path

from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)


def backfill_semiconductor_china(curated_dir: Path, raw_dir: Path) -> int:
    """从 SIA raw 新闻整理 China 直接披露月度序列。"""
    try:
        from stock_data.fetcher.industry.semiconductor.transforms import (
            build_china_series,
            parse_sia_raw_dir,
            save_china_series,
        )

        records = parse_sia_raw_dir(SemiconductorRawPaths(raw_dir).sia_dir)
        if not records:
            return 0
        series = build_china_series(records)
        if series.is_empty():
            return 0
        save_china_series(series, curated_dir / "semiconductor_china_series.parquet")
        count = series.height
        sales_count = int(series["china_sales_usd"].is_not_null().sum())
        logger.info(
            "semiconductor_china_series 直接披露整理完成: %d 条记录, %d 个绝对值月份",
            count,
            sales_count,
        )
        return count
    except Exception as exc:  # noqa: BLE001
        logger.warning("semiconductor_china_series 整理失败 (非阻塞): %s", exc)
        return 0
