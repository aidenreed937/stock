"""海关出口景气研究管线 CLI（customs_prosperity）。

一键执行月度 SOP：金额面板 → 量价分解 → 商品拐点 → 观察表
（METHODOLOGY_FINAL §8），产物落 ``data/analytics/industry/customs_*.parquet``。
"""

from __future__ import annotations

import argparse
import sys

from stock_analytics.pipelines.customs_prosperity import run_customs_prosperity_pipeline
from stock_core.utils.logger import logger, setup_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.customs_prosperity",
        description="海关出口景气研究管线: 金额面板→量价分解→商品拐点→观察表 (月度 SOP)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default="config/analytics/customs_prosperity.yaml",
        help="管线配置文件路径",
    )
    parser.add_argument(
        "--output-dir",
        dest="artifact_root",
        default=None,
        help="产物输出目录覆盖 (默认取配置 artifact_root)",
    )
    parser.add_argument(
        "--storage-dir",
        dest="storage_dir",
        default=None,
        help="自定义数据根目录 (默认使用项目内置 data/)",
    )
    parser.add_argument(
        "--skip-product",
        action="store_true",
        help="跳过商品级拐点面板 (仅跑金额/量价/观察表)",
    )
    parser.add_argument(
        "--skip-forward",
        action="store_true",
        help="跳过观察表 (依赖金额+量价产物, 仅跑三个面板)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    setup_logger()

    try:
        outputs = run_customs_prosperity_pipeline(
            config_path=args.config_path,
            storage_dir=args.storage_dir,
            artifact_root=args.artifact_root,
            build_product=not args.skip_product,
            build_forward=not args.skip_forward,
        )
    except (ValueError, OSError) as exc:
        logger.error("海关出口景气管线执行失败: %s", exc)
        sys.exit(1)

    print("已生成产物:")
    for step, path in outputs.items():
        print(f"  {step}: {path}")


if __name__ == "__main__":
    main()
