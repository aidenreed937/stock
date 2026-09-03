"""宏观风控因子 IC 稳定性复审 CLI 入口。

用法示例：
    python -m stock_cli.macro_ic_review                      # 默认复审（60D 年度符号）
    python -m stock_cli.macro_ic_review --horizon 20         # 用 20D 窗口
    python -m stock_cli.macro_ic_review --output-dir PATH    # 指定复审输出目录

首次运行生成基线快照；再次运行会与上次快照对比，输出**新出现漂移**的因子清单。
业务逻辑在 stock_strategy.macro.ic_review，本入口只做参数解析与调用。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from stock_core.utils.logger import setup_logger
from stock_strategy.macro.ic_review import (
    StabilityThresholds,
    build_stability_review,
    load_snapshot,
    report_new_drift,
)

_DEFAULT_IC_DIR = "data/analytics/macro_strategy/ic"
_DEFAULT_REVIEW_DIR = "data/analytics/macro_strategy/ic/review"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="宏观风控因子 IC 稳定性复审（定期复核：年度符号稳定性 + 快照对比）"
    )
    parser.add_argument(
        "--ic-dir", default=_DEFAULT_IC_DIR, help="IC 产物目录（含 ic_yearly.csv 等）"
    )
    parser.add_argument(
        "--output-dir", default=_DEFAULT_REVIEW_DIR, help="复审输出目录（报告 + 快照）"
    )
    parser.add_argument("--horizon", type=int, default=60, help="年度符号窗口（交易日，默认 60）")
    parser.add_argument(
        "--stable-ratio", type=float, default=0.7, help="主导符号占比下限（默认 0.7）"
    )
    parser.add_argument("--max-flips", type=int, default=2, help="符号翻转次数上限（默认 2）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """运行 IC 稳定性复审并输出报告 + 快照 + 新漂移清单。"""
    setup_logger()
    args = _parse_args(argv)
    thresholds = StabilityThresholds(
        horizon=args.horizon,
        stable_ratio=args.stable_ratio,
        max_flips=args.max_flips,
    )
    out = Path(args.output_dir)
    snapshot_path = out / "sign_stability_snapshot.json"

    # 先读上次快照（生成新快照前的历史基线）
    prev_agg, prev_single = load_snapshot(snapshot_path)

    result = build_stability_review(
        ic_dir=Path(args.ic_dir),
        output_dir=out,
        thresholds=thresholds,
    )
    agg = result["agg_stability"]
    single = result["single_stability"]

    print(
        f"聚合信号(12) 稳定: {int(agg['stable'].sum())}/{len(agg)}"
        f" | 单因子(23) 稳定: {int(single['stable'].sum())}/{len(single)}"
    )

    if prev_agg is not None or prev_single is not None:
        drift = report_new_drift(agg, single, prev_agg, prev_single)
        if drift["agg"] or drift["single"]:
            print("⚠️ 新出现漂移（此前稳定 → 本次不稳）：")
            if drift["agg"]:
                print(f"  聚合信号: {', '.join(drift['agg'])}")
            if drift["single"]:
                print(f"  单因子: {', '.join(drift['single'])}")
        else:
            print("✅ 无新出现漂移（与上次快照一致）")
    else:
        print("（首次运行：已生成基线快照，下次运行将对比）")

    print(f"复审报告: {out / 'ic_stability_review.md'}")
    print(f"快照: {snapshot_path}")


if __name__ == "__main__":
    main()
