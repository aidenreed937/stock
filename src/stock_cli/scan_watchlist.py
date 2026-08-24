"""自选池批量量化雷达 CLI 入口。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.watchlist_scanner import run_watchlist_scanner
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.scan_watchlist",
        description="自选池批量量化雷达 CLI: 一键并发扫描核心观察池，筛选极低估值、高股息利差与价值陷阱标的",
    )
    parser.add_argument(
        "--as-of",
        "-d",
        dest="as_of_date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="扫描基准日期 (YYYY-MM-DD，默认为最新交易日)",
    )
    parser.add_argument(
        "--format",
        "-f",
        dest="output_format",
        choices=["json", "markdown"],
        default="markdown",
        help="输出格式: markdown (全景雷达表) 或 json (结构化低 Token 格式)",
    )
    parser.add_argument(
        "--save",
        "-s",
        action="store_true",
        help="是否将雷达结果落盘保存至 data/analytics/watchlist_scanner/",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help="自定义观察池配置文件路径 (默认使用 config/universe/watchlist.yaml)",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=None,
        help="自定义数据根目录 (默认使用 data/)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        result = run_watchlist_scanner(
            target_date=args.as_of_date,
            config_path=args.config,
            storage_dir=args.storage_dir,
        )
    except Exception as exc:
        logger.error(f"自选池扫描失败: {exc}")
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)

    if args.output_format == "json":
        sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(result.to_markdown() + "\n")

    if args.save:
        base_dir = args.storage_dir or Path("data")
        save_dir = (
            base_dir / "analytics" / "watchlist_scanner" / "runs" / f"as_of={result.as_of_date}"
        )
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / "summary.json"
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"自选池扫描产物已保存至: {save_path}")


if __name__ == "__main__":
    main()
