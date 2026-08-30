from datetime import date
from pathlib import Path

import polars as pl

from stock_strategy.industry.report import (
    build_multi_industry_comparison_report,
    compute_metrics,
    load_all_industry_strategy_specs,
    load_industry_benchmarks,
)


def test_load_specs_and_benchmarks() -> None:
    # 轮动策略池已于 2026-08-31 停用（industry_rotation.yaml strategies 为空）
    specs = load_all_industry_strategy_specs()
    assert specs == {}

    benches = load_industry_benchmarks()
    assert len(benches) >= 1
    assert benches[0][0] == "000985.CSI"


def test_compute_metrics() -> None:
    nav_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "nav": [1.0, 1.10],
        }
    )
    m = compute_metrics(nav_df)
    assert m["final_nav"] == 1.10
    assert m["total_return"] == 10.0


def test_build_multi_industry_comparison_report_runs(tmp_path: Path) -> None:
    res = build_multi_industry_comparison_report(
        output_dir=tmp_path,
        start_date=date(2026, 8, 1),
    )
    assert "stats" in res
    assert Path(res["markdown"]).exists()
    assert Path(res["png"]).exists()
    assert Path(res["csv"]).exists()
