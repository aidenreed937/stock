"""回填后的本地验收门禁。"""

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl


def _keys(endpoint: str, columns: list[str]) -> list[str]:
    try:
        from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

        from stock.data.task_registry import resolve_task

        meta = TUSHARE_API_REGISTRY.get(resolve_task("tushare", endpoint).api_name)
        if meta:
            aliases: dict[str, str] = {
                "ts_code": "symbol",
                "stockCode": "symbol",
                "date": "trade_date",
            }
            return [
                aliases.get(key, key)
                for key in meta.primary_keys
                if key in columns or (key in aliases and aliases[key] in columns)
            ]
    except Exception:
        pass
    return [key for key in ("symbol", "ts_code", "trade_date", "date") if key in columns]


def _key_frame(endpoint: str, frame: pl.DataFrame) -> pl.DataFrame:
    """将各历史文件的主键别名统一为 Curated 规范列名。"""
    keys = _keys(endpoint, frame.columns)
    expressions: list[pl.Expr] = []
    for key in keys:
        source: str | None
        if key == "symbol":
            source = next(
                (column for column in ("symbol", "ts_code", "stockCode") if column in frame.columns),
                None,
            )
        elif key == "trade_date":
            source = next(
                (column for column in ("trade_date", "date") if column in frame.columns),
                None,
            )
        else:
            source = key if key in frame.columns else None
        if source:
            expressions.append(pl.col(source).alias(key))
    return frame.select(expressions) if expressions else pl.DataFrame()


def _meta(endpoint: str) -> Any:
    try:
        from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY
        from stock.data.task_registry import resolve_task

        return TUSHARE_API_REGISTRY.get(resolve_task("tushare", endpoint).api_name)
    except Exception:
        return None


def _endpoint_aliases(endpoint: str) -> set[str]:
    """返回验收所对应的项目任务目录名。"""
    try:
        from stock.data.task_registry import resolve_task

        return {resolve_task("tushare", endpoint).dataset}
    except ValueError:
        return {endpoint}


def _column_present(column: str, columns: list[str]) -> bool:
    """判断源端字段是否已映射为 Curated 标准字段。"""
    aliases = {"date": "trade_date", "ts_code": "symbol", "stockCode": "symbol"}
    return column in columns or aliases.get(column) in columns


def _is_artifact(path: Path) -> bool:
    """跳过迁移备份和临时文件，验收只针对当前有效数据。"""
    return path.name.endswith((".bak.parquet", ".tmp.parquet"))


def _date_key(value: object) -> str:
    """将日期列中的紧凑格式和 ISO 格式统一为 YYYY-MM-DD。"""
    text = str(value)
    compact = text.replace("-", "").replace("/", "")
    if len(compact) >= 8 and compact[:8].isdigit():
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
    return text[:10]


def _period_key(value: object, frequency: str) -> str:
    """将月频/季频业务日期转换为可比较的业务期间。"""
    text = str(value)
    compact = text.replace("-", "").replace("/", "")
    if frequency == "quarterly":
        if "Q" in text.upper():
            year, quarter = text.upper().split("Q", 1)
            if year.isdigit() and quarter[:1] in {"1", "2", "3", "4"}:
                return f"{int(year)}Q{quarter[0]}"
        if compact[:8].isdigit():
            month = int(compact[4:6])
            return f"{compact[:4]}Q{(month - 1) // 3 + 1}"
        if compact[:6].isdigit():
            month = int(compact[4:6])
            return f"{compact[:4]}Q{(month - 1) // 3 + 1}"
    if frequency == "monthly":
        if compact[:6].isdigit():
            return f"{compact[:4]}-{compact[4:6]}"
    return _date_key(value)


def _boundary_period(value: date, frequency: str) -> str:
    """将请求边界转换为与源端业务期间一致的格式。"""
    if frequency == "quarterly":
        return f"{value.year}Q{(value.month - 1) // 3 + 1}"
    if frequency == "monthly":
        return f"{value.year:04d}-{value.month:02d}"
    return str(value)


