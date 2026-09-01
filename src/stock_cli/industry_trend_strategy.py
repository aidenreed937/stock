"""申万二级行业产业趋势跟踪策略回测 CLI。

策略全部为申万二级方向池（全球共振 6 行业），数据源：
- 基本面面板：``data/curated/mart/industry_l2_panel_daily.parquet``（阶段 1/3 产物，
  含动量/估值分位/量价齐升/方向分）；
- 价格面板：``data/curated/mart/industry_l2_daily.parquet``（方向池 6 行业收盘价）。
回测窗口从 L2 财务黄金表可用起点（2020-05）开始。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger, setup_logger
from stock_strategy.industry.report import (
    compute_metrics,
    load_all_industry_strategy_specs,
)
from stock_strategy.industry.runner import IndustryStrategyRunner
from stock_strategy.pool import create_strategy

_L2_PANEL_MART = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_L2_PRICE_MART = Path("data/curated/mart/industry_l2_daily.parquet")
# L2 财务黄金表 2020Q1 起，实证回测统一从首份 L2 财报发布后开始（公平对比）
_L2_AVAILABLE_FROM = date(2020, 5, 1)
# 全球共振方向池 16 个申万二级行业（去重版：剔除高相关成员 光伏/生物制品/化学制品/塑料，
# 2026-09 纳入消费电子 270500：全球手机/PC 出货 AI 终端需求方向，159732.SZ 纯正对标 gap -0.65%）
_L2_DIRECTION_POOL = (
    "270100",  # 半导体
    "730200",  # 通信设备
    "710100",  # 计算机设备
    "630700",  # 电池
    "630800",  # 电网设备
    "280500",  # 乘用车(汽车)
    "240300",  # 工业金属
    "240400",  # 贵金属
    "370100",  # 化学制药
    "370600",  # 医疗服务
    "220200",  # 化学原料
    "220400",  # 化学纤维
    "220800",  # 农化制品
    "640600",  # 工程机械
    "421100",  # 航运港口
    "270500",  # 消费电子
)


def load_l2_panel() -> pl.DataFrame:
    """加载申万二级方向池基本面面板（industry_l2_panel_daily），对齐实证窗口。"""
    if not _L2_PANEL_MART.exists():
        raise FileNotFoundError(f"缺少二级行业基本面面板: {_L2_PANEL_MART}")
    panel = pl.read_parquet(_L2_PANEL_MART)
    if panel.is_empty() or "trade_date" not in panel.columns:
        raise ValueError("二级行业基本面面板为空或缺少 trade_date 列")
    panel = panel.filter(
        (pl.col("trade_date") >= _L2_AVAILABLE_FROM)
        & (pl.col("industry_code").is_in(_L2_DIRECTION_POOL))
    ).sort(["trade_date", "industry_code"])
    # 宏观恐慌指数（组合防守门 panic_scale 消费；risk_factors 缺失时回退中性 50）
    rf = pl.read_parquet("data/analytics/macro_risk/latest/risk_factors.parquet").select(
        ["trade_date", "panic_index"]
    )
    return panel.join(rf, on="trade_date", how="left")


def load_l2_price_panel() -> pl.DataFrame:
    """加载申万二级方向池历史日收盘价格长表（trade_date x symbol x close）。"""
    if not _L2_PRICE_MART.exists():
        raise FileNotFoundError(f"缺少二级行业行情 Mart: {_L2_PRICE_MART}")
    return (
        pl.read_parquet(_L2_PRICE_MART)
        .filter(pl.col("industry_code").is_in(_L2_DIRECTION_POOL))
        .select(
            [
                pl.col("trade_date").cast(pl.Date),
                pl.col("industry_code").cast(pl.Utf8).alias("symbol"),
                pl.col("close").cast(pl.Float64, strict=False),
            ]
        )
        .filter(pl.col("trade_date") >= _L2_AVAILABLE_FROM)
        .sort(["trade_date", "symbol"])
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="申万二级行业产业趋势跟踪策略运行与回测工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--list",
        dest="list_strategies",
        action="store_true",
        help="列出所有已配置的产业趋势跟踪策略",
    )
    parser.add_argument(
        "--strategy",
        "-s",
        dest="strategy_name",
        default="industry_l2_direction",
        help="指定运行的策略名称",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default="config/strategy/industry_trend_tracking.yaml",
        help="策略配置文件路径",
    )
    return parser


def main() -> None:
    """CLI 主入口。"""
    setup_logger()
    parser = _build_parser()
    args = parser.parse_args()

    cfg_path = Path(args.config_path)
    specs = load_all_industry_strategy_specs(cfg_path)

    if args.list_strategies:
        print("已注册的申万二级行业产业趋势跟踪策略列表:")
        for name, spec in specs.items():
            print(f"  - {name}: {spec.get('description', '')} ({spec.get('strategy_class')})")
        return

    if args.strategy_name not in specs:
        logger.error(f"未找到策略: {args.strategy_name}，可选: {list(specs.keys())}")
        sys.exit(1)

    spec = specs[args.strategy_name]
    cls_name = str(spec.get("strategy_class", ""))

    try:
        panel = load_l2_panel()
        price_panel = load_l2_price_panel()

        friction = spec.get("friction", {})
        comm = float(friction.get("commission_rate", 0.0001))
        slip = float(friction.get("slippage_rate", 0.0005))
        dead = float(friction.get("rebalance_deadband", 0.03))

        kwargs = {
            k: v
            for k, v in spec.items()
            if k not in ("strategy_class", "friction", "description", "name")
        }
        strat = create_strategy(cls_name, **kwargs)
        runner = IndustryStrategyRunner(
            strat,
            strategy_name=args.strategy_name,
            commission_rate=comm,
            slippage_rate=slip,
            rebalance_deadband=dead,
        )

        nav_df = runner.backtest(panel, price_panel)
        metrics = compute_metrics(nav_df)

        print("\n==================================================")
        print(f"策略: {args.strategy_name} ({cls_name}) 回测结果 [申万二级方向池]")
        print("==================================================")
        print(f"累计净值:     {metrics['final_nav']:.4f}")
        print(f"总收益率:     {metrics['total_return']:+.2f}%")
        print(f"年化复合收益: {metrics['cagr']:+.2f}%")
        print(f"最大回撤:     {metrics['max_drawdown']:.2f}%")
        print(f"年化波动率:   {metrics['annual_volatility']:.2f}%")
        print(f"夏普比率:     {metrics['sharpe_ratio']:.2f}")
        print(f"卡玛比率:     {metrics['calmar_ratio']:.2f}")
        print("==================================================\n")

    except Exception as exc:
        logger.exception(f"策略回测失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
