"""光伏全产业链 (硅料/硅片/电池片/装机/供需剪刀差) 数据管道单元测试。"""

from datetime import date

import polars as pl
import pytest

from stock_data.fetcher.industry.contracts import IndustryCollectionResult
from stock_data.fetcher.industry.models import (
    SolarCapacityRecord,
    SolarCellNbsRecord,
)
from stock_data.fetcher.industry.power.collectors.nbs import NbsSolarCellCollector
from stock_data.fetcher.industry.power.collectors.nea import SolarCollector
from stock_data.fetcher.industry.power.collectors.silicon import (
    SiliconBranchCollector,
    get_polysilicon_annual_capacity,
    parse_silicon_branch_bulletin_text,
)
from stock_data.fetcher.industry.power.transforms import (
    POLYSILICON_BALANCE_MONTHLY_SCHEMA,
    POLYSILICON_INVENTORY_MONTHLY_SCHEMA,
    POLYSILICON_SUPPLY_MONTHLY_SCHEMA,
    PV_WAFER_MONTHLY_SCHEMA,
    SOLAR_SUPPLY_DEMAND_SCHEMA,
    build_polysilicon_balance_frame,
    build_polysilicon_inventory_from_silicon_frame,
    build_polysilicon_supply_from_silicon_frame,
    build_pv_wafer_from_silicon_frame,
    build_solar_supply_demand_frame,
    empty_polysilicon_balance,
    empty_polysilicon_inventory,
    empty_polysilicon_supply,
    empty_pv_wafer,
    empty_silicon_wafer_monthly,
    empty_solar_supply_demand,
    records_to_polysilicon_inventory_frame,
    records_to_polysilicon_supply_frame,
    records_to_pv_wafer_frame,
    records_to_silicon_wafer_monthly_frame,
    records_to_solar_cell_nbs_frame,
    records_to_solar_frame,
)


def _write_silicon_fixture(raw_dir):
    silicon_file = raw_dir / "power" / "silicon_wafer_monthly.csv"
    silicon_file.parent.mkdir(parents=True)
    silicon_file.write_text(
        "report_month,trade_date,polysilicon_output_w_tons,polysilicon_output_yoy,"
        "polysilicon_operating_rate,derived_polysilicon_utilization_rate,wafer_output_gw,"
        "wafer_output_yoy,wafer_operating_rate,derived_wafer_utilization_rate,"
        "polysilicon_inventory_w_tons,unit,source,source_url,release_date,data_status,collected_at\n"
        "2025-01,2025-01-31,9.44,-3.0,38.11,32.55,44.71,1.2,41.0,42.21,38.2,"
        "ten_thousand_tons_and_gw,Silicon_Branch_Antaike,http://www.silicon.net.cn/,"
        "2025-02-07,actual,2026-09-02T00:00:00Z\n"
        "2025-02,2025-02-28,9.50,-2.0,39.00,32.80,45.00,1.5,42.0,42.50,39.0,"
        "ten_thousand_tons_and_gw,Silicon_Branch_Antaike,http://www.silicon.net.cn/,"
        "2025-03-07,verified_industry_report,2026-09-02T00:00:00Z\n"
        "2025-03,2025-03-31,9.70,-1.0,40.00,33.00,46.00,2.0,43.0,43.50,40.0,"
        "ten_thousand_tons_and_gw,CPIA/Silicon_Branch_Reconstructed,http://www.silicon.net.cn/,"
        "2025-04-07,reconstructed,2026-09-02T00:00:00Z\n"
        "2025-04,2025-04-30,,,,,,,,,,ten_thousand_tons_and_gw,"
        "Silicon_Branch_Antaike,http://www.silicon.net.cn/,,missing_unverified,"
        "2026-09-02T00:00:00Z\n",
        encoding="utf-8",
    )
    return silicon_file


def _write_capacity_fixture(raw_dir):
    capacity_file = raw_dir / "power" / "polysilicon_wafer_capacity_annual.csv"
    capacity_file.parent.mkdir(parents=True, exist_ok=True)
    capacity_file.write_text(
        "year,polysilicon_capacity_w_tons,polysilicon_output_w_tons,"
        "polysilicon_utilization_rate,wafer_capacity_gw,wafer_output_gw,"
        "wafer_utilization_rate,source\n"
        "2025,347.9,136.7,39.3,1271.1,719.3,56.6,CPIA\n",
        encoding="utf-8",
    )
    return capacity_file


class _EmptySiliconCrawler:
    def fetch_latest(self, *, force=False):
        del force
        return IndustryCollectionResult([], status="EMPTY")


