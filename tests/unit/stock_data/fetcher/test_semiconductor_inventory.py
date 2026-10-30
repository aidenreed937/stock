"""测试全球半导体 IDM 龙头存货周转天数 (DOI) 2-Tier ETL 与物化。"""

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from stock_data.fetcher.industry.semiconductor.collectors.inventory import (
    SemiconductorInventoryCollector,
)
from stock_data.fetcher.industry.semiconductor.models import SemiconductorInventoryRecord
from stock_data.fetcher.industry.semiconductor.parsers.inventory import (
    SecFiling,
    build_inventory_release_date_map,
    extract_sec_filings,
    load_inventory_raw_csv,
)
from stock_data.fetcher.industry.semiconductor.parsers.inventory_online import (
    parse_companyfacts_inventory,
    parse_sec_6k_inventory,
)
from stock_data.fetcher.industry.semiconductor.transforms import (
    build_inventory_days_frame,
    determine_inventory_regime,
    records_to_raw_inventory_frame,
)
from stock_data.fetcher.industry.task_executor import execute_single_industry_task


def test_determine_inventory_regime() -> None:
    assert determine_inventory_regime(160.0) == "high_overstocked"
    assert determine_inventory_regime(140.0) == "elevated_destocking"
    assert determine_inventory_regime(115.0) == "normal_balanced"
    assert determine_inventory_regime(95.0) == "tight_restocking"


def test_inventory_csv_parser_builds_record_model(tmp_path: Path) -> None:
    csv_path = tmp_path / "inventory.csv"
    csv_path.write_text(
        "symbol,report_quarter,trade_date,inventory_usd,cost_of_revenue_usd,release_date\n"
        'txn,2026q1,2026-03-31,"3,910.0","1,840.0",2026-04-24\n',
        encoding="utf-8",
    )

    records = load_inventory_raw_csv(csv_path)

    assert len(records) == 1
    record = records[0]
    assert isinstance(record, SemiconductorInventoryRecord)
    assert record.symbol == "TXN"
    assert record.report_quarter == "2026Q1"
    assert record.inventory_usd_million == 3910.0
    assert record.cost_of_revenue_usd_million == 1840.0
    assert records_to_raw_inventory_frame(records)["inventory_usd_raw"].to_list() == ["3,910.0"]


def test_inventory_csv_parser_rejects_non_finite_value(tmp_path: Path) -> None:
    csv_path = tmp_path / "inventory.csv"
    csv_path.write_text(
        "symbol,report_quarter,trade_date,inventory_usd,cost_of_revenue_usd,release_date\n"
        "TXN,2026Q1,2026-03-31,nan,1840.0,2026-04-24\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="不是有限数值"):
        load_inventory_raw_csv(csv_path)


def test_extract_sec_filings_and_match_release_dates() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["10-Q", "8-K", "6-K"],
                "filingDate": ["2026-04-24", "2026-04-23", "2026-04-15"],
                "reportDate": ["2026-03-31", "2026-04-23", "2026-03-29"],
                "primaryDocument": ["txn.htm", "txn-8k.htm", "form6-kquarterlyfilings.htm"],
            }
        }
    }
    filings = extract_sec_filings(payload)
    assert filings == [
        SecFiling(
            form="10-Q",
            filing_date=date(2026, 4, 24),
            report_date=date(2026, 3, 31),
            primary_document="txn.htm",
        ),
        SecFiling(
            form="6-K",
            filing_date=date(2026, 4, 15),
            report_date=date(2026, 3, 29),
            primary_document="form6-kquarterlyfilings.htm",
        ),
    ]

    release_dates = build_inventory_release_date_map(
        [
            {"symbol": "TXN", "report_quarter": "2026Q1", "trade_date": date(2026, 3, 31)},
            {"symbol": "STM", "report_quarter": "2026Q1", "trade_date": date(2026, 3, 31)},
        ],
        {"TXN": filings[:1], "STM": filings[1:]},
    )
    assert release_dates == {
        ("TXN", "2026Q1"): date(2026, 4, 24),
        ("STM", "2026Q1"): date(2026, 4, 15),
    }


