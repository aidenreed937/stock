"""GACC 采集器的路径与月份辅助函数。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.customs.paths import GACC_RAW_SUBDIR

_GACC_RAW_SUBDIR = Path("customs") / GACC_RAW_SUBDIR


def resolve_gacc_raw_dir(raw_dir: Path | str) -> Path:
    """把产业 RAW 根目录归一到 GACC 专属目录。"""
    path = Path(raw_dir)
    if path.name == "gacc":
        return path
    if path.name == "customs":
        return path / "gacc"
    return path / _GACC_RAW_SUBDIR


def parse_month(value: str | date) -> tuple[int, int]:
    """将 YYYY-MM 或日期解析为年月。"""
    if isinstance(value, date):
        return value.year, value.month
    text = str(value).strip().replace("/", "-")
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) != 6:
        raise ValueError(f"月份必须使用 YYYY-MM 格式: {value!r}")
    year, month = int(digits[:4]), int(digits[4:])
    if not 1 <= month <= 12:
        raise ValueError(f"月份超出范围: {value!r}")
    return year, month


def month_range(start: str | date | None, end: str | date | None) -> list[tuple[int, int]]:
    """生成包含首尾月份的年月序列。"""
    if start is None and end is None:
        today = date.today()
        return [(today.year - 1, 12)] if today.month == 1 else [(today.year, today.month - 1)]
    start = end if start is None else start
    end = start if end is None else end
    start_year, start_month = parse_month(start)  # type: ignore[arg-type]
    end_year, end_month = parse_month(end)  # type: ignore[arg-type]
    if (start_year, start_month) > (end_year, end_month):
        raise ValueError("GACC 历史回填的起始月份不能晚于结束月份")

    result: list[tuple[int, int]] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        result.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


__all__ = ["month_range", "parse_month", "resolve_gacc_raw_dir"]
