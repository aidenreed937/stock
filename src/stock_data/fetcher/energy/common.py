"""全球能源采集与落盘通用工具 (RAW 快照归档、Curated 事实增量落盘与主键去重)。"""

from __future__ import annotations

import calendar
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)

DEFAULT_RAW_ENERGY_DIR = Path("data/raw/industry/energy")
DEFAULT_CURATED_ENERGY_DIR = Path("data/curated/industry/energy")


def get_month_end_date(year: int, month: int) -> date:
    """计算指定年月的最后一个自然日 (月度指标标准对齐日期)。"""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def parse_period_to_date(period_str: str) -> date:
    """将 YYYY、YYYY-MM 或 YYYY-MM-DD 转换为标准自然日。"""
    p = period_str.strip()
    parts = p.split("-")
    if len(parts) == 1:
        # 年度数据对齐到当年 12 月 31 日
        return date(int(parts[0]), 12, 31)
    if len(parts) == 2:
        # 月度数据对齐到当月末
        return get_month_end_date(int(parts[0]), int(parts[1]))
    if len(parts) == 3:
        # 日频数据
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    raise ValueError(f"无法解析的时间周期格式: {period_str}")


def save_raw_energy_snapshot(
    source_name: str,
    snapshot_filename: str,
    content: str | bytes | dict[str, Any] | list[Any],
    base_dir: Path | str = DEFAULT_RAW_ENERGY_DIR,
) -> Path:
    """将外部采集的原始能源数据归档到 2-Tier ETL RAW 分源目录。

    目录规范: data/raw/industry/energy/{source_name}/{snapshot_filename}
    """
    target_dir = Path(base_dir) / source_name.lower().replace("/", "_")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / snapshot_filename

    if isinstance(content, dict | list):
        with target_file.open("w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
    elif isinstance(content, bytes):
        target_file.write_bytes(content)
    else:
        target_file.write_text(str(content), encoding="utf-8")

    logger.debug("已保存 RAW 原始能源快照: %s", target_file)
    return target_file


def save_curated_energy_fact(
    new_df: pl.DataFrame,
    target_parquet_path: Path | str,
    primary_keys: list[str] | None = None,
    sort_keys: list[str] | None = None,
    export_csv: bool = True,
) -> int:
    """将规范化后的全球能源黄金事实持久化为 Parquet 并支持增量主键去重。

    Returns:
        int: 落盘后的总行数
    """
    p = Path(target_parquet_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if new_df.is_empty() and p.exists():
        logger.debug("传入空 DataFrame 且表已存在，跳过覆盖: %s", p.name)
        return pl.read_parquet(p).height

    keys = primary_keys or [new_df.columns[0]]
    order_keys = sort_keys or keys

    if p.exists():
        existing_df = pl.read_parquet(p)
        merged_df = (
            pl.concat([existing_df, new_df], how="diagonal_relaxed")
            .unique(subset=keys, keep="last")
            .sort(order_keys)
        )
    else:
        merged_df = new_df.unique(subset=keys, keep="last").sort(order_keys)

    merged_df.write_parquet(p)
    if export_csv:
        csv_path = p.with_suffix(".csv")
        merged_df.write_csv(csv_path)

    logger.info("Curated 能源事实表落盘成功 [%s]: 共 %d 行", p.name, merged_df.height)
    return merged_df.height


def now_utc_iso() -> str:
    """获取当前 UTC ISO 8601 时间戳。"""
    return datetime.now(UTC).isoformat()
