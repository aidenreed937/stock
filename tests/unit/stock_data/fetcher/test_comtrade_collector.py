import json
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.customs import (
    CUSTOMS_TRADE_SCHEMA,
    ComtradeCollector,
    empty_customs_trade,
    records_to_customs_trade_frame,
)
from stock_data.fetcher.industry.models import CustomsTradeRecord


def test_empty_customs_trade_schema() -> None:
    """测试空表骨架 Schema 匹配。"""
    df = empty_customs_trade()
    assert df.schema == CUSTOMS_TRADE_SCHEMA
    assert df.is_empty()


def test_records_to_customs_trade_frame() -> None:
    """测试记录转 Polars 事实表及 3MMA/YoY/ASP 派生。"""
    records = [
        CustomsTradeRecord(
            category_key="power_and_new_energy",
            category_name="新能源与电力设备",
            product_key="transformer",
            product_name="变压器",
            hs_code="85042100",
            hs_name="额定容量≤650kVA液体介质变压器",
            report_month="2026-05",
            trade_date=date(2026, 5, 31),
            trade_direction="export",
            export_value_usd=1000000.0,
            export_volume=500.0,
            quantity_unit="units",
            target_l1_code="801730.SI",
            target_l1_name="电力设备",
            target_l2_codes="801737.SI",
            target_l2_names="电网设备",
        ),
        CustomsTradeRecord(
            category_key="power_and_new_energy",
            category_name="新能源与电力设备",
            product_key="transformer",
            product_name="变压器",
            hs_code="85042100",
            hs_name="额定容量≤650kVA液体介质变压器",
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            trade_direction="export",
            export_value_usd=1200000.0,
            export_volume=600.0,
            quantity_unit="units",
            target_l1_code="801730.SI",
            target_l1_name="电力设备",
            target_l2_codes="801737.SI",
            target_l2_names="电网设备",
        ),
    ]

    df = records_to_customs_trade_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "export_value_3mma" in df.columns
    assert "yoy_growth_3mma" in df.columns
    assert "export_asp_usd" in df.columns

    # 验证均价 ASP = 1000000 / 500 = 2000.0 美元/台
    assert abs(df["export_asp_usd"][0] - 2000.0) < 1e-6
    # 验证 6月 3MMA = (1000000 + 1200000) / 2 = 1100000.0
    assert abs(df["export_value_3mma"][1] - 1100000.0) < 1e-6


def test_comtrade_collector_load_catalog(tmp_path: Path) -> None:
    """测试字典表加载与映射建立。"""
    catalog_file = tmp_path / "catalog.csv"
    catalog_file.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,target_l1_code,target_l1_name,target_l2_codes,target_l2_names,description\n"
        "power,新能源,transformer,变压器,85042100,变压器,units,801730.SI,电力设备,801737.SI,电网设备,出海\n",
        encoding="utf-8-sig",
    )

    collector = ComtradeCollector(raw_dir=tmp_path / "raw", catalog_path=catalog_file)
    assert "85042100" in collector._catalog_map
    assert "850421" in collector._catalog_map
    assert collector._catalog_map["85042100"]["product_key"] == "transformer"
    assert collector.get_hs6_query_list() == ["850421"]


def test_comtrade_collector_load_raw_json(tmp_path: Path) -> None:
    """测试从 RAW JSON 快照加载。"""
    catalog_file = tmp_path / "catalog.csv"
    catalog_file.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,target_l1_code,target_l1_name,target_l2_codes,target_l2_names,description\n"
        "power,新能源,transformer,变压器,85042100,变压器,units,801730.SI,电力设备,801737.SI,电网设备,出海\n",
        encoding="utf-8-sig",
    )

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    json_file = raw_dir / "2026-06.json"
    mock_payload = {
        "data": [
            {
                "period": "202606",
                "reporterCode": 156,
                "cmdCode": "85042100",
                "cmdDesc": "液体介质变压器",
                "flowDesc": "Exports",
                "primaryValue": 8500000.0,
                "qty": 450.0,
                "qtyUnitAbbr": "units",
            }
        ]
    }
    json_file.write_text(json.dumps(mock_payload), encoding="utf-8")

    collector = ComtradeCollector(raw_dir=raw_dir, catalog_path=catalog_file)
    records = collector.collect()
    assert len(records) == 1
    rec = records[0]
    assert rec.product_key == "transformer"
    assert rec.hs_code == "85042100"
    assert rec.report_month == "2026-06"
    assert rec.export_value_usd == 8500000.0
    assert rec.export_volume == 450.0
    assert rec.target_l2_codes == "801737.SI"
    assert rec.release_date == date(2026, 7, 20)  # 次月 20 日统一发布


