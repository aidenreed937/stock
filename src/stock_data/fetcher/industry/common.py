"""垂直产业采集器通用工具 (日期自然日计算、RAW 原始快照归档、增量落盘)。"""

import calendar
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)


def get_month_end_date(year: int, month: int) -> date:
    """计算指定年月的最后一个自然日 (行业月度指标标准对齐日期)。"""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def parse_month_string(month_str: str) -> tuple[int, int]:
    """解析 YYYY-MM 字符串为 (year, month)。"""
    parts = month_str.strip().split("-")
    return int(parts[0]), int(parts[1])


def save_raw_snapshot(
    source_name: str,
    snapshot_filename: str,
    content: str | bytes | dict[str, Any] | list[Any],
    base_dir: Path | str = "data/raw/industry",
) -> Path:
    """将外部采集的原始数据 (HTML/JSON/文本) 归档到 2-Tier ETL RAW 分源目录。

    目录规范: data/raw/industry/{source_name}/{snapshot_filename}
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

    logger.debug("已保存 RAW 原始快照: %s", target_file)
    return target_file


def save_curated_fact(
    new_df: pl.DataFrame,
    target_parquet_path: Path | str,
    primary_keys: list[str] | None = None,
    export_csv: bool = True,
) -> int:
    """将清洗后的黄金事实 DataFrame 执行增量去重并持久化为 Parquet (可附带 CSV)。

    Returns:
        int: 落盘后的总有效行数
    """
    p = Path(target_parquet_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if primary_keys:
        keys = primary_keys
    elif "report_month" in new_df.columns:
        keys = ["report_month"]
    elif "trade_date" in new_df.columns:
        keys = ["trade_date"]
    else:
        keys = [new_df.columns[0]]

    if p.exists():
        existing_df = pl.read_parquet(p)
        merged_df = (
            pl.concat([existing_df, new_df], how="diagonal_relaxed")
            .unique(subset=keys, keep="last")
            .sort("trade_date")
        )
    else:
        merged_df = new_df.unique(subset=keys, keep="last").sort("trade_date")

    merged_df.write_parquet(p)
    if export_csv:
        csv_path = p.with_suffix(".csv")
        merged_df.write_csv(csv_path)

    logger.info("Curated 事实表落盘成功 [%s]: 共 %d 行", p.name, merged_df.height)
    return merged_df.height


def now_utc_iso() -> str:
    """获取当前 UTC ISO 8601 时间戳。"""
    return datetime.now(UTC).isoformat()
