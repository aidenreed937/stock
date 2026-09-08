"""build_customs_company_exposure.py（公司级出口景气观察表）单元测试。"""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

import polars as pl
import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "build_customs_company_exposure.py"
_mod = run_path(str(_SCRIPT_PATH))
load_catalog_hs_codes = _mod["load_catalog_hs_codes"]
build_segment_key_map = _mod["build_segment_key_map"]
_derive = _mod["_derive"]


def _write_golden(path: Path, rows: list[dict]) -> None:
    pl.DataFrame(rows).write_parquet(path)


def test_load_catalog_hs_codes_expands_six_digit_products(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "product_key,product_name,hs_code,hs_level,hs_parent_code\n"
        "zinc,锌,790111,6,7901\n"
        "copper_wire,铜丝,74081100,8,740811\n"
        "transformer,变压器,85042100,8,850421\n",
        encoding="utf-8-sig",
    )
    golden = tmp_path / "golden.parquet"
    _write_golden(
        golden,
        [
            {
                "hs_level": "8",
                "hs_parent_code": "790111",
                "hs_code": "79011100",
                "report_month": "2026-01",
                "trade_direction": "export",
                "export_value_usd": 1.0,
                "export_volume": 1.0,
            },
            {
                "hs_level": "8",
                "hs_parent_code": "790111",
                "hs_code": "79011110",
                "report_month": "2026-01",
                "trade_direction": "export",
                "export_value_usd": 2.0,
                "export_volume": 1.0,
            },
        ],
    )
    g = pl.read_parquet(golden)
    out = load_catalog_hs_codes(catalog, g)
    assert set(out["zinc"]) == {"79011100", "79011110"}  # 6 位父码 → 8 位子码
    assert set(out["copper_wire"]) == {"74081100"}
    assert set(out["transformer"]) == {"85042100"}


def test_load_catalog_hs_codes_keeps_leading_zero_parent(tmp_path: Path) -> None:
    """水产品 030323 型前导 0 码：schema_overrides 保证与黄金表 hs_parent_code 匹配。"""
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "product_key,product_name,hs_code,hs_level,hs_parent_code\n"
        "aquatic_products,水产品,030323,6,0303\n",
        encoding="utf-8-sig",
    )
    golden = tmp_path / "golden.parquet"
    _write_golden(
        golden,
        [
            {
                "hs_level": "8",
                "hs_parent_code": "030323",
                "hs_code": "03032300",
                "report_month": "2026-01",
                "trade_direction": "export",
                "export_value_usd": 1.0,
                "export_volume": 1.0,
            },
        ],
    )
    out = load_catalog_hs_codes(catalog, pl.read_parquet(golden))
    assert out["aquatic_products"] == ["03032300"]


def test_load_catalog_hs_codes_merges_legacy_8_and_six_digit_children(tmp_path: Path) -> None:
    """疫苗型：catalog 8 位历史码（30022000）与 6 位父码现行子码（30024100）合并去重。"""
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "product_key,product_name,hs_code,hs_level,hs_parent_code\n"
        "pharma_vaccines,疫苗,30022000,8,300220\n"
        "pharma_vaccines,疫苗,300220,6,3002\n"
        "pharma_vaccines,疫苗,300241,6,3002\n",
        encoding="utf-8-sig",
    )
    golden = tmp_path / "golden.parquet"
    _write_golden(
        golden,
        [
            {
                "hs_level": "8",
                "hs_parent_code": "300220",
                "hs_code": "30022000",
                "report_month": "2026-01",
                "trade_direction": "export",
                "export_value_usd": 1.0,
                "export_volume": 1.0,
            },
            {
                "hs_level": "8",
                "hs_parent_code": "300241",
                "hs_code": "30024100",
                "report_month": "2026-01",
                "trade_direction": "export",
                "export_value_usd": 2.0,
                "export_volume": 1.0,
            },
        ],
    )
    out = load_catalog_hs_codes(catalog, pl.read_parquet(golden))
    assert set(out["pharma_vaccines"]) == {"30022000", "30024100"}