def test_comtrade_collector_load_raw_json_gz(tmp_path: Path) -> None:
    """测试从 RAW JSON.GZ 压缩快照加载。"""
    import gzip

    catalog_file = tmp_path / "catalog.csv"
    catalog_file.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,target_l1_code,target_l1_name,target_l2_codes,target_l2_names,description\n"
        "power,新能源,transformer,变压器,85042100,变压器,units,801730.SI,电力设备,801737.SI,电网设备,出海\n",
        encoding="utf-8-sig",
    )

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    gz_file = raw_dir / "2026-07.json.gz"
    mock_payload = {
        "data": [
            {
                "period": "202607",
                "reporterCode": 156,
                "cmdCode": "85042100",
                "cmdDesc": "液体介质变压器",
                "flowDesc": "Exports",
                "primaryValue": 9200000.0,
                "qty": 500.0,
                "qtyUnitAbbr": "units",
            }
        ]
    }
    with gzip.open(gz_file, "wt", encoding="utf-8") as f:
        json.dump(mock_payload, f)

    collector = ComtradeCollector(raw_dir=raw_dir, catalog_path=catalog_file)
    records = collector.collect()
    assert len(records) == 1
    assert records[0].export_value_usd == 9200000.0
    assert records[0].report_month == "2026-07"


def test_comtrade_collector_load_gacc_chinese_csv(tmp_path: Path) -> None:
    """测试从 GACC 官方中文导出格式 CSV 加载与解析。"""
    catalog_file = tmp_path / "catalog.csv"
    catalog_file.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,target_l1_code,target_l1_name,target_l2_codes,target_l2_names,description\n"
        "power,新能源,transformer,变压器,85042100,变压器,units,801730.SI,电力设备,801737.SI,电网设备,出海\n",
        encoding="utf-8-sig",
    )

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    csv_file = raw_dir / "gacc_2025.csv"
    csv_content = (
        '"数据年月","商品编码","商品名称","第一数量","第一计量单位","第二数量","第二计量单位","美元"\n'
        '"202501","85042100","液体介质变压器","24,950","个","13562977","千克","66,663,023"\n'
    )
    csv_file.write_text(csv_content, encoding="utf-8-sig")

    collector = ComtradeCollector(raw_dir=raw_dir, catalog_path=catalog_file)
    records = collector.collect()
    assert len(records) == 1
    rec = records[0]
    assert rec.product_key == "transformer"
    assert rec.hs_code == "85042100"
    assert rec.report_month == "2025-01"
    assert rec.export_value_usd == 66663023.0
    assert rec.export_volume == 24950.0
    assert rec.quantity_unit == "个"
    assert rec.source == "GACC"
    assert rec.release_date == date(2025, 2, 20)  # 次月 20 日统一发布