def test_inventory_without_release_date_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir = tmp_path / "raw"
    inv_dir = raw_dir / "semiconductors" / "inventory"
    inv_dir.mkdir(parents=True)
    (inv_dir / "idm_quarterly_financials_10y.csv").write_text(
        "symbol,report_quarter,trade_date,inventory_usd,cost_of_revenue_usd\n"
        "TXN,2026Q1,2026-03-31,3910.0,1840.0\n",
        encoding="utf-8",
    )

    collector = SemiconductorInventoryCollector(raw_dir)
    monkeypatch.setattr(collector, "_load_sec_filings", lambda *args, **kwargs: {})
    with pytest.raises(ValueError, match="缺少真实 release_date"):
        collector.collect_raw()


def test_inventory_rejects_sec_cache_for_wrong_company(tmp_path: Path) -> None:
    collector = SemiconductorInventoryCollector(tmp_path / "raw")
    collector.paths.inventory_sec_dir.mkdir(parents=True)
    (collector.paths.inventory_sec_dir / "STM.json").write_text(
        '{"cik":"0000937966","name":"ASML HOLDING NV","tickers":["ASML"]}',
        encoding="utf-8",
    )

    assert collector._load_sec_filings(["STM"], force=False, allow_network=False)["STM"] == []


def test_inventory_companyfacts_parser_derives_q4_from_annual_cogs() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "InventoryNet": {
                    "units": {
                        "USD": [
                            {
                                "end": "2016-03-31",
                                "val": 1805000000,
                                "form": "10-Q",
                                "filed": "2016-05-04",
                            },
                            {
                                "end": "2016-06-30",
                                "val": 1876000000,
                                "form": "10-Q",
                                "filed": "2016-08-04",
                            },
                            {
                                "end": "2016-09-30",
                                "val": 1808000000,
                                "form": "10-Q",
                                "filed": "2016-11-03",
                            },
                            {
                                "end": "2016-12-31",
                                "val": 1790000000,
                                "form": "10-K",
                                "filed": "2017-02-23",
                            },
                        ]
                    }
                },
                "CostOfRevenue": {
                    "units": {
                        "USD": [
                            {
                                "start": "2016-01-01",
                                "end": "2016-03-31",
                                "val": 1184000000,
                                "form": "10-Q",
                                "filed": "2016-05-04",
                            },
                            {
                                "start": "2016-04-01",
                                "end": "2016-06-30",
                                "val": 1270000000,
                                "form": "10-Q",
                                "filed": "2016-08-04",
                            },
                            {
                                "start": "2016-07-01",
                                "end": "2016-09-30",
                                "val": 1395000000,
                                "form": "10-Q",
                                "filed": "2016-11-03",
                            },
                            {
                                "start": "2016-01-01",
                                "end": "2016-12-31",
                                "val": 5130000000,
                                "form": "10-K",
                                "filed": "2017-02-23",
                            },
                        ]
                    }
                },
            }
        }
    }

    records = parse_companyfacts_inventory(
        payload,
        symbol="TXN",
        start_date=date(2016, 1, 1),
        end_date=date(2016, 12, 31),
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000097476.json",
        raw_content_hash="hash",
        raw_snapshot_path="inventory/sec_companyfacts/txn.json.gz",
        collected_at="now",
    )

    assert len(records) == 4
    assert records[-1].report_quarter == "2016Q4"
    assert records[-1].cost_of_revenue_usd_million == 1281.0
    assert records[-1].data_status == "derived_q4"
    assert records[-1].cost_of_revenue_derivation == "annual_minus_q1_q2_q3"


def test_inventory_6k_parser_handles_operations_and_net_inventory() -> None:
    html = """
    <h1>Condensed consolidated statements of operations</h1>
    <p>For the three months ended June 28, 2026</p>
    <p>Revenue 3,496 Cost of revenue (1,494) Gross profit 2,002</p>
    <h2>Condensed consolidated balance sheets</h2>
    <p>As of June 28, 2026</p>
    <p>Cash 3,222 Inventories, net 2,557 Other current assets 539</p>
    """

    record = parse_sec_6k_inventory(
        html,
        symbol="NXPI",
        report_quarter="2026Q2",
        release_date=date(2026, 7, 28),
        source_url="https://www.sec.gov/Archives/edgar/data/example.htm",
        raw_content_hash="hash",
        raw_snapshot_path="inventory/sec_6k/nxpi.htm.gz",
        collected_at="now",
    )

    assert record is not None
    assert record.inventory_usd_million == 2557.0
    assert record.cost_of_revenue_usd_million == 1494.0
    assert record.source_period_end == date(2026, 6, 28)


