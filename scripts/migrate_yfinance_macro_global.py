"""将 yfinance 宏观标的从错误市场分区归并到 GLOBAL。"""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl

MACRO_SYMBOLS = frozenset({"^TNX", "^IRX", "DX-Y.NYB", "CNH=X", "GC=F", "CL=F", "HG=F", "^VIX"})
SOURCE = "yfinance"
DATASET = "macro_indicators"
TARGET_MARKET = "GLOBAL"


def _backup_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.migrated.bak.parquet")


def _temp_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.migration.tmp.parquet")


def _write_with_backup(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = _backup_path(path)
        if not backup.exists():
            shutil.copy2(path, backup)
    temp = _temp_path(path)
    frame.write_parquet(temp, compression="zstd")
    temp.replace(path)


def _read_source_files(root: Path) -> list[Path]:
    base = root / SOURCE
    target = base / f"market={TARGET_MARKET}" / DATASET / "data.parquet"
    return sorted(
        base.glob(f"market=*/{DATASET}/data.parquet"),
        key=lambda p: (p != target, str(p)),
    )


def _move_registered_symbols(root: Path) -> dict[str, int]:  # noqa: C901, PLR0912, PLR0915
    target_path = root / SOURCE / f"market={TARGET_MARKET}" / DATASET / "data.parquet"
    source_files = _read_source_files(root)
    moved_frames: list[pl.DataFrame] = []
    retained_target_frames: list[pl.DataFrame] = []
    source_rows = 0
    moved_rows = 0
    rewritten_files = 0
    removed_files = 0

    for path in source_files:
        frame = pl.read_parquet(path)
        if "symbol" not in frame.columns:
            continue
        selected = frame.filter(pl.col("symbol").is_in(sorted(MACRO_SYMBOLS)))
        remainder = frame.filter(~pl.col("symbol").is_in(sorted(MACRO_SYMBOLS)))
        if selected.is_empty():
            continue
        source_rows += len(frame)
        moved_rows += len(selected)
        moved_frames.append(selected)
        if path == target_path:
            retained_target_frames.append(remainder)
        elif remainder.is_empty():
            backup = _backup_path(path)
            if not backup.exists():
                shutil.copy2(path, backup)
            path.unlink()
            removed_files += 1
        else:
            _write_with_backup(path, remainder)
            rewritten_files += 1

    if not moved_frames:
        return {
            "source_rows": 0,
            "moved_rows": 0,
            "target_rows": 0,
            "rewritten_files": 0,
            "removed_files": 0,
        }

    merged = pl.concat(moved_frames, how="diagonal_relaxed")
    if "market" in merged.columns:
        merged = merged.with_columns(pl.lit(TARGET_MARKET).alias("market"))
    if "exchange" in merged.columns:
        merged = merged.with_columns(pl.lit(TARGET_MARKET).alias("exchange"))
    if "currency" in merged.columns:
        merged = merged.with_columns(pl.lit("USD").alias("currency"))
    if {"symbol", "trade_date"}.issubset(merged.columns):
        merged = merged.unique(subset=["symbol", "trade_date"], keep="last")
        merged = merged.sort(["trade_date", "symbol"])

    target_frames = [frame for frame in retained_target_frames if not frame.is_empty()]
    target_frames.append(merged)
    target = pl.concat(target_frames, how="diagonal_relaxed")
    _write_with_backup(target_path, target)

    return {
        "source_rows": source_rows,
        "moved_rows": moved_rows,
        "target_rows": len(target),
        "rewritten_files": rewritten_files,
        "removed_files": removed_files,
    }


def _validate(root: Path) -> dict[str, int]:
    target_path = root / SOURCE / f"market={TARGET_MARKET}" / DATASET / "data.parquet"
    frame = pl.read_parquet(target_path)
    macro = frame.filter(pl.col("symbol").is_in(sorted(MACRO_SYMBOLS)))
    duplicate_keys = macro.group_by(["symbol", "trade_date"]).len().filter(pl.col("len") > 1)
    wrong_market = (
        macro.filter(pl.col("market") != TARGET_MARKET).height if "market" in macro.columns else 0
    )
    if not duplicate_keys.is_empty() or wrong_market:
        raise RuntimeError(
            f"迁移校验失败: duplicate_keys={len(duplicate_keys)}, wrong_market={wrong_market}"
        )
    return {
        "macro_rows": len(macro),
        "symbols": macro["symbol"].n_unique(),
        "duplicate_keys": len(duplicate_keys),
        "wrong_market": wrong_market,
    }


def migrate(root: str | Path) -> tuple[dict[str, int], dict[str, int]]:
    root_path = Path(root)
    result = _move_registered_symbols(root_path)
    validation = _validate(root_path)
    return result, validation


def main() -> None:
    for tier in ("data/raw", "data/curated"):
        result, validation = migrate(tier)
        print(f"[{tier}] migration={result}")
        print(f"[{tier}] validation={validation}")


if __name__ == "__main__":
    main()
