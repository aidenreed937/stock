from pathlib import Path
import polars as pl
from stock.data.audit.master_audit import run_master_audit, main


def test_run_master_audit_empty(tmp_path: Path) -> None:
    df = run_master_audit(str(tmp_path))
    assert df.is_empty()


def test_run_master_audit_with_data(tmp_path: Path) -> None:
    # 模拟构建 Parquet 文件目录结构: tmp_path / tushare / market=CN / index_daily / year=2026 / month=08 / data.parquet
    target_dir = tmp_path / "tushare" / "market=CN" / "index_daily" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / "data.parquet"

    mock_df = pl.DataFrame({
        "symbol": ["000001.SH", "000300.SH"],
        "trade_date": ["2026-08-01", "2026-08-02"],
        "close": [3000.0, 4000.0],
    })
    mock_df.write_parquet(file_path)

    summary = run_master_audit(str(tmp_path))
    assert not summary.is_empty()
    assert "source" in summary.columns
    assert summary["精炼落盘总记录数"][0] == 2


def test_main(capsys) -> None:
    main()
    captured = capsys.readouterr()
    assert "全库全量数据离线存储主审计报告" in captured.out