def test_build_segment_key_map_covers_segment_and_product(tmp_path: Path) -> None:
    seg_rows = [
        ("transformer", "transformer_ultra", "特高压", "85042312;85042313", "u"),
        ("transformer", "transformer_main", "主力", "85042311", "m"),
    ]
    seg_path = tmp_path / "segments.csv"
    seg_path.write_text(
        "product_key,segment_key,segment_name,hs_codes,description\n"
        + "\n".join(",".join(r) for r in seg_rows)
        + "\n",
        encoding="utf-8-sig",
    )
    from stock_data.fetcher.industry.customs.parsers.company_exposure import (
        load_taxline_segments,
    )

    segments_map = load_taxline_segments(seg_path)
    keys = build_segment_key_map(segments_map, {"transformer": ["85042311", "85042312"]})
    assert set(keys) == {
        "transformer::transformer_ultra",
        "transformer::transformer_main",
        "transformer::product",
    }
    assert set(keys["transformer::transformer_ultra"]["hs_codes"]) == {"85042312", "85042313"}
    assert keys["transformer::product"]["hs_codes"] == ["85042311", "85042312"]


def test_derive_computes_3mma_yoy_drive_and_turning_point() -> None:
    n = 26  # 2024-01..2026-02，保证 12 个月前窗口有完整 3 点
    months = [f"{2024 + m // 12}-{m % 12 + 1:02d}" for m in range(n)]
    monthly = pl.DataFrame(
        {
            "key": ["k1"] * n,
            "report_month": months,
            "export_value_usd": [100.0 * 1.05**m for m in range(n)],
            "export_volume": [10.0 * 1.02**m for m in range(n)],
        }
    )
    panel = _derive(monthly, "key", months)
    last = panel.sort("report_month").tail(1).row(0, named=True)
    # 值增速(5%/月) > 量增速(2%/月) → 3MMA yoy 量价齐升
    assert last["value_yoy_3mma"] > 0
    assert last["volume_yoy_3mma"] > 0
    assert last["price_yoy_3mma"] > 0
    assert last["驱动类型"] == "量价齐升"
    assert panel.filter(pl.col("拐点").is_not_null()).height == 0


def test_main_end_to_end_writes_company_rows(tmp_path: Path) -> None:
    """端到端：小黄金表 + 小 map/catalog/segments → 公司-段行与产品级对照列。"""
    import subprocess
    import sys

    golden = tmp_path / "golden.parquet"
    rows = []
    for y in (2024, 2025):
        for m in ("01", "02", "03"):
            v = 100.0 if y == 2024 else 200.0  # 2025 金额翻倍
            rows.append(
                {
                    "hs_level": "8",
                    "hs_code": "85042311",
                    "hs_parent_code": "850423",
                    "report_month": f"{y}-{m}",
                    "trade_direction": "export",
                    "export_value_usd": v,
                    "export_volume": 10.0,
                    "quantity_unit_norm": "units",
                    "unit_known": True,
                }
            )
    _write_golden(golden, rows)

    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "product_key,product_name,hs_code,hs_level,hs_parent_code\n"
        "transformer,变压器,85042311,8,850423\n",
        encoding="utf-8-sig",
    )
    segments = tmp_path / "segments.csv"
    segments.write_text(
        "product_key,segment_key,segment_name,hs_codes,description\n"
        "transformer,transformer_main,主力段,85042311,主力\n",
        encoding="utf-8-sig",
    )
    emap = tmp_path / "map.csv"
    emap.write_text(
        "product_key,product_name,stock_code,company_name,exposure,sw_l2,evidence,status,taxline_segment\n"
        "transformer,变压器,688676.SH,金盘科技,0.9,电网设备,测试,estimated,transformer_main\n",
        encoding="utf-8-sig",
    )
    out_csv = tmp_path / "out.csv"
    out_pq = tmp_path / "out.parquet"
    script = str(_SCRIPT_PATH)
    subprocess.run(  # noqa: S603 — 固定解释器+脚本路径，无不可信输入
        [
            sys.executable,
            script,
            "--input",
            str(golden),
            "--output-pq",
            str(out_pq),
            "--output-csv",
            str(out_csv),
            "--map",
            str(emap),
            "--catalog",
            str(catalog),
            "--segments",
            str(segments),
        ],
        check=True,
        capture_output=True,
    )
    out = pl.read_csv(out_csv)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["company_name"] == "金盘科技"
    assert row["bind_segment"] == "transformer_main"
    assert row["value_yoy_3mma"] == pytest.approx(1.0)  # 2025 金额 = 2×2024
    assert row["product_value_yoy"] == pytest.approx(1.0)
    assert row["segment_minus_product"] == pytest.approx(0.0)
    assert out_pq.exists()