def test_parse_silicon_branch_bulletin_text() -> None:
    sample_text = (
        "2025年1月我国多晶硅产量为 9.67 万吨，环比减少 6.84%。"
        "装置年产能 10 万吨以上企业开工率为 38.11%。"
        "1月单晶硅片产出 44.71 GW，环比下降 2.61%，国内整体硅片行业开工率在 41.0% 左右。"
        "截至1月底国内多晶硅库存小幅降至 38.2 万吨。"
    )
    parsed = parse_silicon_branch_bulletin_text(sample_text)
    assert parsed["polysilicon_output_w_tons"] == 9.67
    assert parsed["polysilicon_operating_rate"] == 38.11
    assert parsed["wafer_output_gw"] == 44.71
    assert parsed["wafer_operating_rate"] == 41.0
    assert parsed["polysilicon_inventory_w_tons"] == 38.2


def test_silicon_branch_collector_load(tmp_path) -> None:
    _write_silicon_fixture(tmp_path)
    collector = SiliconBranchCollector(raw_dir=tmp_path, crawler=_EmptySiliconCrawler())
    records = collector.collect()
    assert len(records) == 2
    assert {r.data_status for r in records} == {"actual", "verified_industry_report"}

    # 验证已核验官方一手通报月份有准确真实值 (2025-01)
    verified_2025_01 = next(r for r in records if r.report_month == "2025-01")
    assert verified_2025_01.polysilicon_output_w_tons == 9.44
    assert verified_2025_01.derived_polysilicon_utilization_rate == 32.55
    assert verified_2025_01.wafer_output_gw == 44.71
    assert verified_2025_01.derived_wafer_utilization_rate == 42.21
    assert verified_2025_01.data_status == "actual"

    verified_2025_02 = next(r for r in records if r.report_month == "2025-02")
    assert verified_2025_02.data_status == "verified_industry_report"

    # 验证单调递增性
    for i in range(1, len(records)):
        assert records[i].trade_date > records[i - 1].trade_date


def test_specialized_collectors(tmp_path) -> None:
    _write_silicon_fixture(tmp_path)
    _write_capacity_fixture(tmp_path)
    collector = SiliconBranchCollector(raw_dir=tmp_path, crawler=_EmptySiliconCrawler())
    supply_records = collector.collect_supply()
    inventory_records = collector.collect_inventory()
    wafer_records = collector.collect_wafer()

    assert len(supply_records) == 2
    assert len(inventory_records) == 2
    assert len(wafer_records) == 2

    # 验证供给表转换
    supply_df = records_to_polysilicon_supply_frame(supply_records)
    assert len(supply_df) == len(supply_records)
    assert supply_df.schema == POLYSILICON_SUPPLY_MONTHLY_SCHEMA
    assert supply_df["production_yoy"].to_list() == [-0.03, -0.02]

    # 验证库存表转换
    inv_df = records_to_polysilicon_inventory_frame(inventory_records)
    assert len(inv_df) == len(inventory_records)
    assert inv_df.schema == POLYSILICON_INVENTORY_MONTHLY_SCHEMA

    # 验证硅片表转换
    wafer_df = records_to_pv_wafer_frame(wafer_records)
    assert len(wafer_df) == len(wafer_records)
    assert wafer_df.schema == PV_WAFER_MONTHLY_SCHEMA
    assert wafer_df["wafer_output_yoy"].to_list() == [0.012, 0.015]

    # 验证供需平衡表构建
    balance_df = build_polysilicon_balance_frame(supply_df, wafer_df, inv_df)
    assert len(balance_df) == len(supply_df)
    assert balance_df.schema == POLYSILICON_BALANCE_MONTHLY_SCHEMA

    row_2025_01 = balance_df.filter(pl.col("report_month") == "2025-01").to_dicts()[0]
    assert row_2025_01["domestic_production_w_tons"] == 9.44
    assert row_2025_01["net_imports_w_tons"] is None
    assert row_2025_01["implied_demand_w_tons"] == pytest.approx(9.1656)
    assert row_2025_01["total_supply_w_tons"] == pytest.approx(9.44)
    assert row_2025_01["theoretical_surplus_w_tons"] == pytest.approx(0.2744)


