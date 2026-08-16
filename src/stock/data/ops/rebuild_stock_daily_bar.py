"""按 RAW 证据重建 TuShare stock_daily_bar Curated 黄金表。"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from stock.core.contracts import STOCK_DAILY_BAR_CONTRACT
from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.normalizer.bar_normalizer import (
    BarDataNormalizer,
)
from stock.data.normalizer.unit_normalizer import UnitNormalizer
from stock.data.pipeline_stages import NormalizerStage
from stock.data.storage.compat import StorageCompat
from stock.utils.logger import logger

DEFAULT_RAW_ROOT = Path("data/raw/tushare/market=CN/stock_daily_bar")
DEFAULT_CURATED_ROOT = Path("data/curated/tushare/market=CN/stock_daily_bar")
DEFAULT_BASIC_PATH = Path("data/curated/tushare/market=CN/stock_basic/data.parquet")
DEFAULT_QUARANTINE_ROOT = Path("data/quarantine")


@dataclass(slots=True)
class RebuildReport:
    """一次重建运行的可审计统计。"""

    raw_files: int = 0
    partitions: int = 0
    raw_rows: int = 0
    unit_rejected_rows: int = 0
    pre_listing_rows: int = 0
    validation_rejected_rows: int = 0
    raw_duplicate_rows: int = 0
    output_rows: int = 0
    unknown_listing_symbols: int = 0
    output_duplicate_rows: int = 0
    ratio_bad_days: int = 0
    ratio_min_median: float | None = None
    ratio_max_median: float | None = None
    output_root: str = ""
    quarantine_path: str = ""
    backup_root: str = ""
    applied: bool = False
    accepted: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PartitionResult:
    """单个 RAW 分区的重建结果。"""

    raw_rows: int = 0
    unit_rejected_rows: int = 0
    pre_listing_rows: int = 0
    validation_rejected_rows: int = 0
    raw_duplicate_rows: int = 0
    output: pl.DataFrame = field(default_factory=pl.DataFrame)
    quarantine_parts: list[pl.DataFrame] = field(default_factory=list)
    unknown_symbols: set[str] = field(default_factory=set)
    error: str = ""


@dataclass(frozen=True, slots=True)
class RebuildContext:
    """全量重建过程中各分区共享的规则与输出配置。"""

    output_root: Path
    cleaner: BarDataCleaner
    unit_normalizer: UnitNormalizer
    normalizer_stage: NormalizerStage
    listing_dates: dict[str, date]


@dataclass(frozen=True, slots=True)
class ApplyContext:
    """Curated 替换阶段的路径与运行标识。"""

    output_root: Path
    target_path: Path
    quarantine_root: Path
    backup_root: Path
    run_id: str
    work_root: Path


def _is_artifact(path: Path) -> bool:
    return path.name.endswith((".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet"))


def _partition_key(path: Path) -> str:
    year = next((part for part in path.parts if part.startswith("year=")), "year=unknown")
    month = next((part for part in path.parts if part.startswith("month=")), "month=unknown")
    return f"{year}/{month}"


def _partition_output_path(root: Path, partition: str) -> Path:
    return root / partition / "data.parquet"


def _load_listing_dates(path: Path) -> dict[str, date]:
    if not path.exists():
        return {}
    try:
        frame = pl.read_parquet(path)
    except Exception as exc:
        logger.warning(f"读取 stock_basic 失败 [{path}]: {exc}")
        return {}
    if not {"symbol", "list_date"}.issubset(frame.columns):
        return {}
    return {
        str(row["symbol"]): listed_date
        for row in frame.select(["symbol", "list_date"]).iter_rows(named=True)
        if (listed_date := BarDataCleaner._date_value(row["list_date"])) is not None
    }


def _read_partition(files: list[Path]) -> pl.DataFrame:
    frames = [pl.read_parquet(path) for path in files]
    frames = [frame for frame in frames if not frame.is_empty()]
    if not frames:
        return pl.DataFrame()
    return frames[0] if len(frames) == 1 else pl.concat(frames, how="diagonal_relaxed")


def _decorate_curated(
    frame: pl.DataFrame, partition: str, normalizer_stage: NormalizerStage
) -> pl.DataFrame:
    """复用在线标准化阶段，保证历史重放与未来采集的血统一致。"""
    return normalizer_stage.normalize(
        cleaned_df=frame,
        instrument=None,
        api_name="daily",
        request_id=f"rebuild:stock_daily_bar:{partition}",
        dataset="stock_daily_bar",
    )


def _key_columns(frame: pl.DataFrame) -> list[str]:
    return [column for column in ("market", "symbol", "trade_date") if column in frame.columns]


def _attach_quarantine(frame: pl.DataFrame, reason: str) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    return frame.with_columns(
        [
            pl.lit(reason).alias("quarantine_reason"),
            pl.lit("stock_daily_bar").alias("source_endpoint"),
            pl.lit("tushare").alias("data_source"),
            pl.lit(datetime.now(UTC)).cast(pl.Datetime("us", "UTC")).alias("quarantined_at"),
        ]
    )


def _write_quarantine(frame: pl.DataFrame, root: Path, run_id: str) -> Path | None:
    if frame.is_empty():
        return None
    target = root / "endpoint=stock_daily_bar" / f"rebuild_{run_id}.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(target, compression="zstd")
    return target


def _ratio_summary(frame: pl.DataFrame) -> tuple[int, float | None, float | None]:
    required = {"amount", "volume", "close", "trade_date"}
    if not required.issubset(frame.columns):
        return 1, None, None
    valid = frame.filter(
        (pl.col("volume") > 0) & (pl.col("amount") > 0) & (pl.col("close") > 0)
    ).with_columns((pl.col("amount") / (pl.col("volume") * pl.col("close"))).alias("_amount_ratio"))
    if valid.is_empty():
        return 0, None, None
    daily = valid.group_by("trade_date").agg(pl.col("_amount_ratio").median().alias("median_ratio"))
    bad = daily.filter((pl.col("median_ratio") < 0.7) | (pl.col("median_ratio") > 1.3))
    minimum = daily["median_ratio"].min()
    maximum = daily["median_ratio"].max()
    return (
        len(bad),
        float(str(minimum)) if minimum is not None else None,
        float(str(maximum)) if maximum is not None else None,
    )


def _duplicate_key_rows(
    frame: pl.DataFrame, keys: list[str] | tuple[str, ...] | None = None
) -> int:
    key_columns = list(keys) if keys is not None else _key_columns(frame)
    if not key_columns or any(column not in frame.columns for column in key_columns):
        return 0
    normalized = StorageCompat.safe_cast_date_col(frame, "trade_date")
    valid = normalized.drop_nulls(subset=key_columns)
    return len(valid) - len(valid.unique(subset=key_columns))


def _validate_output(
    frame: pl.DataFrame,
) -> tuple[bool, list[str], int, int, int, float | None, float | None]:
    errors: list[str] = []
    if frame.is_empty():
        return False, ["重建结果为空"], 0, 0, 0, None, None
    try:
        STOCK_DAILY_BAR_CONTRACT.validate(frame)
    except Exception as exc:
        errors.append(str(exc))
    duplicate_rows = _duplicate_key_rows(frame, _key_columns(frame))
    if duplicate_rows:
        errors.append(f"输出存在 {duplicate_rows} 条重复主键")
    ratio_bad_days, ratio_min, ratio_max = _ratio_summary(frame)
    if ratio_bad_days:
        errors.append(f"成交额/成交量/收盘价日中位数越界 {ratio_bad_days} 天")
    return not errors, errors, duplicate_rows, ratio_bad_days, len(frame), ratio_min, ratio_max


def _replace_curated_dataset(temp_root: Path, curated_root: Path, backup_root: Path) -> None:
    """移动旧 Curated 到备份，再将已验收临时目录移入目标位置。"""
    backup_root.parent.mkdir(parents=True, exist_ok=True)
    if curated_root.exists():
        backup_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(curated_root), str(backup_root))
    try:
        curated_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_root), str(curated_root))
    except Exception:
        if not curated_root.exists() and backup_root.exists():
            shutil.move(str(backup_root), str(curated_root))
        raise


def _write_report(report: RebuildReport, work_root: Path) -> Path:
    report_path = work_root / "rebuild_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return report_path


def _validation_quarantine(eligible: pl.DataFrame, cleaned: pl.DataFrame) -> pl.DataFrame | None:
    if len(cleaned) >= len(eligible):
        return None
    key_columns = [
        column
        for column in ("symbol", "trade_date")
        if column in eligible.columns and column in cleaned.columns
    ]
    if not key_columns:
        return None
    rejected = eligible.join(cleaned.select(key_columns).unique(), on=key_columns, how="anti")
    return rejected if not rejected.is_empty() else None


def _rebuild_partition(
    partition: str,
    files: list[Path],
    context: RebuildContext,
) -> PartitionResult:
    result = PartitionResult()
    try:
        raw_frame = StorageCompat.normalize_identity_columns(_read_partition(files))
        result.raw_rows = len(raw_frame)
        if raw_frame.is_empty():
            return result
        result.raw_duplicate_rows = _duplicate_key_rows(raw_frame, ("symbol", "trade_date"))

        if "symbol" in raw_frame.columns and context.listing_dates:
            result.unknown_symbols = {
                str(value)
                for value in raw_frame.get_column("symbol").drop_nulls().unique().to_list()
                if str(value) not in context.listing_dates
            }

        unit_frame, unit_rejected = context.unit_normalizer.normalize_units_with_quarantine(
            raw_frame
        )
        result.unit_rejected_rows = len(unit_rejected)
        if not unit_rejected.is_empty():
            result.quarantine_parts.append(
                _attach_quarantine(unit_rejected, "unit_inference_failed")
            )

        eligible_frame, pre_listing = context.cleaner._exclude_pre_listing(unit_frame)
        result.pre_listing_rows = len(pre_listing)
        if not pre_listing.is_empty():
            result.quarantine_parts.append(
                _attach_quarantine(pre_listing, "trade_date_before_list_date")
            )

        cleaned_frame = context.cleaner.clean(eligible_frame)
        result.validation_rejected_rows = max(0, len(eligible_frame) - len(cleaned_frame))
        rejected = _validation_quarantine(eligible_frame, cleaned_frame)
        if rejected is not None:
            result.quarantine_parts.append(_attach_quarantine(rejected, "bar_validation_rejected"))

        curated_frame = _decorate_curated(cleaned_frame, partition, context.normalizer_stage)
        if curated_frame.is_empty():
            return result
        key_columns = _key_columns(curated_frame)
        curated_frame = curated_frame.unique(subset=key_columns, keep="last")
        result.output = curated_frame.sort(["trade_date", "symbol"])
        target = _partition_output_path(context.output_root, partition)
        target.parent.mkdir(parents=True, exist_ok=True)
        result.output.write_parquet(target, compression="zstd")
    except Exception as exc:
        result.error = f"{partition}: {exc}"
        logger.exception(f"重建分区失败 [{partition}]")
    return result


def _group_raw_files(raw_path: Path) -> tuple[list[Path], dict[str, list[Path]]]:
    files = sorted(path for path in raw_path.rglob("*.parquet") if not _is_artifact(path))
    grouped: dict[str, list[Path]] = {}
    for path in files:
        grouped.setdefault(_partition_key(path), []).append(path)
    return files, grouped


def _rebuild_partitions(
    grouped: dict[str, list[Path]], context: RebuildContext, report: RebuildReport
) -> tuple[list[pl.DataFrame], list[pl.DataFrame], set[str]]:
    output_parts: list[pl.DataFrame] = []
    quarantine_parts: list[pl.DataFrame] = []
    unknown_symbols: set[str] = set()
    for partition, partition_files in sorted(grouped.items()):
        result = _rebuild_partition(partition, partition_files, context)
        report.raw_rows += result.raw_rows
        report.unit_rejected_rows += result.unit_rejected_rows
        report.pre_listing_rows += result.pre_listing_rows
        report.validation_rejected_rows += result.validation_rejected_rows
        report.raw_duplicate_rows += result.raw_duplicate_rows
        if result.error:
            report.errors.append(result.error)
        if not result.output.is_empty():
            output_parts.append(result.output)
        quarantine_parts.extend(result.quarantine_parts)
        unknown_symbols.update(result.unknown_symbols)
    return output_parts, quarantine_parts, unknown_symbols


def _finalize_output(report: RebuildReport, output_parts: list[pl.DataFrame]) -> None:
    all_output = pl.concat(output_parts, how="diagonal_relaxed") if output_parts else pl.DataFrame()
    report.output_rows = len(all_output)
    accepted, errors, duplicate_rows, ratio_bad_days, _, ratio_min, ratio_max = _validate_output(
        all_output
    )
    report.errors.extend(errors)
    report.output_duplicate_rows = duplicate_rows
    report.ratio_bad_days = ratio_bad_days
    report.ratio_min_median = ratio_min
    report.ratio_max_median = ratio_max
    report.accepted = accepted and not report.errors


def _apply_rebuild(
    report: RebuildReport,
    context: ApplyContext,
) -> None:
    if not report.accepted:
        report.errors.append("验收未通过，拒绝替换 Curated")
        return

    backup_path = context.backup_root / f"stock_daily_bar_backup_{context.run_id}"
    try:
        if report.quarantine_path:
            actual_quarantine = (
                context.quarantine_root
                / "endpoint=stock_daily_bar"
                / f"rebuild_{context.run_id}.parquet"
            )
            actual_quarantine.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(report.quarantine_path, actual_quarantine)
            report.quarantine_path = str(actual_quarantine)
        _replace_curated_dataset(context.output_root, context.target_path, backup_path)
    except Exception as exc:
        report.errors.append(f"替换 Curated 失败: {exc}")
        report.accepted = False
        _write_report(report, context.work_root)
        raise
    report.backup_root = str(backup_path)
    report.applied = True


def rebuild_stock_daily_bar(  # noqa: PLR0913
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    curated_root: str | Path = DEFAULT_CURATED_ROOT,
    *,
    stock_basic_path: str | Path = DEFAULT_BASIC_PATH,
    temp_root: str | Path | None = None,
    quarantine_root: str | Path = DEFAULT_QUARANTINE_ROOT,
    backup_root: str | Path = "data/audit",
    apply: bool = False,
) -> dict[str, Any]:
    """从 RAW 重建行情；默认仅生成临时结果并返回验收报告。"""
    raw_path = Path(raw_root)
    target_path = Path(curated_root)
    if not raw_path.exists():
        return {"accepted": False, "errors": [f"RAW 目录不存在: {raw_path}"]}

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    work_root = (
        Path(temp_root)
        if temp_root is not None
        else Path("data/audit") / f"stock_daily_bar_rebuild_{run_id}"
    )
    output_root = work_root / "curated" / "tushare" / "market=CN" / "stock_daily_bar"
    work_quarantine = work_root / "quarantine"
    listing_dates = _load_listing_dates(Path(stock_basic_path))
    cleaner = BarDataCleaner(listing_dates=listing_dates)
    unit_normalizer = UnitNormalizer("tushare", "stock_daily_bar")

    files, grouped = _group_raw_files(raw_path)

    report = RebuildReport(
        raw_files=len(files),
        partitions=len(grouped),
        output_root=str(output_root),
    )
    context = RebuildContext(
        output_root,
        cleaner,
        unit_normalizer,
        NormalizerStage(BarDataNormalizer(), data_source="tushare"),
        listing_dates,
    )
    output_parts, quarantine_parts, unknown_symbols = _rebuild_partitions(grouped, context, report)
    report.unknown_listing_symbols = len(unknown_symbols)
    _finalize_output(report, output_parts)

    if quarantine_parts:
        quarantine_frame = pl.concat(quarantine_parts, how="diagonal_relaxed")
        quarantine_path = _write_quarantine(quarantine_frame, work_quarantine, run_id)
        report.quarantine_path = str(quarantine_path) if quarantine_path else ""

    if apply:
        _apply_rebuild(
            report,
            ApplyContext(
                output_root=output_root,
                target_path=target_path,
                quarantine_root=Path(quarantine_root),
                backup_root=Path(backup_root),
                run_id=run_id,
                work_root=work_root,
            ),
        )

    _write_report(report, work_root)

    return asdict(report)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="stock_daily_bar RAW 重放、验收与 Curated 替换")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    parser.add_argument("--curated-root", default=str(DEFAULT_CURATED_ROOT))
    parser.add_argument("--stock-basic", default=str(DEFAULT_BASIC_PATH))
    parser.add_argument("--temp-root", default=None)
    parser.add_argument("--quarantine-root", default=str(DEFAULT_QUARANTINE_ROOT))
    parser.add_argument("--backup-root", default="data/audit")
    parser.add_argument("--apply", action="store_true", help="验收通过后替换 Curated")
    return parser.parse_args()


def main() -> None:
    """运行命令行重建并输出 JSON 报告。"""
    args = _parse_args()
    result = rebuild_stock_daily_bar(
        raw_root=args.raw_root,
        curated_root=args.curated_root,
        stock_basic_path=args.stock_basic,
        temp_root=args.temp_root,
        quarantine_root=args.quarantine_root,
        backup_root=args.backup_root,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))  # noqa: T201


if __name__ == "__main__":
    main()
