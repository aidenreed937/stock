"""郑商所/大商所官方日行情解析、主力筛选与 RAW 合并单元测试。

解析逻辑已从 scripts/backfill_chemical_futures_daily.py 收编到
stock_data.fetcher.industry.chemicals.collectors.official，测试随之下沉。
"""

from datetime import date

import stock_data.fetcher.industry.chemicals.collectors.official as official_mod
from stock_data.fetcher.industry.chemicals.collectors.official import (
    DCE_DAILY_PAGE_URL,
    _fmt_value,
    build_daily_record,
    download_dce_daily_text,
    merge_daily_rows,
    parse_czce_daily_text,
    parse_dce_daily_text,
    pick_main_contract,
    read_daily_csv,
)

CZCE_DAILY_FIXTURE = """
\t\t\t\t\t郑州商品交易所期货每日行情表(2026-09-15)
合约代码|昨结算    |今开盘    |最高价    |最低价    |今收盘    |今结算    |涨跌1    |涨跌2    |成交量(手)|持仓量    |增减量    |成交额(万元)|交割结算价
SA610 |1,065.00  |1,067.00  |1,067.00  |1,016.00  |1,019.00  |1,037.00  |18.00    |32.00    |1,895,369 |1,291,224 |-7,544  |2,006,799.23|
SA701 |1,061.00  |1,063.00  |1,063.00  |1,014.00  |1,017.00  |1,035.00  |17.00    |31.00    |2,121,220 |1,594,499 |11,422  |2,240,997.54|
SA703 |1,061.00  |1,062.00  |1,063.00  |1,012.00  |1,015.00  |1,033.00  |16.00    |29.00    |352,142   |360,900   |1,099    |370,663.05 |
小计    |          |          |          |          |          |          |         |         |4,368,731 |3,246,623 |4,977    |4,618,459.82|
MA610 |3,444.00  |3,457.00  |3,481.00  |3,361.00  |3,429.00  |3,422.00  |-15.00   |-22.00   |2,586,680 |340,507   |-83,751  |8,852,435.09|
MA611 |3,258.00  |3,278.00  |3,299.00  |3,177.00  |3,239.00  |3,234.00  |-19.00   |-24.00   |1,005,150 |362,783   |14,838   |3,250,564.92|
小计    |          |          |          |          |          |          |         |         |3,591,830 |703,290   |-68,913  |12,103,000.01|
"""

DCE_DAILY_FIXTURE = """\
品种\t商品名称\t合约代码\t开盘价\t最高价\t最低价\t收盘价\t结算价\t成交量\t持仓量
v\t聚氯乙烯\tv2601\t4,900.00\t4,950.00\t4,880.00\t4,920.00\t4,925.00\t120,000\t200,000
v\t聚氯乙烯\tv2605\t4,980.00\t5,020.00\t4,950.00\t4,990.00\t4,995.00\t150,000\t250,000
pp\t聚丙烯\tpp2601\t7,100.00\t7,150.00\t7,050.00\t7,100.00\t7,120.00\t80,000\t90,000
l\t聚乙烯\tl2601\t8,000.00\t8,050.00\t7,950.00\t8,000.00\t8,010.00\t60,000\t70,000
eb\t苯乙烯\teb2601\t8,500.00\t8,600.00\t8,400.00\t8,500.00\t8,550.00\t50,000\t55,000
"""


def test_parse_czce_daily_text_extracts_symbols_and_contracts() -> None:
    daily = parse_czce_daily_text(CZCE_DAILY_FIXTURE, ("SA", "MA"))

    assert set(daily.keys()) == {"SA", "MA"}
    assert len(daily["SA"]) == 3
    assert len(daily["MA"]) == 2
    assert daily["SA"][0]["contract"] == "SA610"
    assert daily["SA"][0]["settle"] == 1037.0
    assert daily["SA"][0]["close"] == 1019.0
    assert daily["SA"][0]["open_interest"] == 1291224.0
    assert daily["SA"][0]["volume"] == 1895369.0
    # 千分位清理
    assert daily["MA"][1]["open_interest"] == 362783.0


def test_pick_main_contract_uses_largest_open_interest() -> None:
    daily = parse_czce_daily_text(CZCE_DAILY_FIXTURE, ("SA", "MA"))

    main_sa = pick_main_contract(daily["SA"])
    main_ma = pick_main_contract(daily["MA"])

    assert main_sa is not None
    assert main_sa["contract"] == "SA701"  # 持仓量 1,594,499 最大
    assert main_sa["settle"] == 1035.0
    assert main_ma is not None
    assert main_ma["contract"] == "MA611"  # 持仓量 362,783 最大


def test_pick_main_contract_returns_none_for_empty_or_zero_rows() -> None:
    assert pick_main_contract([]) is None
    assert (
        pick_main_contract(
            [
                {"open_interest": 0.0, "volume": 0.0},
                {"open_interest": None, "volume": None},
            ]
        )
        is None
    )


def test_build_record_keeps_official_source_and_continuous_contract() -> None:
    main = {
        "symbol": "SA",
        "contract": "SA701",
        "open": 1063.0,
        "high": 1063.0,
        "low": 1014.0,
        "close": 1017.0,
        "settle": 1035.0,
        "volume": 2121220.0,
        "open_interest": 1594499.0,
    }
    record = build_daily_record(
        symbol="SA",
        meta={"main_contract": "SA0", "exchange": "CZCE"},
        trade_date=date(2026, 9, 15),
        main=main,
        source_sha256="abc123",
        now_iso="2026-09-16T10:00:00+08:00",
    )

    assert record["contract"] == "SA0"  # 主力连续代码保持不变
    assert record["settle"] == "1035.00"
    assert record["open_interest"] == "1594499"
    assert record["source"] == "Exchange_Official/CZCE"
    assert record["source_url"].endswith("FutureDataDaily.txt")
    assert record["raw_content_sha256"] == "abc123"
    assert record["data_status"] == "actual"