def test_polysilicon_balance_uses_customs_net_imports(tmp_path) -> None:
    """平衡表按进口量减出口量计算海关净进口，并折算为万吨。"""
    _write_silicon_fixture(tmp_path)
    collector = SiliconBranchCollector(raw_dir=tmp_path, crawler=_EmptySiliconCrawler())
    supply_df = records_to_polysilicon_supply_frame(collector.collect_supply())
    wafer_df = records_to_pv_wafer_frame(collector.collect_wafer())
    customs_df = pl.DataFrame(
        {
            "category_key": ["polysilicon", "polysilicon"],
            "hs_code": ["280461", "280461"],
            "report_month": ["2025-01", "2025-01"],
            "trade_direction": ["import", "export"],
            "export_volume": [50000.0, 10000.0],
        }
    )

    balance_df = build_polysilicon_balance_frame(supply_df, wafer_df, customs_df=customs_df)
    row = balance_df.filter(pl.col("report_month") == "2025-01").to_dicts()[0]

    assert row["net_imports_w_tons"] == pytest.approx(0.004)
    assert row["total_supply_w_tons"] == pytest.approx(9.444)
    assert row["theoretical_surplus_w_tons"] == pytest.approx(0.2784)


def test_polysilicon_capacity_loaded_from_raw(tmp_path) -> None:
    _write_capacity_fixture(tmp_path)
    assert get_polysilicon_annual_capacity(2025, raw_dir=tmp_path) == 347.9
    assert get_polysilicon_annual_capacity(2026, raw_dir=tmp_path) is None


def test_solar_capacity_first_cumulative_month_is_not_estimated(tmp_path) -> None:
    class FakeCrawler:
        def fetch_latest_bulletins(self):
            return {
                "2024-05": {"cumulative_gw": 690.0, "url": "http://test/2024-05"},
                "2024-06": {"cumulative_gw": 710.0, "url": "http://test/2024-06"},
            }

    collector = SolarCollector(raw_dir=tmp_path)
    collector.crawler = FakeCrawler()
    records = collector.collect(force=True)

    rows = {record.report_month: record for record in records}
    assert rows["2024-05"].monthly_new_capacity_gw is None
    assert rows["2024-06"].monthly_new_capacity_gw == 20.0


def test_build_solar_supply_demand_frame() -> None:
    cell_records = [
        SolarCellNbsRecord(
            report_month="2024-05",
            trade_date=date(2024, 5, 31),
            output_current=5500.0,  # 55 GW
            output_yoy=30.0,
        ),
        SolarCellNbsRecord(
            report_month="2024-06",
            trade_date=date(2024, 6, 30),
            output_current=6000.0,  # 60 GW
            output_yoy=25.0,
        ),
    ]
    install_records = [
        SolarCapacityRecord(
            report_month="2024-05",
            trade_date=date(2024, 5, 31),
            monthly_new_capacity_gw=19.04,
            yoy_growth=0.476,  # NEA 源口径为小数比率 (47.6%)
        ),
        SolarCapacityRecord(
            report_month="2024-06",
            trade_date=date(2024, 6, 30),
            monthly_new_capacity_gw=20.0,
            yoy_growth=0.15,
        ),
    ]
    cell_df = records_to_solar_cell_nbs_frame(cell_records)
    install_df = records_to_solar_frame(install_records)

    sd_df = build_solar_supply_demand_frame(cell_df, install_df)
    assert len(sd_df) == 2
    assert sd_df.schema == SOLAR_SUPPLY_DEMAND_SCHEMA

    row0 = sd_df.filter(pl.col("report_month") == "2024-05").to_dicts()[0]
    assert row0["supply_cell_gw"] == 55.0
    assert row0["demand_install_gw"] == 19.04
    assert row0["monthly_surplus_gw"] == pytest.approx(35.96, rel=1e-3)
    assert row0["domestic_absorption_ratio"] == pytest.approx(0.3462, rel=1e-3)
    # 剪刀差统一为小数口径：47.6% - 30.0% = 17.6pct = 0.176
    assert row0["scissors_spread_yoy"] == pytest.approx(0.176, rel=1e-3)


def test_empty_fallbacks() -> None:
    assert empty_silicon_wafer_monthly().is_empty()
    assert empty_polysilicon_supply().is_empty()
    assert empty_polysilicon_inventory().is_empty()
    assert empty_pv_wafer().is_empty()
    assert empty_polysilicon_balance().is_empty()
    assert empty_solar_supply_demand().is_empty()
    assert records_to_silicon_wafer_monthly_frame([]).is_empty()
    assert records_to_polysilicon_supply_frame([]).is_empty()
    assert records_to_polysilicon_inventory_frame([]).is_empty()
    assert records_to_pv_wafer_frame([]).is_empty()
    assert build_polysilicon_balance_frame(pl.DataFrame(), pl.DataFrame()).is_empty()
    assert build_solar_supply_demand_frame(pl.DataFrame(), pl.DataFrame()).is_empty()


