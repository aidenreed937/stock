"""Tariffline RAW 聚合与 HS6/HS8 黄金表测试。"""

import gzip
import json
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.customs.transforms.tariffline_gold import (
    load_tariffline_gold_records,
    materialize_tariffline_gold,
    validate_tariffline_gold,
)


def _write_catalog(path: Path) -> None:
    path.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names\n"
        "raw_material,原料,graphite,天然石墨,25041010,天然石墨,kg,801000.SI,材料,"
        "801001.SI,非金属材料\n"
        "raw_material,原料,graphite,天然石墨,25041091,天然石墨,kg,801000.SI,材料,"
        "801001.SI,非金属材料\n",
        encoding="utf-8-sig",
    )


def test_tariffline_gold_aggregates_partners_and_derives_hs6(tmp_path: Path) -> None:
    raw_dir = tmp_path / "tariffline"
    raw_dir.mkdir()
    snapshot = raw_dir / "202401_202412_tariffline_M_X_test.json.gz"
    payload = {
        "data": [
            {
                "period": 202401,
                "flowCode": "X",
                "cmdCode": "25041010",
                "partnerCode": 100,
                "primaryValue": 100,
                "qty": 2,
                "qtyUnitAbbr": "kg",
            },
            {
                "period": 202401,
                "flowCode": "X",
                "cmdCode": "25041010",
                "partnerCode": 200,
                "primaryValue": 300,
                "qty": 3,
                "qtyUnitAbbr": "kg",
            },
            {
                "period": 202401,
                "flowCode": "X",
                "cmdCode": "25041091",
                "partnerCode": 100,
                "primaryValue": 50,
                "qty": 1,
                "qtyUnitAbbr": "kg",
            },
            {
                "period": 202401,
                "flowCode": "M",
                "cmdCode": "25041010",
                "partnerCode": 300,
                "primaryValue": 10,
                "qty": 2,
                "qtyUnitAbbr": "kg",
            },
        ]
    }
    with gzip.open(snapshot, "wt", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj)
    (raw_dir / "tariffline_manifest.jsonl").write_text(
        json.dumps(
            {
                "periods": [f"2024{month:02d}" for month in range(1, 13)],
                "flow_code": "M,X",
                "cmd_code": "250410",
                "status": "success",
                "rows": 4,
                "snapshot_path": str(snapshot),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.csv"
    _write_catalog(catalog_path)

    records, raw_files, raw_rows = load_tariffline_gold_records(raw_dir, catalog_path)

    assert raw_files == 1
    assert raw_rows == 4
    assert len(records) == 5
    hs8 = [record for record in records if record.hs_level == "8"]
    hs6 = [record for record in records if record.hs_level == "6"]
    export_25041010 = next(
        record
        for record in hs8
        if record.hs_code == "25041010" and record.trade_direction == "export"
    )
    export_parent = next(record for record in hs6 if record.trade_direction == "export")
    assert export_25041010.export_value_usd == 400.0
    assert export_25041010.export_volume == 5.0
    assert export_parent.hs_code == "250410"
    assert export_parent.export_value_usd == 450.0
    assert export_parent.export_volume == 6.0

    curated_path = tmp_path / "customs_trade.parquet"
    summary = materialize_tariffline_gold(
        raw_dir=raw_dir,
        catalog_path=catalog_path,
        curated_path=curated_path,
    )
    assert summary.hs8_rows == 3
    assert summary.hs6_rows == 2
    frame = pl.read_parquet(curated_path)
    assert frame.height == 5
    assert set(frame["hs_level"].to_list()) == {"6", "8"}
    assert (
        validate_tariffline_gold(
            curated_path,
            start_month="2024-01",
            end_month="2024-01",
        )["errors"]
        == []
    )


def test_tariffline_gold_reads_zstd_parquet_snapshot(tmp_path: Path) -> None:
    raw_dir = tmp_path / "tariffline"
    snapshot = raw_dir / "period=202401/flow=M_X/batch=test/data.parquet"
    snapshot.parent.mkdir(parents=True)
    pl.DataFrame(
        [
            {
                "period": 202401,
                "flowCode": "X",
                "cmdCode": "25041010",
                "partnerCode": 100,
                "primaryValue": 123,
                "qty": 4,
                "qtyUnitAbbr": "kg",
            }
        ]
    ).write_parquet(snapshot, compression="zstd")
    (raw_dir / "tariffline_manifest.jsonl").write_text(
        json.dumps(
            {
                "periods": ["202401"],
                "flow_code": "M,X",
                "cmd_code": "250410",
                "status": "success",
                "rows": 1,
                "snapshot_path": str(snapshot),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.csv"
    _write_catalog(catalog_path)

    records, raw_files, raw_rows = load_tariffline_gold_records(raw_dir, catalog_path)

    assert raw_files == 1
    assert raw_rows == 1
    assert {(record.hs_code, record.trade_direction) for record in records} == {
        ("25041010", "export"),
        ("250410", "export"),
    }


def test_tariffline_gold_skips_exact_duplicate_rows_across_snapshots(tmp_path: Path) -> None:
    raw_dir = tmp_path / "tariffline"
    item = {
        "period": 202401,
        "flowCode": "X",
        "cmdCode": "25041010",
        "partnerCode": 100,
        "primaryValue": 123,
        "qty": 4,
        "qtyUnitAbbr": "kg",
    }
    snapshots = [
        raw_dir / "period=202401/flow=M_X/batch=one/data.parquet",
        raw_dir / "period=202401/flow=M_X/batch=two/data.parquet",
    ]
    for snapshot in snapshots:
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame([item]).write_parquet(snapshot, compression="zstd")
    (raw_dir / "tariffline_manifest.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "periods": ["202401"],
                    "flow_code": "M,X",
                    "cmd_code": "250410",
                    "status": "success",
                    "rows": 1,
                    "snapshot_path": str(snapshot),
                }
            )
            + "\n"
            for snapshot in snapshots
        ),
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.csv"
    _write_catalog(catalog_path)

    records, raw_files, raw_rows = load_tariffline_gold_records(raw_dir, catalog_path)
    hs8 = next(record for record in records if record.hs_level == "8")

    assert raw_files == 2
    assert raw_rows == 2
    assert hs8.export_value_usd == 123.0
    assert hs8.export_volume == 4.0


def _write_catalog_with_transformer(path: Path) -> None:
    path.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names\n"
        "electric,电力设备,transformer,变压器,85042100,液体介质变压器,units,630000.SI,电力设备,"
        "630800.SI,电网设备\n",
        encoding="utf-8-sig",
    )


def test_tariffline_gold_drops_unit_shift_volume_keeps_value(tmp_path: Path) -> None:
    """单位错位申报（数量巨大×ASP 远低于该码中位数）的数量不参与聚合，金额保留。

    复现 85042100 变压器 2024-06~09 印度/土耳其/孟加拉按错误单位申报的污染：
    正常行 ASP ≈ $3,000/台，错位行 30 万台仅 $600（ASP $0.002）。
    修复前月度数量被放大至 30 万台；修复后应为正常行合计 100 台，金额 600 + 3000*99。
    """
    raw_dir = tmp_path / "tariffline"
    raw_dir.mkdir()
    items = []
    # 正常行（3 行不同 partner，ASP 约 $3000，保证该码中位数样本充足）
    for partner in [100, 200, 300]:
        items.append(
            {
                "period": 202406,
                "flowCode": "X",
                "cmdCode": "85042100",
                "partnerCode": partner,
                "primaryValue": 3000 * 33,
                "qty": 33,
                "qtyUnitAbbr": "u",
            }
        )
    # 错位行：30 万台 × $600（ASP $0.002），应被剔除数量
    items.append(
        {
            "period": 202406,
            "flowCode": "X",
            "cmdCode": "85042100",
            "partnerCode": 400,
            "primaryValue": 600,
            "qty": 300000,
            "qtyUnitAbbr": "u",
        }
    )
    snapshot = raw_dir / "202406_tariffline_test.json.gz"
    with gzip.open(snapshot, "wt", encoding="utf-8") as file_obj:
        json.dump({"data": items}, file_obj)
    (raw_dir / "tariffline_manifest.jsonl").write_text(
        json.dumps(
            {
                "periods": ["202406"],
                "flow_code": "M,X",
                "cmd_code": "850421",
                "status": "success",
                "rows": len(items),
                "snapshot_path": str(snapshot),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.csv"
    _write_catalog_with_transformer(catalog_path)

    records, _, _ = load_tariffline_gold_records(raw_dir, catalog_path)
    hs8 = next(
        record
        for record in records
        if record.hs_level == "8"
        and record.hs_code == "85042100"
        and record.trade_direction == "export"
    )
    # 金额保留全部（4 行），数量剔除错位行（仅 3 个正常行 33*3=99）
    assert hs8.export_value_usd == 3000 * 33 * 3 + 600
    assert hs8.export_volume == 33 * 3


def test_tariffline_gold_keeps_low_asp_code_untouched(tmp_path: Path) -> None:
    """低价商品（ASP 中位数 < $500，如服装按件计）不适用单位错位检测，数量照常聚合。"""
    raw_dir = tmp_path / "tariffline"
    raw_dir.mkdir()
    items = []
    for partner in [100, 200, 300, 400]:
        items.append(
            {
                "period": 202406,
                "flowCode": "X",
                "cmdCode": "61091000",
                "partnerCode": partner,
                "primaryValue": 50,
                "qty": 1000,
                "qtyUnitAbbr": "u",
            }
        )
    snapshot = raw_dir / "202406_tariffline_low.json.gz"
    with gzip.open(snapshot, "wt", encoding="utf-8") as file_obj:
        json.dump({"data": items}, file_obj)
    (raw_dir / "tariffline_manifest.jsonl").write_text(
        json.dumps(
            {
                "periods": ["202406"],
                "flow_code": "M,X",
                "cmd_code": "610910",
                "status": "success",
                "rows": len(items),
                "snapshot_path": str(snapshot),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.csv"
    catalog_path.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names\n"
        "apparel,服装,tshirt,T恤,61091000,棉制T恤,units,550000.SI,纺织服饰,"
        "550300.SI,服装家纺\n",
        encoding="utf-8-sig",
    )

    records, _, _ = load_tariffline_gold_records(raw_dir, catalog_path)
    hs8 = next(
        record
        for record in records
        if record.hs_level == "8"
        and record.hs_code == "61091000"
        and record.trade_direction == "export"
    )
    # 数量巨大（4000 件）但 ASP $0.05——真实低价商品，不应触发错位剔除
    assert hs8.export_value_usd == 200.0
    assert hs8.export_volume == 4000.0
