"""核心观察池腾讯实时快照监控 CLI 兼容入口。"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from stock_analytics.realtime import RealtimeSession, create_realtime_session
from stock_core.exceptions import DataFetchError

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_DISPLAY_COLUMNS = (
    ("symbol", "代码"),
    ("name", "名称"),
    ("price", "现价"),
    ("pct_change", "涨跌幅%"),
    ("ma20_deviation_pct", "MA20偏离%"),
    ("ma60_deviation_pct", "MA60偏离%"),
    ("amount_ratio_20d", "成交额/20日"),
    ("freshness", "新鲜度"),
    ("warning", "预警"),
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="腾讯实时快照核心观察池体检（不代表全市场）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--watch", action="store_true", help="持续监控，按间隔重复抓取")
    parser.add_argument("--interval", type=float, default=3.0, help="持续监控的抓取间隔（秒）")
    parser.add_argument("--format", choices=("table", "markdown"), default="table", help="输出格式")
    parser.add_argument("--record", action="store_true", help="将快照批量留档到 RAW realtime 目录")
    parser.add_argument("--storage-dir", default=None, help="Curated 数据根目录")
    parser.add_argument("--raw-root", default=None, help="实时快照 RAW 留档根目录")
    return parser


def main() -> None:
    """解析参数并执行一次或持续执行实时观察池监控。"""
    args = _build_parser().parse_args()
    session: RealtimeSession | None = None
    try:
        session = create_realtime_session(
            storage_dir=args.storage_dir,
            raw_root=args.raw_root,
            record=args.record,
        )
        while True:
            frame = session.run_once()
            sys.stdout.write(_format_report(frame, session.configured_count, args.format))
            sys.stdout.flush()
            if not args.watch:
                break
            time.sleep(max(0.1, args.interval))
    except KeyboardInterrupt:
        if session is not None:
            session.flush(now=datetime.now(_SHANGHAI_TZ))
        sys.stdout.write("\n已停止实时监控。\n")
    except (DataFetchError, FileNotFoundError) as error:
        if session is not None:
            session.flush(now=datetime.now(_SHANGHAI_TZ))
        _fail(str(error))


def _format_report(frame: pl.DataFrame, configured_count: int, output_format: str) -> str:
    now = datetime.now(_SHANGHAI_TZ).isoformat(timespec="seconds")
    usable_count = (
        frame.filter(
            (pl.col("quote_status") == "valid") & pl.col("freshness").is_in(("fresh", "stale"))
        ).height
        if {"quote_status", "freshness"}.issubset(frame.columns)
        else 0
    )
    header = (
        f"范围：核心观察池（配置 {configured_count} 只，不代表全市场）\n"
        f"数据源：TencentRealtimeFetcher | 本地时间：{now} | 可计算快照：{usable_count}\n"
    )
    body = _format_markdown(frame) if output_format == "markdown" else _format_table(frame)
    return f"\n{header}{body}\n"


def _format_table(frame: pl.DataFrame) -> str:
    rows = [_display_row(row) for row in frame.iter_rows(named=True)]
    headers = [label for _, label in _DISPLAY_COLUMNS]
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(value)) for width, value in zip(widths, row, strict=True)]
    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+\n"
    output = (
        separator
        + "| "
        + " | ".join(header.ljust(width) for header, width in zip(headers, widths, strict=True))
        + " |\n"
        + separator
    )
    output += "".join(
        "| "
        + " | ".join(value.ljust(width) for value, width in zip(row, widths, strict=True))
        + " |\n"
        for row in rows
    )
    return output + separator


def _format_markdown(frame: pl.DataFrame) -> str:
    headers = [label for _, label in _DISPLAY_COLUMNS]
    output = "| " + " | ".join(headers) + " |\n"
    output += "| " + " | ".join("---" for _ in headers) + " |\n"
    output += "".join(
        "| " + " | ".join(_display_row(row)) + " |\n" for row in frame.iter_rows(named=True)
    )
    return output


def _display_row(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for column, _ in _DISPLAY_COLUMNS:
        value = row.get(column)
        if value is None or value == "":
            values.append("-")
        elif column in {"pct_change", "ma20_deviation_pct", "ma60_deviation_pct"}:
            values.append(f"{float(value):.2f}")
        elif column == "amount_ratio_20d":
            values.append(f"{float(value):.2f}x")
        elif column == "price":
            values.append(f"{float(value):.3f}")
        else:
            values.append(str(value))
    return values


def _fail(message: str) -> None:
    sys.stderr.write(f"实时监控失败：{message}\n")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
