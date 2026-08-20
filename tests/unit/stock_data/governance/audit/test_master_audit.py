from pathlib import Path
from unittest.mock import patch

import polars as pl

from stock_data.governance.audit.master_audit import main, run_master_audit


def test_run_master_audit_empty(tmp_path: Path) -> None:
    df = run_master_audit(str(tmp_path))
    assert df.is_empty()


def test_run_master_audit_with_data(tmp_path: Path) -> None:
    target_dir = tmp_path / "tushare" / "market=CN" / "index_daily" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / "data.parquet"

    mock_df = pl.DataFrame(
        {
            "symbol": ["000001.SH", "000300.SH"],
            "trade_date": ["2026-08-01", "2026-08-02"],
            "close": [3000.0, 4000.0],
        }
    )
    mock_df.write_parquet(file_path)

    summary = run_master_audit(str(tmp_path))
    assert not summary.is_empty()
    assert "source" in summary.columns
    assert summary["精炼落盘总记录数"][0] == 2
    assert summary["审计错误数"][0] == 0


def test_run_master_audit_counts_union_of_normalized_symbols(tmp_path: Path) -> None:
    first_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    second_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=09"
    first_dir.mkdir(parents=True, exist_ok=True)
    second_dir.mkdir(parents=True, exist_ok=True)

    pl.DataFrame(
        {
            "symbol": ["A", "B"],
            "ts_code": pl.Series([None, None], dtype=pl.String),
            "trade_date": ["2026-08-01", "2026-08-01"],
        }
    ).write_parquet(first_dir / "data.parquet")
    pl.DataFrame(
        {
            "symbol": pl.Series([None, "C"], dtype=pl.String),
            "ts_code": ["D", "C"],
            "trade_date": ["2026-09-01", "2026-09-01"],
        }
    ).write_parquet(second_dir / "data.parquet")

    summary = run_master_audit(str(tmp_path))

    assert summary["标的数"].to_list() == [4]


def test_run_master_audit_reports_bad_parquet(tmp_path: Path) -> None:
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar"
    target_dir.mkdir(parents=True)
    (target_dir / "data.parquet").write_text("not a parquet file", encoding="utf-8")

    summary = run_master_audit(str(tmp_path))

    assert not summary.is_empty()
    assert summary["审计错误数"][0] == 1


def test_run_master_audit_detects_year_gaps(tmp_path: Path) -> None:
    # 构造只有 2014 和 2026 年的数据，缺失 2015-2025
    dir_2014 = tmp_path / "tushare" / "market=CN" / "adj_factor" / "year=2014" / "month=08"
    dir_2014.mkdir(parents=True, exist_ok=True)
    df_2014 = pl.DataFrame(
        {"symbol": ["000001.SZ"], "trade_date": ["2014-08-01"], "adj_factor": [1.0]}
    )
    df_2014.write_parquet(dir_2014 / "data.parquet")

    dir_2026 = tmp_path / "tushare" / "market=CN" / "adj_factor" / "year=2026" / "month=08"
    dir_2026.mkdir(parents=True, exist_ok=True)
    df_2026 = pl.DataFrame(
        {"symbol": ["000001.SZ"], "trade_date": ["2026-08-01"], "adj_factor": [2.0]}
    )
    df_2026.write_parquet(dir_2026 / "data.parquet")

    summary = run_master_audit(str(tmp_path))
    assert not summary.is_empty()
    assert "year_gap_warning" in summary.columns
    warning = summary["year_gap_warning"][0]
    assert warning is not None
    assert "2015..2025" in warning


def test_run_master_audit_uses_record_years_for_cross_year_files(tmp_path: Path) -> None:
    first_file = tmp_path / "yfinance" / "market=GLOBAL" / "macro_indicators"
    first_file.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["^TNX"] * 12,
            "trade_date": [f"{year}-01-01" for year in range(2014, 2026)],
            "close": [1.0] * 12,
        }
    ).write_parquet(first_file / "data.parquet")

    second_file = tmp_path / "yfinance" / "market=US" / "macro_indicators"
    second_file.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"symbol": ["^GSPC"], "trade_date": ["2026-01-01"], "close": [1.0]}).write_parquet(
        second_file / "data.parquet"
    )

    summary = run_master_audit(str(tmp_path))

    assert summary.filter(pl.col("dataset") == "macro_indicators")[
        "year_gap_warning"
    ].to_list() == [None]


def test_run_master_audit_uses_report_year_not_partition_year(tmp_path: Path) -> None:
    first_file = tmp_path / "tushare" / "market=CN" / "balancesheet" / "year=1992" / "month=12"
    first_file.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {"symbol": ["000001.SZ"], "ann_date": ["1993-04-01"], "end_date": ["1992-12-31"]}
    ).write_parquet(first_file / "data.parquet")

    second_file = tmp_path / "tushare" / "market=CN" / "balancesheet" / "year=1994" / "month=04"
    second_file.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {"symbol": ["000001.SZ"], "ann_date": ["1994-04-16"], "end_date": ["1993-12-31"]}
    ).write_parquet(second_file / "data.parquet")

    summary = run_master_audit(str(tmp_path))

    assert summary["year_gap_warning"].to_list() == [None]


def test_main(capsys) -> None:
    with patch("stock_data.governance.audit.master_audit.run_master_audit") as mock_audit:
        mock_audit.return_value = pl.DataFrame(
            {
                "source": ["tushare"],
                "dataset": ["stock_daily_bar"],
                "分区数": [1],
                "标的数": [10],
                "精炼落盘总记录数": [1000],
                "最早交易日": ["2024-01-01"],
                "最新交易日": ["2024-01-10"],
                "审计错误数": [0],
            }
        )
        main()
        captured = capsys.readouterr()
        assert "全库全量数据离线存储主审计报告" in captured.out