def test_semiconductor_inventory_collector(tmp_path: Path) -> None:
    # 构造临时 RAW CSV
    raw_dir = tmp_path / "raw_industry"
    inv_dir = raw_dir / "semiconductors" / "inventory"
    inv_dir.mkdir(parents=True, exist_ok=True)

    csv_content = """symbol,report_quarter,trade_date,inventory_usd,cost_of_revenue_usd,release_date
TXN,2026Q1,2026-03-31,3910.0,1840.0,2026-04-24
ADI,2026Q1,2026-03-31,1767.1,1115.3,2026-02-18
STM,2026Q1,2026-03-31,3173.0,2050.0,2026-04-15
NXPI,2026Q1,2026-03-31,2450.0,1430.0,2026-04-28
"""
    (inv_dir / "idm_quarterly_financials_10y.csv").write_text(csv_content, encoding="utf-8")

    collector = SemiconductorInventoryCollector(raw_dir=raw_dir)
    df = build_inventory_days_frame(collector.collect_raw())

    assert not df.is_empty()
    assert len(df) == 4
    assert "doi_days" in df.columns
    assert "idm_weighted_doi_days" in df.columns
    assert "inventory_regime" in df.columns

    # 验证 TXN 的 DOI 计算: 3910.0 / 1840.0 * 90 = 191.25 -> 191.2
    txn_row = df.filter(pl.col("symbol") == "TXN")
    assert txn_row["doi_days"][0] == 191.2

    # 验证综合加权 DOI: sum(inv)=11300.1, sum(cogs)=6435.3 -> 11300.1 / 6435.3 * 90 = 158.0
    assert df["idm_weighted_doi_days"][0] == 158.0
    assert df["inventory_regime"][0] == "high_overstocked"


def test_semiconductor_inventory_endpoint_honors_report_date_window(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_industry"
    inv_dir = raw_dir / "semiconductors" / "inventory"
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "idm_quarterly_financials_10y.csv").write_text(
        "symbol,report_quarter,trade_date,inventory_usd,cost_of_revenue_usd,release_date\n"
        "TXN,2025Q1,2025-03-31,3000.0,1500.0,2025-04-24\n"
        "TXN,2025Q2,2025-06-30,3100.0,1550.0,2025-07-24\n",
        encoding="utf-8",
    )

    count = execute_single_industry_task(
        endpoint="semiconductor_inventory_days",
        start_date=date(2025, 4, 1),
        end_date=date(2025, 6, 30),
        raw_dir=raw_dir,
        curated_dir=tmp_path / "curated",
    )

    assert count == 1
    raw_saved = pl.read_parquet(
        raw_dir / "semiconductor" / "inventory" / "semiconductor_inventory_days.parquet"
    )
    assert raw_saved["report_quarter"].to_list() == ["2025Q2"]


def test_semiconductor_inventory_real_curated_file() -> None:
    curated_path = Path(
        "data/curated/industry/semiconductor/inventory/semiconductor_inventory_days.parquet"
    )
    assert curated_path.exists(), "必须存在物化好的 semiconductor_inventory_days.parquet"

    df = pl.read_parquet(curated_path)
    assert len(df) >= 160
    assert "2016Q1" in df["report_quarter"].to_list()
    assert "2026Q2" in df["report_quarter"].to_list()

    # DART 回溯替换三星 DS 库存后，2021Q4 全量 IDM DOI 落入低库存补库区间
    q_2021q4 = df.filter(pl.col("report_quarter") == "2021Q4")
    assert q_2021q4["analog_weighted_doi_days"][0] < 105.0
    assert q_2021q4["idm_weighted_doi_days"][0] < 115.0
    assert q_2021q4["inventory_regime"][0] == "tight_restocking"


