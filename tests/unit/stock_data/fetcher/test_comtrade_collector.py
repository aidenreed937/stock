import json
from datetime import date
from pathlib import Path

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
