"""全市场聚合监控产物管线测试。"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

import stock_analytics.pipelines.market_aggregate.pipeline as market_aggregate_pipeline
from stock_analytics.pipelines.market_aggregate import run_market_aggregate
from stock_data.fetcher.realtime.market_aggregate import (
    BaseMarketAggregateFetcher,
    MarketAggregateSnapshot,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class _Fetcher(BaseMarketAggregateFetcher):
    source = "tencent"

    def __init__(self, snapshot: MarketAggregateSnapshot) -> None:
        self.snapshot = snapshot

    def fetch_aggregate(self) -> MarketAggregateSnapshot:
        return self.snapshot


class _TrendCatalog:
    def load_dataset(self, dataset: str, **_: object) -> pl.DataFrame:
        dates = [
            datetime(2026, 8, 14).date(),
            datetime(2026, 8, 17).date(),
            datetime(2026, 8, 18).date(),
            datetime(2026, 8, 19).date(),
        ]
        if dataset == "stock_daily_bar":
            return pl.DataFrame(
                [
                    {
                        "trade_date": trade_date,
                        "symbol": symbol,
                        "close": 10.0,
                        "pre_close": 10.0,
                        "pct_chg": 1.0 if symbol == "000001.SZ" else -1.0,
                        "amount": 100.0,
                    }
                    for trade_date in dates
                    for symbol in ("000001.SZ", "600000.SH")
                ]
            )
        return pl.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "circ_mv": 1_000.0,
                    "total_mv": 1_200.0,
                }
                for trade_date in dates
                for symbol in ("000001.SZ", "600000.SH")
            ]
        )


def _snapshot(
    received_at: datetime,
    *,
    status: str = "valid",
    coverage_ratio: float = 1.0,
) -> MarketAggregateSnapshot:
    return MarketAggregateSnapshot(
        status=status,  # type: ignore[arg-type]
        received_at=received_at,
        reported_count=100,
        returned_count=int(100 * coverage_ratio),
        priced_count=100,
        change_count=100,
        amount_count=100,
        market_cap_count=100,
        coverage_ratio=coverage_ratio,
        advance_count=60,
        decline_count=30,
        flat_count=10,
        advance_share=0.6,
        decline_share=0.3,
        advance_decline_ratio=2.0,
        strong_up_threshold_pct=5.0,
        strong_up_count=8,
        strong_down_count=3,
        strong_up_share=0.08,
        strong_down_share=0.03,
        median_pct_change=1.2,
        pct_change_p25=-0.8,
        pct_change_p75=2.8,
        weighted_pct_change=0.9,
        amount_total_yuan=2_000_000_000_000,
        total_market_value_yuan=100_000_000_000_000,
        free_float_market_value_yuan=70_000_000_000_000,
        free_float_turnover_pct=2.86,
        amount_top_5pct_share=0.55,
    )


def test_pipeline_renders_configured_reports_and_latest_artifacts(tmp_path: Path) -> None:
    received_at = datetime(2026, 8, 19, 10, 0, tzinfo=_SHANGHAI_TZ)
    result = run_market_aggregate(
        output_root=tmp_path / "analytics",
        fetcher=_Fetcher(_snapshot(received_at)),
        now=received_at,
    )

    assert result.as_of_date.isoformat() == "2026-08-19"
    assert result.manifest["status"] == "valid"
    assert result.quality_report_json["status"] == "passed"
    assert "A 股全市场实时聚合监控" in result.report_markdown
    assert "接收时间: 2026-08-19 10:00:00" in result.report_markdown
    assert "市场广度" in result.report_markdown
    assert "成交额前 5% 集中度" in result.human_report_markdown
    assert "上涨扩散占优" in result.human_report_markdown
    assert "非逐标的快照" in result.table_markdown
    for path in (
        result.paths.manifest,
        result.paths.snapshot,
        result.paths.facts,
        result.paths.trend,
        result.paths.report_md,
        result.paths.report_json,
        result.paths.human_report_md,
        result.paths.quality_report_md,
        result.paths.quality_report_json,
    ):
        assert path.exists()
    assert (result.paths.latest_dir / "report.md").exists()
    assert pl.read_parquet(result.paths.facts)["returned_count"].to_list() == [100]


def test_pipeline_marks_partial_snapshot_below_coverage_threshold(tmp_path: Path) -> None:
    received_at = datetime(2026, 8, 19, 10, 0, tzinfo=_SHANGHAI_TZ)
    result = run_market_aggregate(
        output_root=tmp_path,
        fetcher=_Fetcher(_snapshot(received_at, status="partial", coverage_ratio=0.5)),
        now=received_at,
    )

    assert result.quality_report_json["status"] == "failed"
    assert result.quality_report_json["summary"]["error_count"] == 1
    assert "低于质量阈值" in result.quality_report_markdown


def test_pipeline_renders_short_term_trend_for_human_report(tmp_path: Path) -> None:
    received_at = datetime(2026, 8, 20, 10, 0, tzinfo=_SHANGHAI_TZ)
    result = run_market_aggregate(
        output_root=tmp_path,
        fetcher=_Fetcher(_snapshot(received_at)),
        catalog=_TrendCatalog(),
        now=received_at,
    )

    assert result.short_term_trend["status"] == "available"
    assert "最近 5 个交易日短期趋势" in result.human_report_markdown
    assert "今日为腾讯实时快照" in result.human_report_markdown
    assert result.report_json["trend"]["history_dates"] == [
        "2026-08-14",
        "2026-08-17",
        "2026-08-18",
        "2026-08-19",
    ]
    assert result.paths.trend.exists()


def test_load_market_symbols_uses_local_stock_basic_and_excludes_non_sh_sz(monkeypatch) -> None:
    class _Catalog:
        def __init__(self, *, data_source: str) -> None:
            assert data_source == "tushare"

        def load_dataset(self, dataset: str) -> pl.DataFrame:
            assert dataset == "stock_basic"
            return pl.DataFrame(
                {
                    "ts_code": ["000001.SZ", "600519", "430001.BJ", "000002.SZ"],
                    "exchange": ["SZSE", "SSE", "BSE", "SZSE"],
                    "list_status": ["L", "L", "L", "D"],
                }
            )

    monkeypatch.setattr(market_aggregate_pipeline, "DataCatalog", _Catalog)

    assert market_aggregate_pipeline._load_market_symbols("stock_basic") == (
        "000001.SZ",
        "600519.SH",
    )
