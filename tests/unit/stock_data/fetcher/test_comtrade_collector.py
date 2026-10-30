from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.customs import (
    CUSTOMS_TRADE_SCHEMA,
    ComtradeCollector,
    TarifflineCallLimiter,
    TarifflineCallLimitError,
    backfill_tariffline,
    empty_customs_trade,
    get_hs6_query_list,
    load_hs_catalog,
    parse_comtrade_items,
    parse_raw_csv_rows,
    records_to_customs_trade_frame,
)
from stock_data.fetcher.industry.models import CustomsTradeRecord


def test_empty_customs_trade_schema() -> None:
    """测试空表骨架 Schema 匹配。"""
    df = empty_customs_trade()
    assert df.schema == CUSTOMS_TRADE_SCHEMA
    assert df.is_empty()


def test_tariffline_call_limiter_counts_retries_and_stops_at_budget() -> None:
    limiter = TarifflineCallLimiter(max_calls=2, min_interval_seconds=0)

    assert limiter.acquire() == 1
    assert limiter.acquire() == 2
    with pytest.raises(TarifflineCallLimitError):
        limiter.acquire()
    assert limiter.calls == 2


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
            target_l3_codes="857381.SI",
            target_l3_names="输变电设备",
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
            target_l3_codes="857381.SI",
            target_l3_names="输变电设备",
        ),
    ]

    df = records_to_customs_trade_frame(records)
    assert not df.is_empty()
    assert df.height == 2
    assert "export_value_3mma" in df.columns
    assert "yoy_growth_3mma" in df.columns
    assert "export_asp_usd" in df.columns
    assert "target_l3_codes" in df.columns
    assert "target_l3_names" in df.columns

    # 验证均价 ASP = 1000000 / 500 = 2000.0 美元/台
    assert abs(df["export_asp_usd"][0] - 2000.0) < 1e-6
    assert df["target_l3_codes"].to_list() == ["857381.SI", "857381.SI"]
    assert df["target_l3_names"].to_list() == ["输变电设备", "输变电设备"]
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
    assert collector._catalog_map["85042100"]["hs_level"] == "8"
    assert collector._catalog_map["85042100"]["hs_parent_code"] == "850421"
    assert collector.get_hs6_query_list() == ["850421"]


def test_comtrade_catalog_parent_and_child_codes_are_not_queried_twice() -> None:
    """医药目录的 HS6 父级与中国 8 位子目只形成一个 Comtrade 查询码。"""
    catalog_file = Path("config/data/customs/good_h8_codes.csv")
    catalog_map = load_hs_catalog(catalog_file)
    query_codes = get_hs6_query_list(catalog_file)

    assert query_codes.count("300490") == 1
    assert query_codes.count("300220") == 1
    assert query_codes.count("300241") == 1
    assert catalog_map["30049010"]["description"].startswith("中国海关8位子目")
    # catalog 全面 8 位码化后不再维护显式 6 位父行；6 位前缀由 8 位子行合成兜底
    assert catalog_map["300490"]["product_key"] == "pharma_chemicals"
    assert catalog_map["300490"]["hs_level"] == "8"
    assert catalog_map["30022000"]["description"].startswith("HS2017中国海关8位历史子目")
    assert catalog_map["300220"]["product_key"] == "pharma_vaccines"
    assert catalog_map["300241"]["product_key"] == "pharma_vaccines"


def test_comtrade_catalog_prefers_explicit_parent_mapping() -> None:
    """同一 HS6 下多八位产品时映射正确：无显式 6 位父行，父级由 8 位子行合成。"""
    catalog_map = load_hs_catalog(Path("config/data/customs/good_h8_codes.csv"))

    # 850440 父级由 8 位子行合成（产品键一致）
    assert catalog_map["850440"]["product_key"] == "inverter"
    assert catalog_map["850440"]["hs_level"] == "8"
    assert catalog_map["85044030"]["product_key"] == "inverter"
    # 851762 品目混合（光通讯/网络设备/无线耳机），6 位前缀由首个 8 位子行合成兜底，
    # 回退到 85176211（network_equipment）；子行 85176294 无线耳机独立归消费电子
    assert catalog_map["851762"]["hs_code"] == "85176211"
    assert catalog_map["851762"]["hs_level"] == "8"
    assert catalog_map["851762"]["product_key"] == "network_equipment"
    assert catalog_map["85176294"]["product_key"] == "wireless_earbud"