def test_inventory_companyfacts_parser_handles_micron_and_derives_q3_from_annual() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "InventoryNet": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-11-30",
                                "val": 8300000000,
                                "form": "10-Q",
                                "filed": "2023-12-21",
                            },
                            {
                                "end": "2024-02-29",
                                "val": 8400000000,
                                "form": "10-Q",
                                "filed": "2024-03-21",
                            },
                            {
                                "end": "2024-05-30",
                                "val": 8500000000,
                                "form": "10-Q",
                                "filed": "2024-06-26",
                            },
                            {
                                "end": "2024-08-29",
                                "val": 8600000000,
                                "form": "10-K",
                                "filed": "2024-10-04",
                            },
                        ]
                    }
                },
                "CostOfGoodsAndServicesSold": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-09-01",
                                "end": "2023-11-30",
                                "val": 4000000000,
                                "form": "10-Q",
                                "filed": "2023-12-21",
                            },
                            {
                                "start": "2023-12-01",
                                "end": "2024-02-29",
                                "val": 4500000000,
                                "form": "10-Q",
                                "filed": "2024-03-21",
                            },
                            {
                                "start": "2024-03-01",
                                "end": "2024-05-30",
                                "val": 5000000000,
                                "form": "10-Q",
                                "filed": "2024-06-26",
                            },
                            {
                                "start": "2023-09-01",
                                "end": "2024-08-29",
                                "val": 19500000000,
                                "form": "10-K",
                                "filed": "2024-10-04",
                            },
                        ]
                    }
                },
            }
        }
    }

    records = parse_companyfacts_inventory(
        payload,
        symbol="MU",
        start_date=date(2023, 10, 1),
        end_date=date(2024, 9, 30),
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000723125.json",
        raw_content_hash="hash_mu",
        raw_snapshot_path="inventory/sec_companyfacts/mu.json.gz",
        collected_at="now",
    )

    assert len(records) == 4
    for record in records:
        assert record.symbol == "MU"
        assert record.subsector == "memory"

    mu_q3 = next(r for r in records if r.report_quarter == "2024Q3")
    assert mu_q3.cost_of_revenue_usd_million == 6000.0  # 19500 - (4000 + 4500 + 5000)
    assert mu_q3.inventory_usd_million == 8600.0
    assert mu_q3.data_status == "derived_q3"
    assert mu_q3.cost_of_revenue_derivation == "annual_minus_previous_3q"


def test_inventory_days_frame_calculates_dual_track_doi() -> None:
    records = [
        SemiconductorInventoryRecord(
            symbol="TXN",
            report_quarter="2024Q2",
            trade_date=date(2024, 6, 30),
            inventory_usd_million=4000.0,
            cost_of_revenue_usd_million=2000.0,
            subsector="analog_auto",
            release_date=date(2024, 7, 25),
        ),
        SemiconductorInventoryRecord(
            symbol="ADI",
            report_quarter="2024Q2",
            trade_date=date(2024, 6, 30),
            inventory_usd_million=2000.0,
            cost_of_revenue_usd_million=1500.0,
            subsector="analog_auto",
            release_date=date(2024, 7, 25),
        ),
        SemiconductorInventoryRecord(
            symbol="MU",
            report_quarter="2024Q2",
            trade_date=date(2024, 6, 30),
            inventory_usd_million=8500.0,
            cost_of_revenue_usd_million=5000.0,
            subsector="memory",
            release_date=date(2024, 6, 26),
        ),
        SemiconductorInventoryRecord(
            symbol="NXPI",
            report_quarter="2024Q2",
            trade_date=date(2024, 6, 30),
            inventory_usd_million=3000.0,
            cost_of_revenue_usd_million=1500.0,
            subsector="analog_auto",
            release_date=date(2024, 7, 25),
        ),
    ]

    df = build_inventory_days_frame(records)
    assert not df.is_empty()
    assert len(df) == 4

    # 全量加权 DOI: (4000+2000+8500+3000) / (2000+1500+5000+1500) * 90 = 17500/10000*90 = 157.5
    assert df["idm_weighted_doi_days"][0] == 157.5
    # 模拟/汽车加权 DOI: (4000+2000+3000) / (2000+1500+1500) * 90 = 9000/5000*90 = 162.0
    assert df["analog_weighted_doi_days"][0] == 162.0
    # 存储加权 DOI: 8500 / 5000 * 90 = 153.0
    assert df["memory_weighted_doi_days"][0] == 153.0
    assert df["inventory_regime"][0] == "high_overstocked"

    txn_row = df.filter(pl.col("symbol") == "TXN")
    assert txn_row["subsector"][0] == "analog_auto"
    assert txn_row["doi_days"][0] == 180.0

    mu_row = df.filter(pl.col("symbol") == "MU")
    assert mu_row["subsector"][0] == "memory"
    assert mu_row["doi_days"][0] == 153.0


