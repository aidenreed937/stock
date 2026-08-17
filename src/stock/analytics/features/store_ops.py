"""FeatureStore 原子写入与元数据校验辅助函数。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from stock.utils.logger import logger

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def metadata_path(mart_dir: Path) -> Path:
    """返回 market_daily 构建元数据路径。"""
    return mart_dir / "market_daily.metadata.json"


def read_metadata(mart_dir: Path) -> dict[str, Any]:
    """读取 market_daily 构建元数据。"""
    path = metadata_path(mart_dir)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"FeatureStore 读取 market_daily 元数据失败: {exc}")
        return {}


def merge_incremental(
    existing: pl.DataFrame,
    incoming: pl.DataFrame,
    keys: Sequence[str],
) -> pl.DataFrame:
    """按主键列合并增量，保留两侧各自已有的非空字段。

    - 两侧各自按主键去重（保留后出现者）
    - 全连接后对每个已有列 coalesce 两侧非空值，新列直接追加
    """
    if any(key not in existing.columns or key not in incoming.columns for key in keys):
        return pl.concat([existing, incoming], how="diagonal_relaxed")

    existing = existing.unique(subset=keys, keep="last")
    incoming = incoming.unique(subset=keys, keep="last")
    existing_columns = list(existing.columns)
    incoming_columns = [column for column in incoming.columns if column not in existing_columns]
    merged = existing.join(incoming, on=keys, how="full", coalesce=True, suffix="__incoming")

    for column in existing_columns:
        if column in keys:
            continue
        incoming_column = f"{column}__incoming"
        if incoming_column in merged.columns:
            merged = merged.with_columns(
                pl.coalesce([pl.col(incoming_column), pl.col(column)]).alias(column)
            ).drop(incoming_column)

    return merged.select(
        [column for column in [*existing_columns, *incoming_columns] if column in merged.columns]
    )


def validate_incremental_metadata(mart_dir: Path, metadata: Mapping[str, Any] | None) -> None:
    """拒绝定义指纹不一致的增量宽表合并。"""
    if metadata is None:
        raise ValueError(
            "增量合并必须提供构建元数据；若需替换已有宽表请使用 --overwrite 全量重建。"
        )
    existing = read_metadata(mart_dir)
    expected = metadata.get("definition_fingerprint")
    actual = existing.get("definition_fingerprint")
    if not actual or actual != expected:
        raise ValueError(
            "已有 market_daily 的定义指纹缺失或不匹配；请使用 --overwrite 全量重建，"
            "避免混合不同特征定义。"
        )


def write_metadata(mart_dir: Path, payload: Mapping[str, Any]) -> None:
    """原子写入 market_daily 构建元数据。"""
    target_path = metadata_path(mart_dir)
    with tempfile.NamedTemporaryFile(
        dir=mart_dir,
        prefix="market_daily_metadata_",
        suffix=".tmp.json",
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        json.dump(payload, tmp, ensure_ascii=True, sort_keys=True, indent=2)
        tmp_path = Path(tmp.name)
    try:
        tmp_path.replace(target_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
