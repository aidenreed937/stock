"""市场温度计管线测试。"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from stock.analytics.market_temperature.pipeline import run_market_temperature


def test_run_market_temperature_writes_minimal_artifacts(tmp_path: Path) -> None:
    storage_dir = tmp_path / "curated"
    _write_stock_daily_bar(storage_dir)
    config_path = tmp_path / "market_temperature.yaml"
    output_root = tmp_path / "analytics" / "market_temperature"
    config_path.write_text(
        f"""
market_temperature:
  schema_version: 1
  title: "测试温度计"
  artifact_root: "{output_root}"
  main_window: 20
  short_windows: [5, 10]
  metric_values:
    enabled: false
  dimensions:
    - id: technical
      name: "技术面"
      weight: 1.0
      metrics: []
  datasets:
    - data_source: tushare
      dataset: stock_daily_bar
      dimension: technical
      required: true
""",
        encoding="utf-8",
    )

    result = run_market_temperature(
        target_date=date(2026, 8, 14),
        config_path=config_path,
        collect_metric_values=False,
        storage_dir=storage_dir,
    )

    assert result.as_of_date == date(2026, 8, 14)
    assert result.paths.report_md.exists()
    assert result.paths.human_report_md.exists()
    assert result.paths.quality_report_md.exists()
    assert result.paths.quality_report_json.exists()
    assert result.paths.facts.exists()
    assert (output_root / "latest" / "report.md").exists()
    assert (output_root / "latest" / "human_report.md").exists()
    assert (output_root / "latest" / "quality_report.md").exists()
    assert "测试温度计" in result.report_markdown
    assert "人工阅读版" in result.human_report_markdown
    assert "口径与质量报告" in result.quality_report_markdown
    assert "stock_daily_bar" in result.report_markdown


def _write_stock_daily_bar(storage_dir: Path) -> None:
    partition = storage_dir / "tushare/market=CN/stock_daily_bar/year=2026/month=08"
    partition.mkdir(parents=True, exist_ok=True)
    start = date(2026, 7, 20)
    trade_dates = [start + timedelta(days=offset) for offset in range(26)]
    frame = pl.DataFrame(
        {
            "symbol": ["AAA"] * len(trade_dates),
            "trade_date": trade_dates,
            "open": [10.0] * len(trade_dates),
            "high": [11.0] * len(trade_dates),
            "low": [9.0] * len(trade_dates),
            "close": [10.5] * len(trade_dates),
            "volume": [1000.0] * len(trade_dates),
            "amount": [105000.0] * len(trade_dates),
            "market": ["CN"] * len(trade_dates),
            "exchange": ["SSE"] * len(trade_dates),
            "currency": ["CNY"] * len(trade_dates),
            "adjustment": ["raw"] * len(trade_dates),
            "schema_version": ["v2"] * len(trade_dates),
            "data_source": ["tushare"] * len(trade_dates),
        }
    )
    frame.write_parquet(partition / "data.parquet")