def test_comtrade_snapshot_names_are_directional_with_legacy_export_support(tmp_path: Path) -> None:
    """新快照按方向命名，同时继续识别旧的无后缀出口快照。"""
    from stock_data.fetcher.industry.customs.collectors.comtrade import _snapshot_exists

    legacy_export = tmp_path / "2022_full.json.gz"
    legacy_export.touch()
    assert _snapshot_exists(tmp_path, 2022, "X")
    assert not _snapshot_exists(tmp_path, 2022, "M")

    legacy_export.rename(tmp_path / "2022_full_X.json.gz")
    import_snapshot = tmp_path / "2022_full_M.json.gz"
    import_snapshot.touch()
    assert _snapshot_exists(tmp_path, 2022, "X")
    assert _snapshot_exists(tmp_path, 2022, "M")


def test_comtrade_parser_maps_photovoltaic_historical_codes_and_flow() -> None:
    """历史 HS 版本应归入稳定品类，并保留进口/出口方向。"""
    catalog_file = Path("config/data/customs/good_h8_codes.csv")
    catalog_map = load_hs_catalog(catalog_file)
    assert catalog_map["280461"]["target_l3_codes"] == "857351.SI"
    assert catalog_map["854140"]["target_l3_codes"] == "857352.SI"
    assert catalog_map["854143"]["target_l3_codes"] == "857352.SI"
    assert catalog_map["28429040"]["product_key"] == "cathode_material"
    assert catalog_map["28269020"]["product_key"] == "electrolyte_salt"
    assert catalog_map["39211990"]["target_l3_codes"] == "857372.SI"
    assert catalog_map["85023100"]["target_l3_codes"] == "857361.SI"
    assert catalog_map["85030030"]["target_l3_codes"] == "857362.SI"
    # 87024000 历史码已被现行细分 87024010/20/30 取代（2026 税则），断言现行码映射
    assert catalog_map["87024010"]["target_l2_codes"] == "801096.SI"
    assert catalog_map["87024020"]["target_l3_codes"] == "850913.SI"
    records = parse_comtrade_items(
        [
            {
                "flowCode": "M",
                "cmdCode": "280461",
                "period": "202501",
                "primaryValue": 1200,
                "netWgt": 50000,
            },
            {
                "flowCode": "X",
                "cmdCode": "280461",
                "period": "202501",
                "primaryValue": 300,
                "qty": 10000,
            },
            {
                "flowCode": "X",
                "cmdCode": "854140",
                "period": "202101",
                "primaryValue": 800,
                "qty": 900,
            },
        ],
        catalog_map,
    )

    assert {(record.product_key, record.hs_code, record.trade_direction) for record in records} == {
        ("polysilicon", "280461", "import"),
        ("polysilicon", "280461", "export"),
        ("solar_cell", "854140", "export"),
    }
    import_record = next(record for record in records if record.trade_direction == "import")
    assert import_record.export_volume == 50000.0
    assert import_record.target_l3_codes == "857351.SI"
    solar_record = next(record for record in records if record.product_key == "solar_cell")
    assert solar_record.target_l3_codes == "857352.SI"
    assert solar_record.target_l3_names == "光伏电池组件"


def test_comtrade_catalog_maps_p0_global_pricing_codes() -> None:
    catalog_map = load_hs_catalog(Path("config/data/customs/good_h8_codes.csv"))
    expected = {
        "740311": ("801055.SI", "850552.SI"),
        "740811": ("801055.SI", "850552.SI"),
        "741011": ("801055.SI", "850552.SI"),
        "760110": ("801055.SI", "850551.SI"),
        "720825": ("801044.SI", "850442.SI"),
        "721049": ("801044.SI", "850442.SI"),
        "722550": ("801045.SI", "850401.SI"),
        "730439": ("801044.SI", "850443.SI"),
        "270112": ("801951.SI", "859512.SI"),
        "270400": ("801952.SI", "859521.SI"),
        "271019": ("801963.SI", "859631.SI"),
    }

    assert {
        code: (catalog_map[code]["target_l2_codes"], catalog_map[code]["target_l3_codes"])
        for code in expected
    } == expected


