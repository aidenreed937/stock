"""A 股全市场低频聚合摘要 CLI。"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_analytics.realtime.cache import CachedMarketAggregate
from stock_analytics.realtime.market_aggregate_monitor import MarketAggregateMonitor
from stock_core.exceptions import DataFetchError
from stock_data.core.settings import data_settings
from stock_data.fetcher.realtime.market_aggregate import MarketAggregateFetcher
from stock_data.fetcher.realtime.market_aggregate_recorder import (
    MarketAggregateSnapshotRecorder,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="东方财富 A 股全市场低频聚合摘要（不输出逐标的明细）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--watch", action="store_true", help="持续监控，按间隔重复抓取")
    parser.add_argument("--interval", type=float, default=60.0, help="持续监控的抓取间隔（秒）")
    parser.add_argument(
        "--format",
        choices=("table", "markdown"),
        default="table",
        help="输出格式",
    )
    parser.add_argument("--record", action="store_true", help="将一行聚合快照留档到 RAW")
    parser.add_argument("--raw-root", default=None, help="聚合快照 RAW 留档根目录")
    parser.add_argument("--page-size", type=int, default=100, help="每页请求条数，接口上限为 100")
    parser.add_argument("--max-pages", type=int, default=100, help="最多请求页数")
    parser.add_argument(
        "--strong-move-pct",
        type=float,
        default=5.0,
        help="强势上涨/下跌统计阈值（百分比，不等同于涨跌停）",
    )
    return parser


def main() -> None:
    """执行一次或持续执行 A 股全市场聚合监控。"""
    args = _build_parser().parse_args()
    recorder = None
    try:
        if args.record:
            runtime = data_settings.runtime_context
            raw_root = (
                Path(args.raw_root)
                if args.raw_root
                else runtime.raw_root / "realtime" / "market_aggregate" / "eastmoney"
            )
            recorder = MarketAggregateSnapshotRecorder(root=raw_root)
        monitor = MarketAggregateMonitor(
            MarketAggregateFetcher(
                page_size=args.page_size,
                max_pages=args.max_pages,
                strong_move_threshold_pct=args.strong_move_pct,
            ),
            recorder=recorder,
        )
        while True:
            result = monitor.run()
            sys.stdout.write(_format_report(result, args.format))
            sys.stdout.flush()
            if not args.watch:
                break
            time.sleep(max(1.0, args.interval))
    except KeyboardInterrupt:
        if recorder is not None:
            recorder.flush(now=datetime.now(_SHANGHAI_TZ))
        sys.stdout.write("\n已停止全市场聚合监控。\n")
    except DataFetchError as exc:
        if recorder is not None:
            recorder.flush(now=datetime.now(_SHANGHAI_TZ))
        _fail(str(exc))


def _format_report(result: CachedMarketAggregate, output_format: str) -> str:
    snapshot = result.snapshot
    header = (
        "范围：A股全市场聚合摘要（非逐标的快照）\n"
        f"数据源：{snapshot.source} | 状态：{snapshot.status} | "
        f"覆盖：{snapshot.returned_count}/{snapshot.reported_count} "
        f"（{snapshot.coverage_ratio:.1%}） | 新鲜度：{result.freshness.value}\n"
    )
    rows = [
        (
            "上涨 / 下跌 / 平盘",
            f"{snapshot.advance_count} / {snapshot.decline_count} / {snapshot.flat_count}",
        ),
        (
            "上涨占比 / 下跌占比",
            f"{_share_pct(snapshot.advance_share)} / {_share_pct(snapshot.decline_share)}",
        ),
        ("涨跌比（上涨 / 下跌）", _ratio(snapshot.advance_decline_ratio)),
        (
            f"强势上涨 / 强势下跌（±{snapshot.strong_up_threshold_pct:.1f}%）",
            f"{snapshot.strong_up_count} / {snapshot.strong_down_count}",
        ),
        (
            "中位涨跌幅 / 成交额加权涨跌幅",
            f"{_pct(snapshot.median_pct_change)} / {_pct(snapshot.weighted_pct_change)}",
        ),
        ("成交额", _money(snapshot.amount_total_yuan)),
        ("总市值", _money(snapshot.total_market_value_yuan)),
        (
            "流通市值 / 流通换手率",
            f"{_money(snapshot.free_float_market_value_yuan)} / {_pct(snapshot.free_float_turnover_pct)}",
        ),
        ("成交额前 5% 集中度", _share_pct(snapshot.amount_top_5pct_share)),
        ("P25 / P75 涨跌幅", f"{_pct(snapshot.pct_change_p25)} / {_pct(snapshot.pct_change_p75)}"),
    ]
    body = _format_markdown(rows) if output_format == "markdown" else _format_table(rows)
    return f"\n{header}{body}\n"


def _format_table(rows: list[tuple[str, str]]) -> str:
    widths = [len("指标"), len("数值")]
    for label, value in rows:
        widths[0] = max(widths[0], len(label))
        widths[1] = max(widths[1], len(value))
    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+\n"
    output = separator + f"| {'指标'.ljust(widths[0])} | {'数值'.ljust(widths[1])} |\n" + separator
    output += "".join(
        f"| {label.ljust(widths[0])} | {value.ljust(widths[1])} |\n" for label, value in rows
    )
    return output + separator


def _format_markdown(rows: list[tuple[str, str]]) -> str:
    return "| 指标 | 数值 |\n| --- | --- |\n" + "".join(
        f"| {label} | {value} |\n" for label, value in rows
    )


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}%"


def _share_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.2%}"


def _ratio(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}万亿"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.0f}元"


def _fail(message: str) -> None:
    sys.stderr.write(f"全市场聚合监控失败：{message}\n")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
