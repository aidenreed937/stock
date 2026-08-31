"""垂直产业采集器通用工具 (日期自然日计算、RAW 原始快照归档、增量落盘)。"""

import calendar
import gzip
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
    compress: bool = False,
) -> Path:
    """将外部采集的原始数据 (HTML/JSON/文本) 归档到 2-Tier ETL RAW 分源目录。

    目录规范: data/raw/industry/{source_name}/{snapshot_filename}
    当 compress 为 True 或 snapshot_filename 以 .gz 结尾时，自动执行 Gzip 压缩存储。
    """
    target_dir = Path(base_dir) / source_name.lower().replace("/", "_")
    target_dir.mkdir(parents=True, exist_ok=True)

    if compress and not snapshot_filename.endswith(".gz"):
        snapshot_filename = f"{snapshot_filename}.gz"

    target_file = target_dir / snapshot_filename

    if str(target_file).endswith(".gz"):
        if isinstance(content, dict | list):
            data_bytes = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
        elif isinstance(content, str):
            data_bytes = content.encode("utf-8")
        else:
            data_bytes = content
        if not (len(data_bytes) >= 2 and data_bytes[:2] == b"\x1f\x8b"):
            data_bytes = gzip.compress(data_bytes, compresslevel=9)
        target_file.write_bytes(data_bytes)
    elif isinstance(content, dict | list):
        with target_file.open("w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
    elif isinstance(content, bytes):
        target_file.write_bytes(content)
    else:
        target_file.write_text(str(content), encoding="utf-8")

    logger.debug("已保存 RAW 原始快照: %s", target_file)
    return target_file


def read_raw_text(file_path: Path | str) -> str:
    """读取本地 RAW 原始快照文本 (自动识别 .gz 压缩文件与普通文本文件)。"""
    p = Path(file_path)
    if str(p).endswith(".gz"):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return f.read()
    return p.read_text(encoding="utf-8")


def save_curated_fact(
    new_df: pl.DataFrame,
    target_parquet_path: Path | str,
    primary_keys: list[str] | None = None,
    export_csv: bool = False,
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
