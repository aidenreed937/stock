"""行业结构分析管线测试。"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from stock.analytics.industry_structure.pipeline import run_industry_structure


def test_run_industry_structure_writes_minimal_artifacts(tmp_path: Path) -> None:
    storage_dir = tmp_path / "curated"
    _write_sw_daily(storage_dir)
    config_path = tmp_path / "industry_structure.yaml"
    output_root = tmp_path / "analytics" / "industry_structure"
    config_path.write_text(
        f"""
industry_structure:
  schema_version: 1
  title: "测试行业结构"
  artifact_root: "{output_root}"
  main_window: 20
  short_windows: [5, 10]
  medium_windows: [60, 120]
  classification: "SW2021"
  benchmark: ""
  score_weights:
    momentum: 1.0
    valuation: 0.0
    fundamental: 0.0
    crowding: 0.0
  datasets:
    - data_source: tushare
      dataset: sw_daily
      required: true
""",
        encoding="utf-8",
    )

    result = run_industry_structure(
        target_date=date(2026, 8, 14),
        config_path=config_path,
        storage_dir=storage_dir,
    )

    assert result.as_of_date == date(2026, 8, 14)
    assert result.paths.report_md.exists()
    assert result.paths.human_report_md.exists()
    assert result.paths.industry_panel.exists()
    assert (output_root / "latest" / "industry_panel.parquet").exists()
    assert result.industry_panel.height == 12
    assert "测试行业结构" in result.report_markdown
    assert "评分口径" in result.report_markdown
    assert "TCR(20日成交占比)" in result.report_markdown
    assert "行业1" in result.report_markdown
    assert "人工阅读版" in result.human_report_markdown
    assert "标签不是互斥分组" in result.human_report_markdown


def _write_sw_daily(storage_dir: Path) -> None:
    partition = storage_dir / "tushare/market=CN/sw_daily/year=2026/month=08"
    partition.mkdir(parents=True, exist_ok=True)
    start = date(2026, 3, 1)
    trade_dates = [start + timedelta(days=offset) for offset in range(170)]
    rows = []
    for index, trade_date in enumerate(trade_dates):
        for industry_index in range(1, 13):
            base = 10.0 + industry_index
            close = base * (1.0 + index * (0.002 if industry_index <= 4 else 0.0005))
            rows.append(
                {
                    "symbol": f"801{industry_index:03d}.SI",
                    "trade_date": trade_date,
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "amount": 1_000_000_000.0 + industry_index * 10_000_000.0,
                    "name": f"行业{industry_index}",
                }
            )
    pl.DataFrame(rows).write_parquet(partition / "data.parquet")