def test_nbs_placeholder_row_marked_missing_unverified(tmp_path) -> None:
    nbs_file = tmp_path / "power" / "nbs" / "nbs_solar_cell_monthly.csv"
    nbs_file.parent.mkdir(parents=True)
    nbs_file.write_text(
        "report_month,trade_date,output_current,output_cumulative,output_yoy,output_cum_yoy\n"
        "2026-07,2026-07-31,6520.0,43889.5,-1.8,-12.1\n"
        "2026-08,2026-08-31,,,,\n",
        encoding="utf-8",
    )
    collector = NbsSolarCellCollector(raw_dir=tmp_path)
    records = collector.load_from_raw_csv(nbs_file)
    by_month = {record.report_month: record for record in records}
    assert by_month["2026-07"].data_status == "actual"
    assert by_month["2026-07"].output_current == 6520.0
    assert by_month["2026-08"].data_status == "missing_unverified"
    assert by_month["2026-08"].output_current is None


def test_polysilicon_inventory_weeks_derived(tmp_path) -> None:
    _write_silicon_fixture(tmp_path)
    collector = SiliconBranchCollector(raw_dir=tmp_path, crawler=_EmptySiliconCrawler())
    silicon_df = records_to_silicon_wafer_monthly_frame(collector.collect())

    # 派生路径：从硅业分会主表拆分构建库存专表
    inv_df = build_polysilicon_inventory_from_silicon_frame(silicon_df)
    assert inv_df.schema == POLYSILICON_INVENTORY_MONTHLY_SCHEMA
    assert inv_df["inventory_weeks"].null_count() == 0
    assert inv_df["inventory_status"].null_count() == 0

    row_2025_01 = inv_df.filter(pl.col("report_month") == "2025-01").to_dicts()[0]
    # 2025 耗硅系数 0.205：隐含需求 = 44.71*0.205 = 9.1656；周数 = 38.2/(9.1656/4.33)
    expected_weeks = pytest.approx(38.2 / (9.1656 / 4.33), rel=1e-2)
    assert row_2025_01["inventory_weeks"] == expected_weeks
    assert row_2025_01["inventory_status"] == "severe_oversupply"

    # 记录直转路径：传入 wafer 表后口径与派生路径一致
    wafer_df = build_pv_wafer_from_silicon_frame(silicon_df)
    records = collector.collect_inventory()
    inv_records_df = records_to_polysilicon_inventory_frame(records, wafer_df=wafer_df)
    row_rec = inv_records_df.filter(pl.col("report_month") == "2025-01").to_dicts()[0]
    assert row_rec["inventory_weeks"] == row_2025_01["inventory_weeks"]
    assert row_rec["inventory_status"] == row_2025_01["inventory_status"]

    # 与平衡表同口径对账：balance 按同一公式计算的库存周数
    supply_df = records_to_polysilicon_supply_frame(collector.collect_supply())
    balance_df = build_polysilicon_balance_frame(supply_df, wafer_df, inv_df)
    balance_weeks = balance_df.filter(pl.col("report_month") == "2025-01")["inventory_weeks"][0]
    assert row_2025_01["inventory_weeks"] == balance_weeks


def test_utilization_rate_dimension_contract(tmp_path) -> None:
    """口径收敛契约：派生产能利用率是唯一标准特征，名义开工率为参考辅助列。

    - `derived_utilization_rate`：物理第一性原理（产量×12/年化产能）派生，全历史完整；
    - `operating_rate`：检修装置调查口径，历史缺失多（84/104），仅原样保留为参考列，
      禁止作为供需模型输入（2026-09 阶段 1 口径收敛）。
    """
    _write_silicon_fixture(tmp_path)
    collector = SiliconBranchCollector(raw_dir=tmp_path, crawler=_EmptySiliconCrawler())
    silicon_df = records_to_silicon_wafer_monthly_frame(collector.collect())
    supply_df = build_polysilicon_supply_from_silicon_frame(silicon_df)

    # 派生利用率全历史非空（非占位月份），且由物理公式可重算
    assert supply_df["derived_utilization_rate"].null_count() == 0
    row_2025_01 = supply_df.filter(pl.col("report_month") == "2025-01").to_dicts()[0]
    assert row_2025_01["derived_utilization_rate"] == pytest.approx(
        9.44 * 12.0 / 347.9 * 100.0, abs=0.05
    )

    # 名义开工率仅原样保留参考值，不被派生值覆盖
    assert row_2025_01["operating_rate"] == 38.11

    # 两口径相关性方向一致但数值不同（系统偏移），分析层不得混用
    assert row_2025_01["operating_rate"] > row_2025_01["derived_utilization_rate"]