def test_comtrade_catalog_maps_p1_industry_codes() -> None:
    catalog_map = load_hs_catalog(Path("config/data/customs/good_h8_codes.csv"))
    expected = {
        "871160": ("801881.SI", "858812.SI"),
        "401110": ("801093.SI", "850924.SI"),
        "845710": ("801072.SI", "850711.SI"),
        "610910": ("801132.SI", "851329.SI"),
        "630260": ("801132.SI", "851326.SI"),
        "940360": ("801142.SI", "851437.SI"),
        "845011": ("801111.SI", "851116.SI"),
        "852872": ("801112.SI", "851121.SI"),
        "851713": ("801085.SI", "850853.SI"),
        "847130": ("801085.SI", "850853.SI"),
        "852411": ("801084.SI", "850831.SI"),
    }

    assert {
        code: (catalog_map[code]["target_l2_codes"], catalog_map[code]["target_l3_codes"])
        for code in expected
    } == expected


def test_comtrade_catalog_maps_p1_chemicals_and_pharma_codes() -> None:
    catalog_map = load_hs_catalog(Path("config/data/customs/good_h8_codes.csv"))
    expected = {
        "310210": ("801038.SI", "850331.SI"),
        "310230": ("801038.SI", "850331.SI"),
        "310311": ("801038.SI", "850332.SI"),
        "310530": ("801038.SI", "850332.SI"),
        "310540": ("801038.SI", "850332.SI"),
        "310420": ("801038.SI", "850336.SI"),
        "310520": ("801038.SI", "850381.SI"),
        "283620": ("801033.SI", "850321.SI"),
        "281511": ("801033.SI", "850322.SI"),
        "281512": ("801033.SI", "850322.SI"),
        "540233": ("801032.SI", "850341.SI"),
        "540752": ("801131.SI", "851314.SI"),
        "540231": ("801032.SI", "850346.SI"),
        "550320": ("801032.SI", "850341.SI"),
        "550410": ("801032.SI", "850343.SI"),
        "293621": ("801151.SI", "851511.SI"),
        "293627": ("801151.SI", "851511.SI"),
        "293628": ("801151.SI", "851511.SI"),
        "293629": ("801151.SI", "851511.SI"),
        "294110": ("801151.SI", "851511.SI"),
        "294120": ("801151.SI", "851511.SI"),
        "294130": ("801151.SI", "851511.SI"),
        "294190": ("801151.SI", "851511.SI"),
        "292429": ("801151.SI", "851511.SI"),
    }

    assert set(expected) <= set(catalog_map)
    assert {
        code: (catalog_map[code]["target_l2_codes"], catalog_map[code]["target_l3_codes"])
        for code in expected
    } == expected

    assert catalog_map["310210"]["product_key"] == "urea"
    assert catalog_map["540231"]["product_key"] == "nylon_filament"
    assert catalog_map["293628"]["product_key"] == "vitamins"
    assert catalog_map["294190"]["product_key"] == "antibiotics"
    assert catalog_map["292429"]["product_key"] == "api_paracetamol"


