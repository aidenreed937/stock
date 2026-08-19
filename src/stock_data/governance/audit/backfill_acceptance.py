"""回填后的本地验收门禁。"""

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.governance.audit.raw_gap import (
    boundary_period as _boundary_period,
)
from stock_data.governance.audit.raw_gap import (
    expected_coverage as _expected_coverage,
)
from stock_data.governance.audit.raw_gap import (
    frame_coverage as _frame_coverage,
)
from stock_data.governance.audit.raw_gap import (
    raw_gap_status as _raw_gap_status,
)

_KNOWN_PROVIDERS = {"tushare", "lixinger", "yfinance", "fred", "alphavantage"}

_SYMBOL_ALIASES = ("symbol", "ts_code", "stockCode", "index_id")
_TRADE_DATE_ALIASES = ("trade_date", "date", "Date")
_KEY_ALIASES = {
    "symbol": _SYMBOL_ALIASES,
    "ts_code": _SYMBOL_ALIASES,
    "stockCode": _SYMBOL_ALIASES,
    "index_id": _SYMBOL_ALIASES,
    "trade_date": _TRADE_DATE_ALIASES,
    "date": _TRADE_DATE_ALIASES,
    "Date": _TRADE_DATE_ALIASES,
}


def _keys(endpoint: str, columns: list[str], data_source: str = "tushare") -> list[str]:
    try:
        from stock_data.core.task_registry import resolve_task

        meta = _meta(endpoint, data_source=data_source)
        task = resolve_task(data_source, endpoint)
        if meta:
            aliases: dict[str, str] = {
                "ts_code": "symbol",
                "stockCode": "symbol",
                "date": "trade_date",
                "Date": "trade_date",
            }
            return [
                aliases.get(key, key)
                for key in meta.primary_keys
                if key in columns or any(alias in columns for alias in _KEY_ALIASES.get(key, ()))
            ]
        if task.dataset in {"stock_daily_bar", "index_daily_bar"}:
            return [key for key in ("symbol", "trade_date") if key in columns]
    except Exception:
        pass
    return [
        canonical
        for canonical, aliases in (
            ("symbol", _SYMBOL_ALIASES),
            ("trade_date", _TRADE_DATE_ALIASES),
        )
        if any(alias in columns for alias in aliases)
    ]


def _key_frame(endpoint: str, frame: pl.DataFrame, data_source: str = "tushare") -> pl.DataFrame:
    """将各历史文件的主键别名统一为 Curated 规范列名。"""
    keys = _keys(endpoint, frame.columns, data_source=data_source)
    expressions: list[pl.Expr] = []
    for key in keys:
        source: str | None
        if key == "symbol":
            source = next(
                (column for column in _SYMBOL_ALIASES if column in frame.columns),
                None,
            )
        elif key == "trade_date":
            source = next(
                (column for column in _TRADE_DATE_ALIASES if column in frame.columns),
                None,
            )
        else:
            source = key if key in frame.columns else None
        if source:
            expressions.append(pl.col(source).cast(pl.Utf8, strict=False).alias(key))
    return frame.select(expressions) if expressions else pl.DataFrame()


def _meta(endpoint: str, data_source: str = "tushare") -> Any:
    try:
        from stock_data.core.task_registry import _provider_registry, resolve_task

        task = resolve_task(data_source, endpoint)
        return _provider_registry(data_source).get(task.api_name)
    except Exception:
        pass
    return None


def _endpoint_aliases(endpoint: str) -> set[str]:
    """返回验收所对应的项目任务目录名。"""
    aliases = {endpoint}
    try:
        from stock_data.core.task_registry import resolve_task

        for prov in ("tushare", "lixinger", "yfinance", "fred", "alphavantage"):
            try:
                task = resolve_task(prov, endpoint)
                aliases.add(task.dataset)
                aliases.add(task.task_name)
            except Exception:
                pass
    except Exception:
        pass
    return aliases


def _column_present(column: str, columns: list[str]) -> bool:
    """判断源端字段是否已映射为 Curated 标准字段。"""
    aliases = {"date": "trade_date", "ts_code": "symbol", "stockCode": "symbol"}
    return column in columns or aliases.get(column) in columns


def _is_artifact(path: Path) -> bool:
    """跳过迁移备份和临时文件，验收只针对当前有效数据。"""
    return path.name.endswith((".bak.parquet", ".tmp.parquet"))


def _matching_files(root: str | Path, aliases: set[str]) -> list[Path]:
    """按数据集别名查找有效 Parquet 文件。"""
    base = Path(root)
    if not base.exists():
        return []
    files = [path for path in base.rglob("*.parquet") if not _is_artifact(path)]
    return [
        path
        for path in files
        if any(alias in path.parts or alias in path.stem for alias in aliases)
    ]