def test_comtrade_collector_load_mixed_sources_dedup(tmp_path: Path) -> None:
    """测试同时存在 UN JSON 与 GACC CSV 时的双轨融合与去重逻辑 (GACC 优于 UN)。"""
    import gzip

    catalog_file = tmp_path / "catalog.csv"
    catalog_file.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,target_l1_code,target_l1_name,target_l2_codes,target_l2_names,description\n"
        "power,新能源,transformer,变压器,85042100,变压器,units,801730.SI,电力设备,801737.SI,电网设备,出海\n",
        encoding="utf-8-sig",
    )

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)

    # 1. 写入 2024 UN 快照 (历史)
    gz_2024 = raw_dir / "2024_full.json.gz"
    payload_2024 = {
        "data": [
            {
                "period": "202412",
                "reporterCode": 156,
                "cmdCode": "85042100",
                "cmdDesc": "液体介质变压器",
                "flowDesc": "Exports",
                "primaryValue": 50000000.0,
                "qty": 20000.0,
                "qtyUnitAbbr": "units",
            }
        ]
    }
    with gzip.open(gz_2024, "wt", encoding="utf-8") as f:
        json.dump(payload_2024, f)

    # 2. 写入 2025 GACC 快照 (最新)
    csv_2025 = raw_dir / "gacc_2025.csv"
    csv_content = (
        '"数据年月","商品编码","商品名称","第一数量","第一计量单位","第二数量","第二计量单位","美元"\n'
        '"202501","85042100","液体介质变压器","24950","个","13562977","千克","66663023"\n'
    )
    csv_2025.write_text(csv_content, encoding="utf-8-sig")

    collector = ComtradeCollector(raw_dir=raw_dir, catalog_path=catalog_file)
    records = collector.collect()
    assert len(records) == 2
    assert [r.report_month for r in records] == ["2024-12", "2025-01"]
    assert records[0].source == "UN_Comtrade"
    assert records[1].source == "GACC"
    assert records[0].release_date == date(2025, 1, 20)
    assert records[1].release_date == date(2025, 2, 20)


def _mk_customs_record(
    product_key: str,
    hs_code: str,
    report_month: str,
    value: float,
    year: int,
    month: int,
) -> CustomsTradeRecord:
    """构造测试用 CustomsTradeRecord（release_date 按次月 20 日规则显式传入）。"""
    release_month = 1 if month == 12 else month + 1
    release_year = year + 1 if month == 12 else year
    return CustomsTradeRecord(
        category_key="chemicals_and_materials",
        category_name="基础化工与新材料",
        product_key=product_key,
        product_name="钛白粉",
        hs_code=hs_code,
        hs_name="二氧化钛",
        report_month=report_month,
        trade_date=date(year, month, 28),
        trade_direction="export",
        export_value_usd=value,
        export_volume=100.0,
        quantity_unit="kg",
        target_l1_code="801030.SI",
        target_l1_name="基础化工",
        target_l2_codes="801035.SI",
        target_l2_names="化学原料",
        release_date=date(release_year, release_month, 20),
    )


def test_records_to_customs_trade_frame_hs_switch_product_agg() -> None:
    """HS 2025 切换（6位→8位码）时，品类级聚合保证 YoY 序列连续不断裂。

    同一 product_key 跨税号版本（320611 → 32061190）应合并为一条连续月度序列，
    2025 年首月即可计算 YoY（而非因新税号无 12 个月前数据而全 null）。
    """
    # 2024 全年用旧 6 位码 320611，2025 年用新 8 位码 32061190，金额恒定 1000
    records = []
    for month in range(1, 13):
        records.append(
            _mk_customs_record("tio2", "320611", f"2024-{month:02d}", 1000.0, 2024, month)
        )
    records.append(_mk_customs_record("tio2", "32061190", "2025-01", 1000.0, 2025, 1))

    df = records_to_customs_trade_frame(records)
    assert df.height == 13

    jan25 = df.filter(pl.col("report_month") == "2025-01")
    assert jan25.height == 1
    # 旧实现按 hs_code 分组时 2025-01 无 12 个月前数据 → yoy 为 null
    # 新实现按 product_key 聚合 → 3MMA YoY 有值（金额恒定 → 0%）
    assert jan25["yoy_growth_3mma"][0] is not None
    assert abs(jan25["yoy_growth_3mma"][0] - 0.0) < 1e-9
    assert jan25["export_value_3mma"][0] is not None


def test_records_to_customs_trade_frame_multi_hs_same_month() -> None:
    """同一 product 同月多税号（如 mdi 29291030 + 29291090）按品类求和后回填。"""
    records = [
        _mk_customs_record("mdi", "29291030", "2025-01", 600.0, 2025, 1),
        _mk_customs_record("mdi", "29291090", "2025-01", 400.0, 2025, 1),
    ]
    df = records_to_customs_trade_frame(records)
    assert df.height == 2
    # 品类级 3MMA = 两税号求和 = 1000（仅 1 个月样本）
    for v in df["export_value_3mma"]:
        assert abs(v - 1000.0) < 1e-9
    assert df["release_date"].to_list() == [date(2025, 2, 20), date(2025, 2, 20)]
