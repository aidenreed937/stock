from pathlib import Path
from unittest.mock import patch

import polars as pl

from stock.data.audit.master_audit import main, run_master_audit


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


def test_run_master_audit_reports_bad_parquet(tmp_path: Path) -> None:
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar"
    target_dir.mkdir(parents=True)
    (target_dir / "data.parquet").write_text("not a parquet file", encoding="utf-8")

    summary = run_master_audit(str(tmp_path))

    assert not summary.is_empty()
    assert summary["审计错误数"][0] == 1


def test_main(capsys) -> None:
    with patch("stock.data.audit.master_audit.run_master_audit") as mock_audit:
        mock_audit.return_value = pl.DataFrame(
            {
                "source": ["tushare"],
                "dataset": ["stock_daily_bar"],
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