def test_inventory_under_covered_quarter_leaves_aggregates_empty() -> None:
    """季度主体数低于 MIN_INVENTORY_CONSTITUENTS 时，季度级聚合与相态一律留空。

    防的是"单家公司冒充行业口径"：2026Q3 曾因仅 ADI 一家而输出一个
    "7 家 IDM 加权"的 132.3 天。个股级字段不受影响。
    """
    records = [
        SemiconductorInventoryRecord(
            symbol="TXN",
            report_quarter="2024Q2",
            trade_date=date(2024, 6, 30),
            inventory_usd_million=4000.0,
            cost_of_revenue_usd_million=2000.0,
            release_date=date(2024, 7, 25),
        ),
        SemiconductorInventoryRecord(
            symbol="MU",
            report_quarter="2024Q2",
            trade_date=date(2024, 6, 30),
            inventory_usd_million=8500.0,
            cost_of_revenue_usd_million=5000.0,
            release_date=date(2024, 6, 26),
        ),
    ]

    df = build_inventory_days_frame(records)
    assert len(df) == 2

    for column in (
        "idm_equal_doi_days",
        "idm_weighted_doi_days",
        "analog_weighted_doi_days",
        "memory_weighted_doi_days",
        "inventory_regime",
    ):
        assert df[column].null_count() == df.height, f"{column} 应留空"

    # 个股级 DOI 与合计不受守卫影响
    txn_row = df.filter(pl.col("symbol") == "TXN")
    assert txn_row["doi_days"][0] == 180.0
    assert txn_row["total_inventory_usd_million"][0] == 12500.0


def test_krw_dual_track_fx_conversion() -> None:
    from stock_data.fetcher.industry.semiconductor.fx import (
        convert_krw_to_usd_million,
        get_krw_usd_rates,
    )

    spot, avg = get_krw_usd_rates("2024Q1")
    # 真实 FRED DEXKOUS 日频时序计算结果 (期末即期 1347.08, 62交易日均值 1329.6132)
    assert spot == 1347.08
    assert avg == 1329.6132

    # 存货 29.54 兆韩元，成本 15.20 兆韩元
    inv_usd, cogs_usd = convert_krw_to_usd_million(29.54, 15.20, "2024Q1", unit="trillion_krw")
    # inv = 29.54 * 1,000,000 / 1347.08 = 21928.91
    # cogs = 15.20 * 1,000,000 / 1329.6132 = 11431.90
    assert inv_usd == 21928.91
    assert cogs_usd == 11431.90

    # 严禁静态字典回退：未回填或不存在的时期必须抛出 ValueError，杜绝静默伪造
    with pytest.raises(ValueError, match="缺失"):
        get_krw_usd_rates("1970Q1")


def test_samsung_ds_segment_ratio_validation() -> None:
    from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
        samsung_ds_ratio_minimum,
        validate_samsung_ds_ratio,
    )

    # 正常占比 55%
    assert validate_samsung_ds_ratio(29.54, 53.40) is True

    # 异常过低 (<35%)
    with pytest.raises(ValueError, match="不在安全区间"):
        validate_samsung_ds_ratio(10.0, 50.0)

    # 异常过高 (>70%，如误取了集团合并值)
    with pytest.raises(ValueError, match="不在安全区间"):
        validate_samsung_ds_ratio(50.0, 50.0)

    # 非法负值
    with pytest.raises(ValueError, match="必须为正数"):
        validate_samsung_ds_ratio(-5.0, 50.0)

    assert samsung_ds_ratio_minimum("2016Q1") == 0.20
    assert samsung_ds_ratio_minimum("2021Q1") == 0.35
    assert validate_samsung_ds_ratio(5_346_323, 21_857_598, minimum_ratio=0.20)


