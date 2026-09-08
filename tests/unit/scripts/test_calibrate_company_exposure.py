"""calibrate_company_exposure.py（LLM 别名表校准 exposure）单元测试。"""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pandas as pd
import polars as pl
import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "calibrate_company_exposure.py"
_mod = run_path(str(_SCRIPT_PATH))
load_mainbz = _mod["load_mainbz"]
load_alias_map = _mod["load_alias_map"]
calc_exposure = _mod["calc_exposure"]
GENERIC_ITEMS = _mod["GENERIC_ITEMS"]


def _write_mainbz(dir_path: Path, rows: list[dict]) -> Path:
    """写两张分期 parquet：000001 两期（应取最新）、000002 一期。"""
    df = pl.DataFrame(rows)
    d1 = dir_path / "year=2025" / "month=12"
    d2 = dir_path / "year=2026" / "month=06"
    d1.mkdir(parents=True)
    d2.mkdir(parents=True)
    sub = df.filter(pl.col("end_date").cast(pl.String) <= "2025-12-31")
    if sub.height:
        sub.write_parquet(d1 / "data.parquet")
    sub2 = df.filter(pl.col("end_date").cast(pl.String) > "2025-12-31")
    if sub2.height:
        sub2.write_parquet(d2 / "data.parquet")
    return dir_path


def test_load_mainbz_keeps_only_latest_period_per_symbol(tmp_path: Path) -> None:
    main = _write_mainbz(
        tmp_path / "mainbz",
        [
            {
                "symbol": "000001.SZ",
                "end_date": "2025-12-31",
                "bz_code": "P",
                "bz_item": "变压器",
                "bz_sales": 100.0,
            },
            {
                "symbol": "000001.SZ",
                "end_date": "2026-06-30",
                "bz_code": "P",
                "bz_item": "电气设备系列",
                "bz_sales": 50.0,
            },
            {
                "symbol": "000002.SZ",
                "end_date": "2025-12-31",
                "bz_code": "P",
                "bz_item": "开关",
                "bz_sales": 30.0,
            },
        ],
    )
    sub = load_mainbz(main, "2026-06-30")
    assert set(sub["symbol"].to_list()) == {"000001.SZ", "000002.SZ"}
    one = sub[sub["symbol"] == "000001.SZ"]
    assert (one["end_date"].astype(str) == "2026-06-30").all()
    assert set(one["bz_item"].to_list()) == {"电气设备系列"}


def test_load_mainbz_filters_period(tmp_path: Path) -> None:
    main = _write_mainbz(
        tmp_path / "mainbz",
        [
            {
                "symbol": "000001.SZ",
                "end_date": "2025-12-31",
                "bz_code": "P",
                "bz_item": "变压器",
                "bz_sales": 100.0,
            },
            {
                "symbol": "000001.SZ",
                "end_date": "2026-06-30",
                "bz_code": "P",
                "bz_item": "电气设备系列",
                "bz_sales": 200.0,
            },
        ],
    )
    sub = load_mainbz(main, "2025-12-31")
    assert (sub["end_date"].astype(str) == "2025-12-31").all()


def test_load_alias_map_parses_rows_and_skips_unmapped(tmp_path: Path) -> None:
    path = tmp_path / "alias.csv"
    path.write_text(
        "bz_item,product_key,match_type,confidence,note,source_symbols,source_companies,source_period\n"
        "电气设备系列,transformer,ambiguous,0.7,含变压器,688676.SH,金盘科技,2026-06-30\n"
        "服务收入,,,,,,,\n",
        encoding="utf-8-sig",
    )
    alias = load_alias_map(path)
    assert alias["电气设备系列"] == ("transformer", "ambiguous")
    assert "服务收入" not in alias


def test_load_alias_map_rejects_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "alias.csv"
    path.write_text("bz_item,product_key\n变压器,transformer\n", encoding="utf-8-sig")
    with pytest.raises(ValueError, match="缺列"):
        load_alias_map(path)


def _frame(rows: list[tuple[str, float | None]]) -> pd.DataFrame:
    df = pd.DataFrame([{"symbol": "000001.SZ", "bz_item": it, "bz_sales": v} for it, v in rows])
    if df.empty:
        return pd.DataFrame(columns=["symbol", "bz_item", "bz_sales"])
    return df


def test_calc_exposure_counts_alias_and_ambiguous_hits() -> None:
    alias = {
        "变压器": ("transformer", "alias"),
        "电气设备系列": ("transformer", "ambiguous"),
        "开关": ("transformer", "ambiguous"),
    }
    sub = _frame([("变压器", 30.0), ("电气设备系列", 50.0), ("开关", 20.0), ("服务收入", 40.0)])
    ratio, detail = calc_exposure(sub, "000001.SZ", alias, "transformer")
    # 服务收入不在 GENERIC 但 alias_map 无映射 → 计入分母不命中
    assert ratio == pytest.approx(100.0 / 140.0)
    assert "变压器" in detail and "ambiguous" in detail


def test_calc_exposure_excludes_generic_and_dedups_equal_sales() -> None:
    alias = {"变压器": ("transformer", "alias")}
    sub = _frame(
        [
            ("变压器", 30.0),  # 目标
            ("电气设备", 30.0),  # 同值行（映射其他产品），drop_duplicates 去重后不额外计分母
            ("其他业务", 10.0),  # generic 排除
        ]
    )
    ratio, _ = calc_exposure(sub, "000001.SZ", alias, "transformer")
    # real 为 [变压器, 电气设备]，去重 bz_sales 后剩一行 30.0 → 分母 30、命中 30 → 1.0
    assert ratio == pytest.approx(1.0)


def test_calc_exposure_no_match_when_product_differs() -> None:
    alias = {"变压器": ("transformer", "alias")}
    sub = _frame([("变压器", 30.0)])
    ratio, detail = calc_exposure(sub, "000001.SZ", alias, "solar_cell")
    assert ratio is None and detail == "no_match"


def test_calc_exposure_empty_data() -> None:
    ratio, detail = calc_exposure(_frame([]), "000001.SZ", {}, "transformer")
    assert ratio is None and detail == "no_data"