def accept_backfill(
    root: str = "data/curated",
    endpoint: str = "stock_daily_bar",
    start: date | None = None,
    end: date | None = None,
    source_gaps: list[str] | None = None,
) -> dict[str, Any]:
    """检查文件、日期覆盖、主键重复和源端缺口，返回可序列化报告。"""
    files = (
        [path for path in Path(root).rglob("*.parquet") if not _is_artifact(path)]
        if Path(root).exists()
        else []
    )
    aliases = _endpoint_aliases(endpoint)
    matched = [
        path for path in files
        if any(alias in path.parts or alias in path.stem for alias in aliases)
    ]
    rows = 0
    duplicates = 0
    dates: set[str] = set()
    periods: set[str] = set()
    errors: list[str] = []
    missing_columns: list[str] = []
    lineage_errors: list[str] = []
    key_frames: list[pl.DataFrame] = []
    meta = _meta(endpoint)
    frequency = getattr(meta, "frequency", "daily") if meta else "daily"
    for path in matched:
        try:
            frame = pl.read_parquet(path)
            rows += len(frame)
            if meta:
                missing_columns.extend(
                    column for column in meta.required_columns
                    if not _column_present(column, frame.columns)
                )
                for lineage in ("data_source", "source_endpoint", "request_id", "updated_at"):
                    if lineage not in frame.columns:
                        lineage_errors.append(f"{path}: missing {lineage}")
            keys = _keys(endpoint, frame.columns)
            if keys:
                key_frame = _key_frame(endpoint, frame)
                for key in ("trade_date", "end_date", "suspend_date"):
                    if key in key_frame.columns:
                        key_frame = key_frame.with_columns(
                            pl.col(key)
                            .cast(pl.Utf8, strict=False)
                            .str.replace_all("-", "")
                            .str.replace_all("/", "")
                            .str.slice(0, 8)
                            .alias(key)
                        )
                if "trade_date" in key_frame.columns:
                    key_frame = key_frame.with_columns(
                        pl.col("trade_date")
                        .cast(pl.Utf8, strict=False)
                        .str.slice(0, 8)
                        .alias("trade_date")
                    )
                key_frames.append(key_frame)
            date_col = next((col for col in ("trade_date", "date", "end_date", "month", "quarter") if col in frame.columns), None)
            if date_col:
                values = frame[date_col].drop_nulls().to_list()
                dates.update(_date_key(value) for value in values)
                periods.update(_period_key(value, frequency) for value in values)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    if key_frames:
        all_keys = pl.concat(key_frames, how="vertical_relaxed")
        duplicates = len(all_keys) - len(all_keys.unique())
    missing: list[str] = []
    if start and end:
        start_period = _boundary_period(start, frequency)
        end_period = _boundary_period(end, frequency)
        if frequency in {"monthly", "quarterly"}:
            # 财务/宏观接口按报告期或自然月发布，结束边界可能因源端发布节奏滞后；
            # 起始期间仍必须存在，结束期间缺失通过 source_lag 单独报告。
            if start_period not in periods:
                missing.append(str(start))
        else:
            missing = [str(day) for day in (start, end) if str(day) not in dates]
    gaps = source_gaps or []
    source_lag = bool(
        end
        and (end_period if frequency in {"monthly", "quarterly"} else str(end))
        not in (periods if frequency in {"monthly", "quarterly"} else dates)
    )
    passed = (
        bool(matched)
        and rows > 0
        and duplicates == 0
        and not errors
        and not missing
        and not missing_columns
        and not lineage_errors
    )
    return {
        "status": "PASSED" if passed else "FAILED",
        "endpoint": endpoint,
        "files": len(matched),
        "rows": rows,
        "duplicate_keys": duplicates,
        "missing_boundary_dates": missing,
        "source_gaps": gaps,
        "source_lag": source_lag,
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
    parser.add_argument("--source-gap", action="append", default=[])
    args = parser.parse_args()
    result = accept_backfill(
        args.root,
        args.endpoint,
        date.fromisoformat(args.start) if args.start else None,
        date.fromisoformat(args.end) if args.end else None,
        args.source_gap,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