def test_korea_memory_raw_csv_loader(tmp_path: Path) -> None:
    from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
        load_korea_memory_raw_csv,
    )

    csv_path = tmp_path / "korea_memory_sample.csv"
    csv_path.write_text(
        "symbol,report_quarter,trade_date,inventory_krw,cost_of_revenue_krw,group_total_inventory_krw,unit,release_date,source,source_url,fiscal_period_raw,collected_at\n"
        "000660.KS,2024Q1,2024-03-31,13.84,7.20,,trillion_krw,2024-04-25,SK_HYNIX_DART_PERIODIC_REPORT,https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240515000001,1Q24,2026-09-09T00:00:00Z\n"
        "005930.KS_DS,2024Q1,2024-03-31,29.54,15.20,53.40,trillion_krw,2024-04-30,SAMSUNG_DART_INTERIM_BUSINESS_REPORT_C_INVENTORY_BY_DIVISION,https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240515000001,1Q24,2026-09-09T00:00:00Z\n",
        encoding="utf-8",
    )

    records = load_korea_memory_raw_csv(csv_path)

    assert len(records) == 2
    symbols = {r.symbol for r in records}
    assert symbols == {"000660.KS", "005930.KS_DS"}

    hynix_24q1 = next(
        r for r in records if r.symbol == "000660.KS" and r.report_quarter == "2024Q1"
    )
    assert hynix_24q1.inventory_usd_million == 10274.07
    assert hynix_24q1.cost_of_revenue_usd_million == 5415.11
    assert hynix_24q1.release_date == date(2024, 4, 25)
    assert hynix_24q1.subsector == "memory"

    samsung_24q1 = next(
        r for r in records if r.symbol == "005930.KS_DS" and r.report_quarter == "2024Q1"
    )
    assert samsung_24q1.inventory_usd_million == 21928.91
    assert samsung_24q1.cost_of_revenue_usd_million == 11431.90
    assert samsung_24q1.release_date == date(2024, 4, 30)
    assert samsung_24q1.subsector == "memory"
    assert samsung_24q1.memory_inventory_status == "not_disclosed"


def test_samsung_ds_recent_backfill_keeps_cost_proxy_lineage() -> None:
    from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
        load_korea_memory_raw_csv,
    )

    rows = load_korea_memory_raw_csv(Path("data/raw/industry/semiconductor/korea_memory_raw.csv"))
    recent = [
        row
        for row in rows
        if row.symbol == "005930.KS_DS"
        and row.report_quarter in {"2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"}
    ]

    assert len(recent) == 6
    assert {row.cost_of_revenue_source for row in recent} == {
        "proxy_ds_revenue_minus_ds_operating_profit"
    }
    assert {row.memory_inventory_status for row in recent} == {"not_disclosed"}
    q2 = next(row for row in recent if row.report_quarter == "2026Q2")
    assert q2.ds_revenue_krw_raw is not None
    assert q2.ds_operating_profit_krw_raw is not None
    assert Decimal(q2.ds_revenue_krw_raw) == Decimal("127.5161")
    assert Decimal(q2.ds_operating_profit_krw_raw) == Decimal("89.1960")
    assert "ds_inventory_source=business_report_c_inventory_by_division" in (
        q2.cost_of_revenue_derivation
    )


def test_samsung_ds_historical_dart_inventory_backfill() -> None:
    from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
        load_korea_memory_raw_csv,
    )

    rows = load_korea_memory_raw_csv(Path("data/raw/industry/semiconductor/korea_memory_raw.csv"))
    historical = [
        row
        for row in rows
        if row.symbol == "005930.KS_DS" and "2018Q1" <= row.report_quarter <= "2024Q4"
    ]

    assert len(historical) == 28
    assert {row.source for row in historical} == {
        "SAMSUNG_DART_BUSINESS_REPORT_C_INVENTORY_BY_DIVISION",
        "SAMSUNG_DART_INTERIM_BUSINESS_REPORT_C_INVENTORY_BY_DIVISION",
    }
    q1_2018 = next(row for row in historical if row.report_quarter == "2018Q1")
    assert q1_2018.inventory_usd_raw == "8.315990"
    assert q1_2018.cost_of_revenue_source == "proxy_ds_revenue_minus_ds_operating_profit"
    q4_2018 = next(row for row in historical if row.report_quarter == "2018Q4")
    q4_2024 = next(row for row in historical if row.report_quarter == "2024Q4")
    assert q4_2018.inventory_usd_raw == "12.762964"
    assert q4_2018.release_date == date(2019, 4, 1)
    assert q4_2018.inventory_scope == "legacy_semiconductor_business"
    assert q4_2018.memory_inventory_status == "not_disclosed"
    q4_2021 = next(row for row in historical if row.report_quarter == "2021Q4")
    assert q4_2021.inventory_usd_raw == "16.274418"
    assert q4_2024.inventory_usd_raw == "29.688574"
    assert q4_2024.inventory_scope == "ds_division"
    assert q4_2024.memory_inventory_status == "not_disclosed"
    with Path("data/raw/industry/semiconductor/korea_memory_raw.csv").open(
        encoding="utf-8"
    ) as raw_file:
        raw_rows = list(csv.DictReader(raw_file))
    q4_2024_raw = next(
        row
        for row in raw_rows
        if row["symbol"] == "005930.KS_DS" and row["report_quarter"] == "2024Q4"
    )
    assert q4_2024_raw["group_total_inventory_krw"] == "51.754865"
    assert q4_2024_raw["memory_inventory_status"] == "not_disclosed"