def test_fmt_handles_none_and_integer_flag() -> None:
    assert _fmt_value(None) == ""
    assert _fmt_value(None, integer=True) == ""
    assert _fmt_value(1035.0) == "1035.00"
    assert _fmt_value(1594499.0, integer=True) == "1594499"


def test_parse_dce_daily_text_extracts_symbols_and_contracts() -> None:
    daily = parse_dce_daily_text(DCE_DAILY_FIXTURE, ("V", "PP", "L", "EB"))

    assert set(daily.keys()) == {"V", "PP", "L", "EB"}
    assert len(daily["V"]) == 2
    assert daily["V"][0]["contract"] == "v2601"
    assert daily["V"][0]["settle"] == 4925.0
    assert daily["V"][0]["close"] == 4920.0
    assert daily["V"][0]["high"] == 4950.0
    assert daily["V"][0]["low"] == 4880.0
    assert daily["V"][0]["open_interest"] == 200000.0
    assert daily["V"][0]["volume"] == 120000.0
    # 千分位清理
    assert daily["PP"][0]["open"] == 7100.0


def test_dce_main_contract_uses_largest_open_interest() -> None:
    daily = parse_dce_daily_text(DCE_DAILY_FIXTURE, ("V", "PP", "L", "EB"))

    main = pick_main_contract(daily["V"])
    assert main is not None
    assert main["contract"] == "v2605"  # 持仓量 250,000 最大
    assert main["settle"] == 4995.0


def test_build_record_dce_keeps_official_source_and_continuous_contract() -> None:
    main = {
        "symbol": "V",
        "contract": "v2605",
        "open": 4980.0,
        "high": 5020.0,
        "low": 4950.0,
        "close": 4990.0,
        "settle": 4995.0,
        "volume": 150000.0,
        "open_interest": 250000.0,
    }
    record = build_daily_record(
        symbol="V",
        meta={"main_contract": "V0", "exchange": "DCE"},
        trade_date=date(2026, 9, 15),
        main=main,
        source_sha256="dce-sha",
        now_iso="2026-09-16T10:00:00+08:00",
        exchange="DCE",
        source="Exchange_Official/DCE",
        source_url=DCE_DAILY_PAGE_URL,
        snapshot_dir="dce_daily_cache",
    )

    assert record["contract"] == "V0"  # 主力连续代码保持不变
    assert record["exchange"] == "DCE"
    assert record["source"] == "Exchange_Official/DCE"
    assert record["source_url"] == DCE_DAILY_PAGE_URL
    assert record["raw_snapshot_path"].startswith(
        "industry/chemicals/futures_daily/dce_daily_cache/2026/"
    )
    assert record["raw_snapshot_path"].endswith("20260915.txt")
    assert record["settle"] == "4995.00"
    assert record["open_interest"] == "250000"
    assert record["high"] == "5020.00"
    assert record["low"] == "4950.00"
    assert record["data_status"] == "actual"


def test_merge_daily_rows_keeps_only_official_source_for_dce(tmp_path) -> None:
    daily_dir = tmp_path / "futures_daily"
    daily_dir.mkdir()
    csv_path = daily_dir / "V.csv"
    csv_path.write_text(
        "trade_date,source\n2009-05-25,Exchange_DCE/Sina_Futures\n",
        encoding="utf-8",
    )
    new_rows = [
        {
            "trade_date": "2026-09-15",
            "source": "Exchange_Official/DCE",
        }
    ]

    merged = merge_daily_rows(
        read_daily_csv(csv_path),
        new_rows,
        keep_sources={"Exchange_Official/DCE"},
    )

    assert [row["trade_date"] for row in merged] == ["2026-09-15"]


def test_download_dce_daily_reads_csv_cache_file(tmp_path) -> None:
    year_dir = tmp_path / "dce_daily_cache" / "2026"
    year_dir.mkdir(parents=True)
    (year_dir / "20260915.csv").write_text(DCE_DAILY_FIXTURE, encoding="utf-8")

    text = download_dce_daily_text(date(2026, 9, 15), tmp_path / "dce_daily_cache")

    assert text is not None
    daily = parse_dce_daily_text(text, ("V", "PP", "L", "EB"))
    assert daily["V"][0]["settle"] == 4925.0
    assert daily["V"][1]["open_interest"] == 250000.0


def test_download_dce_daily_reads_gbk_cache_file(tmp_path) -> None:
    year_dir = tmp_path / "dce_daily_cache" / "2026"
    year_dir.mkdir(parents=True)
    (year_dir / "20260915.txt").write_bytes(DCE_DAILY_FIXTURE.encode("gbk"))

    text = download_dce_daily_text(date(2026, 9, 15), tmp_path / "dce_daily_cache")

    assert text is not None
    assert parse_dce_daily_text(text, ("V", "PP", "L", "EB"))["PP"]


def test_has_dce_cache_files_empty_dir_returns_false(tmp_path) -> None:
    assert official_mod._has_dce_cache_files(tmp_path) is False
    assert official_mod._has_dce_cache_files(tmp_path / "missing") is False


def test_backfill_script_smoke_import() -> None:
    import scripts.backfill_chemical_futures_daily as backfill_mod

    assert callable(backfill_mod.main)
    assert backfill_mod.FuturesPriceCollector is not None