def test_comtrade_catalog_maps_p0_and_p2_gap_codes() -> None:
    catalog_map = load_hs_catalog(Path("config/data/customs/good_h8_codes.csv"))
    expected = {
        "710691": ("801053.SI", "850532.SI"),
        "710692": ("801053.SI", "850532.SI"),
        "790111": ("801055.SI", "850553.SI"),
        "790112": ("801055.SI", "850553.SI"),
        "847149": ("801101.SI", "850703.SI"),
        "847150": ("801101.SI", "850703.SI"),
        "851830": ("801085.SI", "850853.SI"),
        "848610": ("801081.SI", "850818.SI"),
        "848620": ("801081.SI", "850818.SI"),
        "848690": ("801081.SI", "850818.SI"),
        "700510": ("801712.SI", "857121.SI"),
        "700521": ("801712.SI", "857121.SI"),
        "700529": ("801712.SI", "857121.SI"),
        "701912": ("801712.SI", "857122.SI"),
        "701919": ("801712.SI", "857122.SI"),
        "701990": ("801712.SI", "857122.SI"),
        "280920": ("801038.SI", "850332.SI"),
        "290511": ("801033.SI", "850325.SI"),
        "290531": ("801033.SI", "850325.SI"),
        "300215": ("801153.SI", "851534.SI"),
        "130219": ("801155.SI", "851521.SI"),
        "842951": ("801077.SI", "850771.SI"),
        "842620": ("801077.SI", "850771.SI"),
        "842641": ("801077.SI", "850771.SI"),
        "690721": ("801713.SI", "850614.SI"),
        "690911": ("801713.SI", "850614.SI"),
    }

    assert set(expected) <= set(catalog_map)
    assert {
        code: (catalog_map[code]["target_l2_codes"], catalog_map[code]["target_l3_codes"])
        for code in expected
    } == expected


def test_comtrade_fetch_api_forwards_flow_code(tmp_path: Path, monkeypatch) -> None:
    """在线请求应把调用方指定的进口/出口方向传给 SDK，并按方向命名快照。"""
    import comtradeapicall
    import pandas as pd

    calls: list[dict[str, object]] = []

    def fake_get_final_data(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            [
                {
                    "flowCode": kwargs["flowCode"],
                    "cmdCode": "280461",
                    "period": "202601",
                    "primaryValue": 1,
                }
            ]
        )

    monkeypatch.setattr(comtradeapicall, "getFinalData", fake_get_final_data)
    catalog_file = tmp_path / "catalog.csv"
    catalog_file.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,target_l1_code,target_l1_name,target_l2_codes,target_l2_names,description\n"
        "power_and_new_energy,新能源与电力设备,polysilicon,多晶硅,28046190,多晶硅,kg,801730.SI,电力设备,801732.SI,光伏设备,测试\n",
        encoding="utf-8-sig",
    )
    collector = ComtradeCollector(
        raw_dir=tmp_path / "raw", catalog_path=catalog_file, subscription_key="test-key"
    )

    rows = collector.fetch_api(period="202601", flow_code="M,X")

    assert rows[0]["flowCode"] == "M,X"
    assert calls[0]["flowCode"] == "M,X"
    assert (tmp_path / "raw" / "202601_M_X.json.gz").exists()


def test_comtrade_fetch_api_splits_long_hs_query(tmp_path: Path, monkeypatch) -> None:
    """HS 目录较大时应分批请求，避免单次 URL 超过 Comtrade 限制。"""
    import comtradeapicall
    import pandas as pd

    catalog_rows = [
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names,description"
    ]
    for index in range(120):
        code = f"{100000 + index:06d}"
        catalog_rows.append(
            f"test,测试,product_{index},测试产品,{code},测试税号,kg,801030.SI,基础化工,"
            "801033.SI,化学原料,测试"
        )
    catalog_file = tmp_path / "catalog.csv"
    catalog_file.write_text("\n".join(catalog_rows) + "\n", encoding="utf-8-sig")

    calls: list[dict[str, object]] = []

    def fake_get_final_data(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            [
                {
                    "flowCode": "X",
                    "cmdCode": str(kwargs["cmdCode"]).split(",")[0],
                    "period": "202201",
                    "primaryValue": 1,
                }
            ]
        )

    monkeypatch.setattr(comtradeapicall, "getFinalData", fake_get_final_data)
    collector = ComtradeCollector(
        raw_dir=tmp_path / "raw", catalog_path=catalog_file, subscription_key="test-key"
    )

    rows = collector.fetch_api(period="202201", flow_code="X")

    assert len(calls) > 1
    assert all(len(str(call["cmdCode"])) <= 600 for call in calls)
    assert len(rows) == len(calls)
    assert (tmp_path / "raw" / "202201_X.json.gz").exists()