def test_korea_memory_sources_are_complete_from_2016q1() -> None:
    from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
        load_korea_memory_raw_csv,
    )

    rows = load_korea_memory_raw_csv(Path("data/raw/industry/semiconductor/korea_memory_raw.csv"))
    expected = {f"{year}Q{quarter}" for year in range(2016, 2027) for quarter in range(1, 5)}
    expected = {quarter for quarter in expected if quarter <= "2026Q2"}

    for symbol in ("005930.KS_DS", "000660.KS"):
        quarters = {row.report_quarter for row in rows if row.symbol == symbol}
        assert quarters == expected
        assert len(quarters) == 42


def test_skhynix_dart_gap_backfill() -> None:
    from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
        load_korea_memory_raw_csv,
    )

    rows = load_korea_memory_raw_csv(Path("data/raw/industry/semiconductor/korea_memory_raw.csv"))
    gap_rows = [
        row
        for row in rows
        if row.symbol == "000660.KS" and row.report_quarter in {"2025Q1", "2025Q3"}
    ]

    assert len(gap_rows) == 2
    q1 = next(row for row in gap_rows if row.report_quarter == "2025Q1")
    q3 = next(row for row in gap_rows if row.report_quarter == "2025Q3")
    assert q1.inventory_usd_raw == "14551.350"
    assert q1.cost_of_revenue_usd_raw == "7537.150"
    assert q1.release_date == date(2025, 5, 15)
    assert q1.cost_of_revenue_source == "official_consolidated_cost_of_revenue"
    assert q3.inventory_usd_raw == "13156.389"
    assert q3.cost_of_revenue_usd_raw == "10419.829"
    assert q3.release_date == date(2025, 11, 14)
    assert q3.cost_of_revenue_source == "official_consolidated_cost_of_revenue"


def test_all_skhynix_rows_use_dart_periodic_reports() -> None:
    from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
        load_korea_memory_raw_csv,
    )

    rows = load_korea_memory_raw_csv(Path("data/raw/industry/semiconductor/korea_memory_raw.csv"))
    sk_rows = [row for row in rows if row.symbol == "000660.KS"]

    assert len(sk_rows) == 42
    assert {row.source for row in sk_rows} == {"SK_HYNIX_DART_PERIODIC_REPORT"}
    assert all(
        row.source_url.startswith("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=")
        for row in sk_rows
    )
    assert all(
        row.raw_snapshot_path.startswith("semiconductor/korea_filings/sk_hynix_dart_")
        for row in sk_rows
    )

    q4_2025 = next(row for row in sk_rows if row.report_quarter == "2025Q4")
    assert q4_2025.inventory_usd_raw == "14289.390"
    assert q4_2025.cost_of_revenue_usd_raw == "10250.278"
    assert q4_2025.cost_of_revenue_annual_raw == "38455.885"
    assert q4_2025.cost_of_revenue_source == ("official_consolidated_cost_of_revenue_derived_q4")
    assert "prior_9m_rcp_no=20251114001805" in q4_2025.cost_of_revenue_derivation


