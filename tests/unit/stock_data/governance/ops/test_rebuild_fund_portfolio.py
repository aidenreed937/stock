"""fund_portfolio RAW 重放重建器测试。

覆盖历史缺陷：源端 ``ts_code``（基金代码）与 ``symbol``（被持有股票代码）
语义不同，曾被归一化器错误 coalesce 导致被持有股票代码丢失。
"""

from pathlib import Path

import polars as pl

from stock_data.governance.ops.rebuild_fund_portfolio import rebuild_fund_portfolio

_RAW_RELATIVE = Path("tushare") / "market=CN" / "fund_portfolio"
_CURATED_RELATIVE = Path("tushare") / "market=CN" / "fund_portfolio"


def _write_raw_partition(root: Path) -> tuple[Path, Path]:
    raw_root = root / "raw" / _RAW_RELATIVE
    curated_root = root / "curated" / _CURATED_RELATIVE
    partition = raw_root / "year=2026" / "month=08"
    partition.mkdir(parents=True)

    pl.DataFrame(
        {
            "ts_code": ["159645.SZ", "260116.OF", "159645.SZ"],
            "ann_date": ["20260828", "20260828", "20260828"],
            "end_date": ["20260630", "20260630", "20260630"],
            "symbol": ["002050.SZ", "600519.SH", "600519.SH"],
            "mkv": [1000.0, 2000.0, 3000.0],
            "amount": [10.0, 20.0, 30.0],
            "stk_mkv_ratio": [1.0, 2.0, 3.0],
            "stk_float_ratio": [0.1, 0.2, 0.3],
        }
    ).write_parquet(partition / "data.parquet")
    return raw_root, curated_root


def _curated_partition(curated_root: Path) -> Path:
    return curated_root / "year=2026" / "month=08" / "data.parquet"


def test_rebuild_preserves_held_stock_symbol_and_fund_code(tmp_path: Path) -> None:
    raw_root, curated_root = _write_raw_partition(tmp_path)

    report = rebuild_fund_portfolio(raw_root, curated_root, apply=True)

    assert report["applied"] is True
    assert report["files_processed"] == 1
    assert report["raw_rows"] == 3
    assert report["curated_rows"] == 3
    assert report["duplicates"] == 0

    curated = pl.read_parquet(_curated_partition(curated_root)).sort(["fund_code", "symbol"])
    # 被持有股票代码保留在 symbol，基金代码改名为 fund_code，两者并存
    assert "ts_code" not in curated.columns
    assert curated.select(["fund_code", "symbol", "mkv"]).rows() == [
        ("159645.SZ", "002050.SZ", 1000.0),
        ("159645.SZ", "600519.SH", 3000.0),
        ("260116.OF", "600519.SH", 2000.0),
    ]


def test_rebuild_dry_run_leaves_curated_untouched(tmp_path: Path) -> None:
    raw_root, curated_root = _write_raw_partition(tmp_path)

    report = rebuild_fund_portfolio(raw_root, curated_root)

    assert report["applied"] is False
    assert report["curated_rows"] == 3
    assert not _curated_partition(curated_root).exists()


def test_rebuild_writes_backup_and_replaces_partition(tmp_path: Path) -> None:
    raw_root, curated_root = _write_raw_partition(tmp_path)
    partition = _curated_partition(curated_root)
    partition.parent.mkdir(parents=True)
    pl.DataFrame({"legacy": [1]}).write_parquet(partition)

    rebuild_fund_portfolio(raw_root, curated_root, apply=True)

    backup = partition.with_suffix(".bak.parquet")
    assert backup.exists()
    assert pl.read_parquet(backup).columns == ["legacy"]
    assert "fund_code" in pl.read_parquet(partition).columns


def test_rebuild_dedups_on_full_primary_key(tmp_path: Path) -> None:
    """同一 (基金, 公告日, 报告期, 股票) 只保留最后一条，不同股票不会被误合并。"""
    raw_root, curated_root = _write_raw_partition(tmp_path)
    partition = raw_root / "year=2026" / "month=08" / "data.parquet"
    pl.concat(
        [
            pl.read_parquet(partition),
            pl.DataFrame(
                {
                    "ts_code": ["159645.SZ"],
                    "ann_date": ["20260828"],
                    "end_date": ["20260630"],
                    "symbol": ["002050.SZ"],
                    "mkv": [9999.0],
                    "amount": [99.0],
                    "stk_mkv_ratio": [9.0],
                    "stk_float_ratio": [0.9],
                }
            ),
        ],
        how="diagonal_relaxed",
    ).write_parquet(partition)

    report = rebuild_fund_portfolio(raw_root, curated_root, apply=True)

    assert report["raw_rows"] == 4
    assert report["curated_rows"] == 3

    # 同键去重由清洗阶段完成（保留最后一条）；此处同时校验不同股票不会被误合并
    curated = pl.read_parquet(_curated_partition(curated_root)).sort(["fund_code", "symbol"])
    assert curated.select(["fund_code", "symbol", "mkv"]).rows() == [
        ("159645.SZ", "002050.SZ", 9999.0),
        ("159645.SZ", "600519.SH", 3000.0),
        ("260116.OF", "600519.SH", 2000.0),
    ]