def _count_rows(path: Path) -> int:
    """只读取 Parquet 元数据统计行数，避免验收加载整张 RAW 表。"""
    return int(pl.scan_parquet(str(path)).select(pl.len()).collect().item())


def _reconciliation_key_frame(
    endpoint: str,
    frame: pl.DataFrame,
    data_source: str,
) -> pl.DataFrame:
    """按源端注册主键抽取可跨 RAW/Curated 对账的标准键，保留重复行。"""
    return _key_frame(endpoint, frame, data_source=data_source)


def _concat_key_frames(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """合并各 Parquet 文件的主键帧，保留跨文件重复以便统计。"""
    non_empty = [frame for frame in frames if frame.width > 0]
    if not non_empty:
        return pl.DataFrame()
    return pl.concat(non_empty, how="vertical_relaxed")


def _sample_key_frame(frame: pl.DataFrame) -> list[str]:
    """将复合主键转换为稳定的审计样例文本。"""
    return [
        "@".join(str(row[column]) for column in frame.columns)
        for row in frame.head(20).iter_rows(named=True)
    ]


def _normalize_key_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """统一主键中的日期格式，确保源端紧凑日期可与 Curated 对齐。"""
    normalized = frame
    for key in ("trade_date", "ann_date", "end_date", "suspend_date"):
        if key in normalized.columns:
            normalized = normalized.with_columns(
                pl.col(key)
                .cast(pl.Utf8, strict=False)
                .str.replace_all("-", "")
                .str.replace_all("/", "")
                .str.slice(0, 8)
                .alias(key)
            )
    if "trade_date" in normalized.columns:
        normalized = normalized.with_columns(
            pl.col("trade_date").cast(pl.Utf8, strict=False).str.slice(0, 8).alias("trade_date")
        )
    return normalized


def _path_provider(path: Path) -> str | None:
    """从路径片段中识别 provider，兼容 data/curated/{source}/... 和扁平测试目录。"""
    return next((part for part in path.parts if part in _KNOWN_PROVIDERS), None)


def accept_backfill(
    root: str = "data/curated",
    endpoint: str = "stock_daily_bar",
    start: date | None = None,
    end: date | None = None,
    data_source: str = "tushare",
    source_gaps: list[str] | None = None,
    raw_root: str | None = None,
    min_raw_ratio: float | None = None,
) -> dict[str, Any]:
    """检查文件、日期覆盖、主键重复和源端缺口，返回可序列化报告。"""
    if min_raw_ratio is not None and not 0 <= min_raw_ratio <= 1:
        raise ValueError("min_raw_ratio 必须位于 [0, 1] 区间")

    from stock_data.governance.audit.registry import get_audit_spec

    audit_spec = get_audit_spec(endpoint, data_source)
    raw_exempt = audit_spec.raw_reconciliation_exempt
    aliases = _endpoint_aliases(endpoint)
    matched = [
        path
        for path in _matching_files(root, aliases)
        if _path_provider(path) in {None, data_source}
    ]
    rows = 0
    duplicates = 0
    dates: set[str] = set()
    periods: set[str] = set()
    errors: list[str] = []
    missing_columns: list[str] = []
    lineage_errors: list[str] = []
    key_frames: list[pl.DataFrame] = []
    meta = _meta(endpoint, data_source=data_source)
    frequency = getattr(meta, "frequency", "daily") if meta else "daily"
    matched_count = 0
    expected_dates: list[str] = []
    expected_periods: list[str] = []
    gap_dates: set[str] = set()
    gap_periods: set[str] = set()
    calendar_error: str | None = None
    if start and end:
        expected_dates, expected_periods, gap_dates, gap_periods, calendar_error = (
            _expected_coverage(start, end, frequency, data_source, source_gaps or [])
        )
        if calendar_error:
            errors.append(calendar_error)
    for path in matched:
        try:
            frame = pl.read_parquet(path)
            path_provider = _path_provider(path)
            if data_source and "data_source" in frame.columns:
                sources = set(frame.get_column("data_source").drop_nulls().unique().to_list())
                if sources and sources != {data_source}:
                    if path_provider == data_source:
                        lineage_errors.append(f"{path}: data_source mismatch {sorted(sources)}")
                    continue
            matched_count += 1
            rows += len(frame)
            if meta:
                missing_columns.extend(
                    column
                    for column in getattr(meta, "required_columns", [])
                    if not _column_present(column, frame.columns)
                )
                for lineage in ("data_source", "source_endpoint", "request_id", "updated_at"):
                    if lineage not in frame.columns:
                        lineage_errors.append(f"{path}: missing {lineage}")
            keys = _keys(endpoint, frame.columns, data_source=data_source)
            if keys:
                key_frames.append(
                    _normalize_key_frame(_reconciliation_key_frame(endpoint, frame, data_source))
                )
            frame_dates, frame_periods = _frame_coverage(frame, frequency)
            dates.update(frame_dates)
            periods.update(frame_periods)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    curated_all_keys = _concat_key_frames(key_frames)
    curated_unique_keys = curated_all_keys.unique() if curated_all_keys.width else curated_all_keys
    if curated_all_keys.width:
        duplicates = len(curated_all_keys) - len(curated_unique_keys)

    raw_files: list[Path] = []
    raw_rows: int | None = None
    raw_effective_rows: int | None = None
    raw_filtered_rows = 0
    raw_ratio: float | None = None
    raw_ratio_passed: bool | None = None
    raw_errors: list[str] = []
    raw_key_frames: list[pl.DataFrame] = []
    raw_duplicate_keys: int | None = None
    raw_key_count: int | None = None
    curated_key_count: int | None = len(curated_unique_keys) if curated_all_keys.width else None
    raw_curated_status: str | None = None
    raw_curated_reason = ""
    raw_dates: set[str] = set()
    raw_periods: set[str] = set()
    raw_missing_dates: list[str] | None = None
    raw_missing_periods: list[str] | None = None
    raw_gap_passed: bool | None = None
    raw_missing_in_curated_count: int | None = None
    raw_extra_in_curated_count: int | None = None
    raw_missing_in_curated_sample: list[str] = []
    raw_extra_in_curated_sample: list[str] = []
    if raw_root is not None and not raw_exempt:
        raw_files = [
            path
            for path in _matching_files(raw_root, aliases)
            if _path_provider(path) in {None, data_source}
        ]
        raw_rows = 0
        raw_effective_rows = 0
        for path in raw_files:
            try:
                frame = pl.read_parquet(path)
                raw_rows += len(frame)
                from stock_data.governance.audit.reconciliation import _clean_raw_frame

                cleaned, filtered_count = _clean_raw_frame(endpoint, data_source, frame)
                raw_effective_rows += len(cleaned)
                raw_filtered_rows += filtered_count
                key_frame = _normalize_key_frame(
                    _reconciliation_key_frame(endpoint, cleaned, data_source)
                )
                if key_frame.width:
                    raw_key_frames.append(key_frame)
                frame_dates, frame_periods = _frame_coverage(cleaned, frequency)
                raw_dates.update(frame_dates)
                raw_periods.update(frame_periods)
            except Exception as exc:
                raw_errors.append(f"{path}: {exc}")
        if raw_effective_rows:
            raw_ratio = rows / raw_effective_rows
        if min_raw_ratio is not None:
            raw_ratio_passed = bool(
                raw_files
                and raw_effective_rows
                and raw_ratio is not None
                and raw_ratio >= min_raw_ratio
                and not raw_errors
            )
        errors.extend(raw_errors)

        raw_all_keys = _concat_key_frames(raw_key_frames)
        raw_unique_keys = raw_all_keys.unique() if raw_all_keys.width else raw_all_keys
        raw_key_count = len(raw_unique_keys) if raw_all_keys.width else 0
        raw_duplicate_keys = len(raw_all_keys) - len(raw_unique_keys) if raw_all_keys.width else 0

        raw_missing_dates, raw_missing_periods, raw_gap_passed = _raw_gap_status(
            expected_dates,
            expected_periods,
            raw_dates,
            raw_periods,
            gap_dates,
            gap_periods,
            frequency,
            calendar_error,
            bool(start and end),
        )

        if not raw_files:
            raw_curated_status = "FAILED"
            raw_curated_reason = "缺少 RAW 物理文件"
        elif matched_count == 0:
            raw_curated_status = "FAILED"
            raw_curated_reason = "缺少 Curated 物理文件"
        elif raw_errors:
            raw_curated_status = "FAILED"
            raw_curated_reason = "存在 Parquet 读取错误"
        elif not raw_all_keys.width or not curated_all_keys.width:
            raw_curated_status = "FAILED"
            raw_curated_reason = "RAW 与 Curated 无法按注册主键构造统一对账键"
        elif set(raw_unique_keys.columns) != set(curated_unique_keys.columns):
            raw_curated_status = "FAILED"
            raw_curated_reason = "RAW 与 Curated 注册主键列不一致"
        else:
            join_keys = list(raw_unique_keys.columns)
            missing_keys = raw_unique_keys.join(curated_unique_keys, on=join_keys, how="anti")
            extra_keys = curated_unique_keys.join(raw_unique_keys, on=join_keys, how="anti")
            raw_missing_in_curated_count = len(missing_keys)
            raw_extra_in_curated_count = len(extra_keys)
            raw_missing_in_curated_sample = _sample_key_frame(missing_keys)
            raw_extra_in_curated_sample = _sample_key_frame(extra_keys)
            if raw_missing_in_curated_count or raw_extra_in_curated_count:
                raw_curated_status = "FAILED"
                raw_curated_reason = "全历史 RAW 与 Curated 主键集合不一致"
            elif duplicates:
                raw_curated_status = "FAILED"
                raw_curated_reason = "Curated 黄金表内部存在重复主键"
            else:
                raw_curated_status = "PASSED"
                reason_parts: list[str] = []
                if raw_filtered_rows:
                    reason_parts.append(f"RAW 清洗过滤 {raw_filtered_rows} 条无效记录")
                if raw_duplicate_keys:
                    reason_parts.append(f"RAW 存在 {raw_duplicate_keys} 条批次重复主键")
                raw_curated_reason = "；".join(reason_parts)

    missing: list[str] = []
    end_period = _boundary_period(end, frequency) if end else ""
    if start and end:
        start_period = _boundary_period(start, frequency)
        if frequency in {"monthly", "quarterly"}:
            # 财务/宏观接口按报告期或自然月发布，结束边界可能因源端发布节奏滞后；
            # 起始期间仍必须存在，结束期间缺失通过 source_lag 单独报告。
            if start_period not in periods:
                missing.append(str(start))
        else:
            missing = [day for day in expected_dates if day not in dates and day not in gap_dates]
    gaps = source_gaps or []
    source_lag = bool(
        end
        and (end_period if frequency in {"monthly", "quarterly"} else str(end))
        not in (periods if frequency in {"monthly", "quarterly"} else dates)
    )
    passed = (
        matched_count > 0
        and rows > 0
        and duplicates == 0
        and not errors
        and not missing
        and not missing_columns
        and not lineage_errors
        and (raw_exempt or raw_ratio_passed is not False)
        and (raw_exempt or raw_gap_passed is not False)
        and (raw_root is None or raw_exempt or raw_curated_status == "PASSED")
    )
    return {
        "status": "PASSED" if passed else "FAILED",
        "endpoint": endpoint,
        "data_source": data_source,
        "files": matched_count,
        "rows": rows,
        "duplicate_keys": duplicates,
        "missing_boundary_dates": missing,
        "missing_dates": missing,
        "source_gaps": gaps,
        "calendar_error": calendar_error,
        "source_lag": source_lag,
        "raw_files": len(raw_files),
        "raw_rows": raw_rows,
        "raw_effective_rows": raw_effective_rows,
        "raw_filtered_rows": raw_filtered_rows,
        "curated_raw_ratio": raw_ratio,
        "min_raw_ratio": min_raw_ratio,
        "raw_ratio_passed": raw_ratio_passed,
        "raw_curated_status": "SKIPPED" if raw_exempt else raw_curated_status,
        "raw_curated_reason": (
            audit_spec.raw_reconciliation_reason if raw_exempt else raw_curated_reason
        ),
        "raw_missing_dates": raw_missing_dates,
        "raw_missing_periods": raw_missing_periods,
        "raw_gap_passed": raw_gap_passed,
        "raw_key_count": raw_key_count,
        "curated_key_count": curated_key_count,
        "raw_duplicate_keys": raw_duplicate_keys,
        "raw_missing_in_curated_count": raw_missing_in_curated_count,
        "raw_extra_in_curated_count": raw_extra_in_curated_count,
        "raw_missing_in_curated_sample": raw_missing_in_curated_sample,
        "raw_extra_in_curated_sample": raw_extra_in_curated_sample,
        "raw_reconciliation_exempt": raw_exempt,
        "raw_reconciliation_reason": audit_spec.raw_reconciliation_reason,
        "lineage_status": audit_spec.lineage_status,
        "source_endpoint": audit_spec.source_endpoint,
        "errors": errors,
        "missing_columns": sorted(set(missing_columns)),
        "lineage_errors": lineage_errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="回填结果验收门禁")
    parser.add_argument("--root", default="data/curated")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--source", "--data-source", dest="data_source", default="tushare")
    parser.add_argument("--raw-root", default="data/raw")
    parser.add_argument("--source-gap", action="append", default=[])
    args = parser.parse_args()
    result = accept_backfill(
        args.root,
        args.endpoint,
        date.fromisoformat(args.start) if args.start else None,
        date.fromisoformat(args.end) if args.end else None,
        args.data_source,
        args.source_gap,
        raw_root=args.raw_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