def test_skhynix_current_five_year_window_is_complete() -> None:
    from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
        load_korea_memory_raw_csv,
    )

    rows = load_korea_memory_raw_csv(Path("data/raw/industry/semiconductor/korea_memory_raw.csv"))
    quarters = {
        row.report_quarter
        for row in rows
        if row.symbol == "000660.KS" and "2021Q3" <= row.report_quarter <= "2026Q2"
    }
    expected = {
        f"{year}Q{quarter}"
        for year, quarter in (
            (2021, 3),
            (2021, 4),
            (2022, 1),
            (2022, 2),
            (2022, 3),
            (2022, 4),
            (2023, 1),
            (2023, 2),
            (2023, 3),
            (2023, 4),
            (2024, 1),
            (2024, 2),
            (2024, 3),
            (2024, 4),
            (2025, 1),
            (2025, 2),
            (2025, 3),
            (2025, 4),
            (2026, 1),
            (2026, 2),
        )
    }
    assert quarters == expected

    q3_2022 = next(
        row for row in rows if row.symbol == "000660.KS" and row.report_quarter == "2022Q3"
    )
    assert q3_2022.inventory_usd_raw == "14664.974"
    assert q3_2022.cost_of_revenue_usd_raw == "7110.221"
    assert q3_2022.release_date == date(2022, 11, 14)


def test_skhynix_non_dart_source_is_rejected(tmp_path: Path) -> None:
    from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
        load_korea_memory_raw_csv,
    )

    csv_path = tmp_path / "sk_hynix_non_dart.csv"
    csv_path.write_text(
        "symbol,report_quarter,trade_date,inventory_krw,cost_of_revenue_krw,unit,release_date,source,source_url\n"
        "000660.KS,2025Q1,2025-03-31,14551.350,7537.150,billion_krw,2025-05-15,SEC_6K,https://www.sec.gov/example\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="必须统一来自 DART"):
        load_korea_memory_raw_csv(csv_path)


def test_samsung_non_dart_source_is_rejected(tmp_path: Path) -> None:
    from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
        load_korea_memory_raw_csv,
    )

    csv_path = tmp_path / "samsung_non_dart.csv"
    csv_path.write_text(
        "symbol,report_quarter,trade_date,inventory_krw,cost_of_revenue_krw,"
        "group_total_inventory_krw,unit,release_date,source,source_url\n"
        "005930.KS_DS,2025Q1,2025-03-31,30.0,20.0,50.0,trillion_krw,"
        "2025-05-15,SAMSUNG_IR_ENGLISH_FACTSHEET,"
        "https://www.samsung.com/global/ir/financial-information/quarterly-results/\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="三星 DS RAW 必须统一来自 DART"):
        load_korea_memory_raw_csv(csv_path)


def test_seven_idm_giants_dual_track_doi() -> None:
    records = [
        SemiconductorInventoryRecord(
            symbol="TXN",
            report_quarter="2024Q1",
            trade_date=date(2024, 3, 31),
            inventory_usd_million=4083.0,
            cost_of_revenue_usd_million=1566.0,
            subsector="analog_auto",
            release_date=date(2024, 4, 24),
        ),
        SemiconductorInventoryRecord(
            symbol="MU",
            report_quarter="2024Q1",
            trade_date=date(2024, 3, 31),
            inventory_usd_million=8443.0,
            cost_of_revenue_usd_million=4745.0,
            subsector="memory",
            release_date=date(2024, 3, 20),
        ),
        SemiconductorInventoryRecord(
            symbol="000660.KS",
            report_quarter="2024Q1",
            trade_date=date(2024, 3, 31),
            inventory_usd_million=10274.07,
            cost_of_revenue_usd_million=5415.11,
            subsector="memory",
            release_date=date(2024, 4, 25),
        ),
        SemiconductorInventoryRecord(
            symbol="005930.KS_DS",
            report_quarter="2024Q1",
            trade_date=date(2024, 3, 31),
            inventory_usd_million=21928.91,
            cost_of_revenue_usd_million=11431.90,
            subsector="memory",
            release_date=date(2024, 4, 30),
        ),
    ]

    df = build_inventory_days_frame(records)
    assert len(df) == 4

    # 存储加权 DOI: (8443 + 10274.07 + 21928.91) / (4745 + 5415.11 + 11431.90) * 90 = 40645.98 / 21592.01 * 90 = 169.4
    assert df["memory_weighted_doi_days"][0] == 169.4

    # 全量加权 DOI: (4083 + 40645.98) / (1566 + 21592.01) * 90 = 44728.98 / 23158.01 * 90 = 173.8
    assert df["idm_weighted_doi_days"][0] == 173.8
