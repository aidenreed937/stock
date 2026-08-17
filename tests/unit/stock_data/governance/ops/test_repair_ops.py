"""单元测试：daily_basic 与 sw_daily 数据治理修复工具。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_data.governance.audit.reconciliation import _filter_target_date
from stock_data.governance.ops.repair_daily_basic import clean_partition_daily_basic
from stock_data.governance.ops.repair_sw_daily import clean_partition_sw_daily


def test_clean_partition_daily_basic(tmp_path: Path) -> None:
    raw_file = tmp_path / "raw.parquet"
    cur_file = tmp_path / "cur.parquet"

    # 构造混杂 RAW 数据：含原始 21 列数据（万元）与已归一截断数据（元）
    df_raw = pl.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "trade_date": ["20260105", "2026-01-05", "2026-01-05"],
            # 1: 万元, 2: 元(重复), 3: 元(仅截断存在)
            "total_mv": [2231700.0, 22317000000.0, 5000000000.0],
            "circ_mv": [2231600.0, 22316000000.0, 4000000000.0],
            "close": [11.5, None, None],
            "pe": [4.8, None, None],
            "source_unit_note": [
                None,
                "Tushare daily_basic market values are normalized",
                "Tushare daily_basic market values are normalized",
            ],
        }
    )
    df_raw.write_parquet(raw_file)

    res = clean_partition_daily_basic(raw_file, cur_file, apply=True)
    assert res["raw_before"] == 3
    assert res["raw_after"] == 2  # 000001.SZ 原始行优先，000002.SZ 仅有截断行保留
    assert res["cur_after"] == 2
    assert res["abnormal_mv_count"] == 0  # 无万亿元异常值

    # 验证 Curated 数据的值
    cur_df = pl.read_parquet(cur_file)
    assert "symbol" in cur_df.columns
    assert "trade_date" in cur_df.columns
    assert cur_df["trade_date"].dtype == pl.Date

    sym1 = cur_df.filter(pl.col("symbol") == "000001.SZ")
    assert sym1["total_mv"][0] == 2231700.0 * 10000.0  # 223.17 亿元
    assert sym1["close"][0] == 11.5
    assert sym1["pe"][0] == 4.8

    sym2 = cur_df.filter(pl.col("symbol") == "000002.SZ")
    assert sym2["total_mv"][0] == 5000000000.0  # 50 亿元 (保持 * 1.0)
    assert set(cur_df["schema_version"].to_list()) == {"v2"}
    assert set(cur_df["adjustment"].to_list()) == {"raw"}


def test_clean_partition_sw_daily(tmp_path: Path) -> None:
    cur_file = tmp_path / "sw_cur.parquet"

    # 构造包含 symbol 与 index_id 的混杂数据
    df = pl.DataFrame(
        {
            "symbol": ["801010.SI", "801980.SI", None],
            "index_id": [None, None, "801980.SI"],
            "trade_date": ["2026-01-05", "2026-01-05", "2026-01-05"],
            "close": [1500.0, 3300.0, 3300.0],
            "amount": [1_000_000_000.0, 2_000_000_000.0, 3_000_000_000.0],
            "request_id": ["legacy:sw_daily:test", "legacy:sw_daily:test", "repair_run"],
        }
    )
    df.write_parquet(cur_file)

    res = clean_partition_sw_daily(cur_file, apply=True)
    assert res["before"] == 3
    assert res["after"] == 2
    assert res["removed"] == 1

    cleaned = pl.read_parquet(cur_file)
    assert len(cleaned) == 2
    assert set(cleaned["symbol"].to_list()) == {"801010.SI", "801980.SI"}
    # 验证保留的是 legacy 记录
    sym801980 = cleaned.filter(pl.col("symbol") == "801980.SI")
    assert sym801980["request_id"][0] == "legacy:sw_daily:test"
    assert sym801980["amount"][0] == 2_000_000_000.0


def test_reconciliation_filter_target_date_multi_format() -> None:
    df = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "600519.SH", "000002.SZ"],
            "trade_date": ["2026-08-12", "20260812", "2026-08-13"],
        }
    )
    filtered = _filter_target_date(df, date(2026, 8, 12))
    assert len(filtered) == 2
    assert set(filtered["symbol"].to_list()) == {"000001.SZ", "600519.SH"}