def test_comtrade_tariffline_fetches_parent_codes_and_keeps_raw_separate(
    tmp_path: Path, monkeypatch
) -> None:
    """Tariffline 应用六位父码查询八位子目，并写入独立 RAW 目录。"""
    import pandas as pd

    import stock_data.fetcher.industry.customs.collectors.tariffline as tariffline_module

    calls: list[dict[str, object]] = []

    def fake_get_tariffline_data(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            [
                {
                    "flowCode": "X",
                    "cmdCode": "25041010",
                    "period": "202401",
                    "primaryValue": 100,
                }
            ]
        )

    monkeypatch.setattr(tariffline_module, "_fetch_tariffline_dataframe", fake_get_tariffline_data)
    catalog_file = tmp_path / "catalog.csv"
    catalog_file.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names,description\n"
        "raw_material,原料,graphite,天然石墨,25041000,天然石墨,kg,801000.SI,材料,"
        "801001.SI,非金属材料,测试\n",
        encoding="utf-8-sig",
    )
    tariffline_dir = tmp_path / "tariffline"
    collector = ComtradeCollector(
        catalog_path=catalog_file,
        subscription_key="test-key",
        tariffline_raw_dir=tariffline_dir,
    )

    rows = collector.fetch_tariffline_api(period="202401", cmd_codes=["250410"])

    assert rows[0]["cmdCode"] == "25041010"
    assert collector.get_tariffline_query_list() == ["250410"]
    assert calls[0]["clCode"] == "HS"
    assert calls[0]["cmdCode"] == "250410"
    assert calls[0]["maxRecords"] == 100000
    assert calls[0]["partnerCode"] is None
    assert calls[0]["customsCode"] is None
    snapshot_files = list(tariffline_dir.glob("period=202401-202401/flow=X/batch=*/data.parquet"))
    assert len(snapshot_files) == 1


