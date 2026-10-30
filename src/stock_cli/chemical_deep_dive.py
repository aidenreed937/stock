"""化工第二阶段细分品种垂直深度爆破统一分发命令行工具 (Chemical Deep Dive CLI)。

支持通过参数化品名/代码一键调度任意已纳管品种的深度全景管线：
- 纯碱: SA / soda_ash / 纯碱 -> stock_cli.soda_ash
- 聚氯乙烯: V / pvc / 聚氯乙烯 -> stock_cli.pvc
- 精对苯二甲酸: TA / pta / 精对苯二甲酸 -> stock_cli.pta
- 钛白粉: TiO2 / tio2 / 钛白粉 -> stock_cli.tio2
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from stock_core.utils.logger import logger

SYMBOL_DISPATCH_MAP: dict[str, str] = {
    # 纯碱
    "SA": "soda_ash",
    "SODA_ASH": "soda_ash",
    "SODA-ASH": "soda_ash",
    "纯碱": "soda_ash",
    # 聚氯乙烯
    "V": "pvc",
    "PVC": "pvc",
    "聚氯乙烯": "pvc",
    # 精对苯二甲酸
    "TA": "pta",
    "PTA": "pta",
    "精对苯二甲酸": "pta",
    # 钛白粉
    "TIO2": "tio2",
    "钛白粉": "tio2",
}


def normalize_commodity_symbol(raw_symbol: str) -> str:
    """将输入的任意代码、别名或品名归一化为标准子模块名称。"""
    cleaned = raw_symbol.strip().upper().replace("-", "_")
    if cleaned in SYMBOL_DISPATCH_MAP:
        return SYMBOL_DISPATCH_MAP[cleaned]
    # 中文直接查
    if raw_symbol.strip() in SYMBOL_DISPATCH_MAP:
        return SYMBOL_DISPATCH_MAP[raw_symbol.strip()]
    raise ValueError(
        f"未识别的化工品种: '{raw_symbol}'。当前已支持: "
        f"SA (纯碱), V (聚氯乙烯), TA (精对苯二甲酸), TiO2 (钛白粉)"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.chemical_deep_dive",
        description="化工细分品种第二阶段垂直深度爆破统一入口："
        "多工艺成本阶梯 + 供需与蓄水池对账 + 估值反向时钟 + 声明式量化门禁 (ArtifactStore + manifest)",
    )
    parser.add_argument(
        "--symbol",
        "-sym",
        dest="symbol",
        type=str,
        required=True,
        help="目标品种代码或名称 (如 SA, V, TA, TiO2, 纯碱, 聚氯乙烯)",
    )
    parser.add_argument(
        "--as-of",
        "-d",
        dest="as_of_date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="分析基准日期 (YYYY-MM-DD，默认最新可用日)",
    )
    parser.add_argument(
        "--save",
        "-s",
        action="store_true",
        help="将产物归档落盘至 data/analytics/{submodule}/ (run 目录 + latest + manifest)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=("markdown", "json"),
        default="markdown",
        help="研报输出格式 (默认 markdown)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="自定义配置文件路径 (默认取各品种默认 config/analytics/{submodule}.yaml)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="产物输出根目录覆盖",
    )
    parser.add_argument(
        "--run-class",
        choices=("official", "backfill", "experiment"),
        default="official",
        help="运行分类 (默认 official)",
    )
    parser.add_argument(
        "--no-latest",
        action="store_true",
        help="落盘时不同步更新 latest 目录",
    )
    return parser


def run_deep_dive(args: argparse.Namespace) -> int:
    """根据目标品种调度对应的管线 CLI。"""
    submodule = normalize_commodity_symbol(args.symbol)
    logger.info("目标化工品种识别: %s -> 子模块 %s", args.symbol, submodule)

    # 构造传递给目标管线 CLI 的参数列表
    forward_args: list[str] = []
    if args.as_of_date:
        forward_args.extend(["--as-of", args.as_of_date.isoformat()])
    if args.save:
        forward_args.append("--save")
    if args.format:
        forward_args.extend(["--format", args.format])
    if args.config:
        forward_args.extend(["--config", str(args.config)])
    if args.output_root:
        forward_args.extend(["--output-root", str(args.output_root)])
    if args.run_class:
        forward_args.extend(["--run-class", args.run_class])
    if args.no_latest:
        forward_args.append("--no-latest")

    if submodule == "soda_ash":
        from stock_cli.soda_ash import main as soda_ash_main

        return soda_ash_main(forward_args)

    if submodule == "pta":
        from stock_cli.pta import main as pta_main

        return pta_main(forward_args)

    if submodule == "tio2":
        from stock_cli.tio2 import main as tio2_main

        return tio2_main(forward_args)

    if submodule == "pvc":
        from stock_cli.pvc import main as pvc_main

        return pvc_main(forward_args)

    logger.error("品种 %s 暂无专用深度爆破管线", submodule)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return run_deep_dive(args)
    except Exception as exc:
        logger.error("执行化工深度爆破管线异常: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
