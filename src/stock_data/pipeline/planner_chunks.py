"""历史回填年度分块与 Curated 分区检查辅助函数。"""

from __future__ import annotations

from datetime import date


def split_date_range_by_year(start_date: date, end_date: date) -> list[tuple[date, date]]:
    """将跨年份的日期区间按日历年拆分为连续的子区间。"""
    if start_date.year == end_date.year:
        return [(start_date, end_date)]
    chunks: list[tuple[date, date]] = []
    current_year = start_date.year
    while current_year <= end_date.year:
        chunk_start = start_date if current_year == start_date.year else date(current_year, 1, 1)
        chunk_end = end_date if current_year == end_date.year else date(current_year, 12, 31)
        if chunk_start <= chunk_end:
            chunks.append((chunk_start, chunk_end))
        current_year += 1
    return chunks


def has_curated_range(data_source: str, endpoint: str, start_date: date, end_date: date) -> bool:
    """检查 Curated 是否已有目标任务区间内的完整月份物理分区。"""
    try:
        from stock_data.core.settings import data_settings
        from stock_data.core.task_registry import get_endpoint_market, resolve_task
        from stock_data.storage.compat import StorageCompat

        task_spec = resolve_task(data_source, endpoint)
        if not task_spec.partitioned:
            return False
        market = get_endpoint_market(data_source, task_spec.dataset)
        dataset_dir = (
            data_settings.runtime_context.curated_root
            / data_source
            / f"market={market.upper()}"
            / task_spec.dataset
        )
        current = date(start_date.year, start_date.month, 1)
        last = date(end_date.year, end_date.month, 1)
        while current <= last:
            month_dir = dataset_dir / f"year={current.year:04d}" / f"month={current.month:02d}"
            if not any(
                path.is_file()
                and path.suffix == ".parquet"
                and not StorageCompat.is_artifact_path(path)
                for path in month_dir.glob("*.parquet")
            ):
                return False
            current = (
                date(current.year + 1, 1, 1)
                if current.month == 12
                else date(current.year, current.month + 1, 1)
            )
        return True
    except (OSError, ValueError):
        return False


__all__ = ["has_curated_range", "split_date_range_by_year"]