def test_tariffline_http_uses_long_read_timeout(monkeypatch) -> None:
    """Tariffline HTTP 请求不能被 SDK 默认的 120 秒读取超时截断。"""
    import pandas as pd
    import requests

    import stock_data.fetcher.industry.customs.collectors.tariffline as tariffline_module

    request: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"flowCode": "X", "cmdCode": "25041010"}]}

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        request.update({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(requests, "get", fake_get)
    frame = tariffline_module._fetch_tariffline_dataframe(
        subscription_key="test-key",
        typeCode="C",
        freqCode="M",
        clCode="HS",
        period="202401",
        reporterCode="156",
        cmdCode="250410",
        flowCode="M,X",
        partnerCode=None,
        partner2Code=None,
        customsCode=None,
        motCode=None,
        maxRecords=100000,
        format_output="JSON",
        includeDesc=True,
    )

    assert isinstance(frame, pd.DataFrame)
    assert request["url"] == "https://comtradeapi.un.org/data/v1/getTariffline/C/M/HS"
    assert request["timeout"] == (30, 3600)
    assert request["params"]["flowCode"] == "M,X"
    assert request["params"]["subscription-key"] == "test-key"


def test_tariffline_backfill_splits_writes_and_resumes(tmp_path: Path, monkeypatch) -> None:
    """Tariffline 回填应触顶拆分、逐批落盘，并跳过已完成批次。"""
    import pandas as pd

    import stock_data.fetcher.industry.customs.collectors.tariffline as tariffline_module

    calls: list[dict[str, object]] = []

    def fake_get_tariffline_data(**kwargs):
        calls.append(kwargs)
        period = str(kwargs["period"])
        if period == "202401,202402":
            return pd.DataFrame(
                [
                    {"flowCode": "X", "cmdCode": "25041010", "period": "202401"},
                    {"flowCode": "X", "cmdCode": "25041091", "period": "202402"},
                ]
            )
        return pd.DataFrame([{"flowCode": "X", "cmdCode": "25041010", "period": period}])

    monkeypatch.setattr(tariffline_module, "_fetch_tariffline_dataframe", fake_get_tariffline_data)
    raw_dir = tmp_path / "tariffline"

    summary = backfill_tariffline(
        subscription_key="test-key",
        raw_dir=raw_dir,
        cmd_codes=["250410"],
        start_month="2024-01",
        end_month="2024-02",
        flow_code="X",
        batch_months=2,
        max_records=2,
        retries=0,
        retry_sleep_seconds=0,
        request_sleep_seconds=0,
        isolate_requests=False,
    )

    assert summary.requested_batches == 1
    assert summary.split_batches == 1
    assert summary.completed_batches == 2
    assert summary.truncated_batches == 0
    assert len(list(raw_dir.glob("**/data.parquet"))) == 2
    assert len(calls) == 3

    calls.clear()
    resumed = backfill_tariffline(
        subscription_key="test-key",
        raw_dir=raw_dir,
        cmd_codes=["250410"],
        start_month="2024-01",
        end_month="2024-02",
        flow_code="X",
        batch_months=2,
        max_records=2,
        retries=0,
        retry_sleep_seconds=0,
        request_sleep_seconds=0,
        isolate_requests=False,
    )

    assert resumed.skipped_batches == 2
    assert resumed.attempted_requests == 0
    assert calls == []
    assert len(raw_dir.joinpath("tariffline_manifest.jsonl").read_text().splitlines()) == 2


def test_tariffline_backfill_batches_parent_codes(tmp_path: Path, monkeypatch) -> None:
    """多个 HS6 父码应合并为一个安全请求批次。"""
    import pandas as pd

    import stock_data.fetcher.industry.customs.collectors.tariffline as tariffline_module

    calls: list[dict[str, object]] = []

    def fake_get_tariffline_data(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame([{"flowCode": "X", "cmdCode": "25041010", "period": "202401"}])

    monkeypatch.setattr(tariffline_module, "_fetch_tariffline_dataframe", fake_get_tariffline_data)
    summary = backfill_tariffline(
        subscription_key="test-key",
        raw_dir=tmp_path / "tariffline",
        cmd_codes=["250410", "250411", "250412"],
        start_month="2024-01",
        end_month="2024-01",
        flow_code="X",
        batch_codes=2,
        retries=0,
        retry_sleep_seconds=0,
        request_sleep_seconds=0,
        isolate_requests=False,
    )

    assert summary.requested_batches == 2
    assert summary.completed_batches == 2
    assert len(calls) == 2
    assert calls[0]["cmdCode"] == "250410,250411"
    assert calls[1]["cmdCode"] == "250412"


def test_tariffline_backfill_parallel_workers_share_limiter(tmp_path: Path, monkeypatch) -> None:
    """并行月份/父码任务应共享同一个 Tariffline 调用节流器。"""
    import pandas as pd

    import stock_data.fetcher.industry.customs.collectors.tariffline as tariffline_module

    calls: list[dict[str, object]] = []

    def fake_get_tariffline_data(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            [{"flowCode": "X", "cmdCode": str(kwargs["cmdCode"]), "period": "202401"}]
        )

    monkeypatch.setattr(tariffline_module, "_fetch_tariffline_dataframe", fake_get_tariffline_data)
    summary = backfill_tariffline(
        subscription_key="test-key",
        raw_dir=tmp_path / "tariffline",
        cmd_codes=["250410", "250411"],
        start_month="2024-01",
        end_month="2024-01",
        flow_code="X",
        batch_codes=1,
        workers=2,
        retries=0,
        retry_sleep_seconds=0,
        request_sleep_seconds=0,
        isolate_requests=False,
    )

    assert summary.completed_batches == 2
    assert summary.api_calls_used == 2
    assert {str(call["cmdCode"]) for call in calls} == {"250410", "250411"}


def test_customs_parsers_skip_rows_without_required_value() -> None:
    catalog_map = {"850421": {"product_key": "transformer", "quantity_unit": "units"}}

    assert (
        parse_comtrade_items(
            [{"flowCode": "X", "cmdCode": "850421", "period": "202501"}], catalog_map
        )
        == []
    )
    api_zero = parse_comtrade_items(
        [{"flowCode": "X", "cmdCode": "850421", "period": "202501", "primaryValue": 0}],
        catalog_map,
    )
    assert len(api_zero) == 1
    assert api_zero[0].export_value_usd == 0.0

    assert parse_raw_csv_rows([{"hs_code": "850421", "report_month": "2025-01"}], catalog_map) == []
    csv_zero = parse_raw_csv_rows(
        [{"hs_code": "850421", "report_month": "2025-01", "export_value_usd": "0"}],
        catalog_map,
    )
    assert len(csv_zero) == 1
    assert csv_zero[0].export_value_usd == 0.0


def test_customs_raw_csv_parser_preserves_l3_catalog_mapping() -> None:
    catalog_map = {
        "280461": {
            "product_key": "polysilicon",
            "quantity_unit": "kg",
            "target_l3_codes": "857351.SI",
            "target_l3_names": "硅料硅片",
        }
    }

    records = parse_raw_csv_rows(
        [{"hs_code": "28046190", "report_month": "2025-01", "export_value_usd": "1200"}],
        catalog_map,
    )

    assert len(records) == 1
    assert records[0].target_l3_codes == "857351.SI"
    assert records[0].target_l3_names == "硅料硅片"


def test_customs_curated_schema_evolves_old_parquet_with_l3_columns(tmp_path: Path) -> None:
    old_path = tmp_path / "old_customs_trade.parquet"
    old_frame = pl.DataFrame(
        {
            "product_key": ["polysilicon"],
            "hs_code": ["28046190"],
            "report_month": ["2025-01"],
            "trade_direction": ["export"],
            "trade_date": [date(2025, 1, 31)],
            "export_value_usd": [1200.0],
        }
    )
    old_frame.write_parquet(old_path)

    new_record = CustomsTradeRecord(
        category_key="power_and_new_energy",
        category_name="新能源与电力设备",
        product_key="polysilicon",
        product_name="多晶硅",
        hs_code="28046190",
        hs_name="多晶硅",
        report_month="2025-02",
        trade_date=date(2025, 2, 28),
        trade_direction="export",
        export_value_usd=1300.0,
        target_l3_codes="857351.SI",
        target_l3_names="硅料硅片",
    )

    frame = records_to_customs_trade_frame([new_record])
    assert (
        save_curated_fact(
            frame,
            old_path,
            primary_keys=["product_key", "hs_code", "report_month", "trade_direction"],
        )
        == 2
    )
    loaded = pl.read_parquet(old_path)
    assert set(loaded.columns) == set(CUSTOMS_TRADE_SCHEMA)
    assert loaded.schema == frame.schema
    assert loaded.filter(pl.col("report_month") == "2025-01")["target_l3_codes"][0] is None
    assert loaded.filter(pl.col("report_month") == "2025-02")["target_l3_codes"][0] == "857351.SI"


def test_csv_direction_comes_from_filename_without_rewriting_raw(tmp_path: Path) -> None:
    """手工 CSV 不改列，加载器按文件名注入进出口方向。"""
    csv_text = (
        "数据年月,商品编码,商品名称,第一数量,第一计量单位,美元\n"
        "202501,28046190,多晶硅,50000,千克,1200\n"
    )
    export_path = tmp_path / "trade_export_2025.csv"
    import_path = tmp_path / "trade_import_2025.csv"
    export_path.write_text(csv_text, encoding="utf-8-sig")
    import_path.write_text(csv_text, encoding="utf-8-sig")
    collector = ComtradeCollector(raw_dir=tmp_path / "raw")

    export_record = collector.load_from_raw_csv(export_path)[0]
    import_record = collector.load_from_raw_csv(import_path)[0]

    assert export_record.trade_direction == "export"
    assert import_record.trade_direction == "import"
    assert "trade_direction" not in export_path.read_text(encoding="utf-8-sig").splitlines()[0]


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
