"""A 股全市场量化全景体检与扫描 CLI (stock.cli.scan)。

执行三层量化扫描:
    1. 宏观周期温度计: 股债收益比 (EY/BY)、巴菲特证券化率、四象限周期状态与建议仓位
    2. 中观行业风控雷达: 申万 31 行业成交拥挤度 (TCR)、PB-ROE 性价比残差、动量剪刀差
    3. 微观博弈与情绪特征: 两融渗透率、多周期市场宽度与背离诊断、破净率及换手率特征
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from stock.analytics.industry import (
    IndustryMomentumSpreadAnalyzer,
    IndustryPBROEAnalyzer,
    TCRCalculator,
)
from stock.analytics.macro import MacroRegimeAnalyzer
from stock.analytics.micro import (
    MarginPenetrationCalculator,
    MarketSentimentAnalyzer,
    MultiPeriodMarketBreadthAnalyzer,
)
from stock.cli.scan_report import (
    format_console_report,
    format_investor_report,
    format_pro_report,
)
from stock.data.catalog import DataCatalog
from stock.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="A 股量化宏观/中观/微观全景体检与扫描 CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--date",
        dest="target_date",
        type=str,
        default=None,
        help="指定体检分析基准日期 (YYYY-MM-DD, 默认最新落盘交易日)",
    )
    parser.add_argument(
        "-s",
        "--symbol",
        dest="symbol",
        type=str,
        default="000300",
        help="宏观股债收益比基准指数代码 (默认 000300 沪深300)",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="format",
        choices=["investor", "console", "pro", "json"],
        default="investor",
        help="输出格式 (investor: 投资者通俗版, console: 终端卡片, pro: 专业版, json: 纯JSON)",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        type=str,
        default=None,
        help="将体检报告保存至指定文件路径",
    )
    parser.add_argument(
        "--save",
        dest="auto_save",
        action="store_true",
        help="自动将通俗版与专业版报告归档至 reports/scan/ 目录",
    )
    return parser


def run_market_scan(
    target_date: date | None = None,
    symbol: str = "000300",
) -> dict[str, Any]:
    """执行全流程三层量化体检并返回结构化数据。"""
    # 统一基准日解析：若未显式指定，以库内基础行情最新交易日为统一基准
    if target_date is None:
        try:
            cat = DataCatalog(data_source="tushare")
            df_basic = cat.load_dataset("daily_basic")
            if not df_basic.is_empty():
                max_d = df_basic["trade_date"].max()
                target_date = max_d if isinstance(max_d, date) else date.fromisoformat(str(max_d))
        except Exception as e:
            logger.debug("自动解析全市场最新基准日失败，将交由各分析器按需降级: %s", e)

    # 1. 宏观周期状态机
    regime_analyzer = MacroRegimeAnalyzer()
    regime_res = regime_analyzer.evaluate_regime(target_date=target_date, index_symbol=symbol)

    # 2. 中观行业风控与轮动
    tcr_calc = TCRCalculator()
    tcr_res = tcr_calc.calculate_daily_tcr(target_date=target_date)

    pbroe_analyzer = IndustryPBROEAnalyzer()
    pbroe_res = pbroe_analyzer.analyze_cross_section(target_date=target_date)

    momentum_analyzer = IndustryMomentumSpreadAnalyzer()
    momentum_res = momentum_analyzer.calculate_spread(target_date=target_date)

    # 3. 微观筹码博弈与情绪
    margin_calc = MarginPenetrationCalculator()
    margin_res = margin_calc.calculate_latest(target_date=target_date)

    breadth_analyzer = MultiPeriodMarketBreadthAnalyzer()
    breadth_res = breadth_analyzer.diagnose_latest(target_date=target_date)

    sentiment_analyzer = MarketSentimentAnalyzer()
    sentiment_res = sentiment_analyzer.diagnose_latest(target_date=target_date)

    eval_date = (
        target_date
        or (regime_res.trade_date if regime_res else None)
        or (tcr_res.trade_date if tcr_res else date.today())
    )

    return {
        "trade_date": eval_date.isoformat(),
        "macro": regime_res.model_dump() if regime_res else None,
        "tcr": tcr_res.model_dump() if tcr_res else None,
        "pbroe": pbroe_res.model_dump() if pbroe_res else None,
        "momentum": momentum_res.model_dump() if momentum_res else None,
        "margin": margin_res.model_dump() if margin_res else None,
        "breadth": breadth_res.model_dump() if breadth_res else None,
        "sentiment": sentiment_res.model_dump() if sentiment_res else None,
    }


def _save_scan_reports(data: dict[str, Any], output_text: str, args: argparse.Namespace) -> None:
    """处理报告持久化保存与自动归档逻辑。"""
    target_output = args.output
    if not target_output and args.auto_save:
        dt_compact = str(data.get("trade_date", "")).replace("-", "")
        investor_path = Path(f"reports/scan/market_scan_{dt_compact}.md")
        pro_path = Path(f"reports/scan/market_scan_pro_{dt_compact}.md")
        investor_path.parent.mkdir(parents=True, exist_ok=True)
        investor_path.write_text(format_investor_report(data), encoding="utf-8")
        pro_path.write_text(format_pro_report(data), encoding="utf-8")
        logger.info("体检报告已归档至: %s 与 %s", investor_path.resolve(), pro_path.resolve())
    elif target_output:
        out_path = Path(target_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")
        logger.info("体检报告已保存至: %s", out_path.resolve())


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    target_d = None
    if args.target_date:
        try:
            target_d = date.fromisoformat(args.target_date)
        except ValueError:
            logger.error("日期格式错误，请使用 YYYY-MM-DD 格式: %s", args.target_date)
            sys.exit(1)

    logger.info("开始执行三层量化扫描 (日期: %s, 标的: %s)...", target_d or "最新", args.symbol)
    try:
        data = run_market_scan(target_date=target_d, symbol=args.symbol)
    except Exception as e:
        logger.exception("量化全景扫描执行失败: %s", e)
        sys.exit(1)

    if args.format == "pro":
        output_text = format_pro_report(data)
    elif args.format == "json":
        output_text = json.dumps(data, ensure_ascii=False, indent=2)
    elif args.format == "console":
        output_text = format_console_report(data)
    else:
        output_text = format_investor_report(data)

    sys.stdout.write(output_text + "\n")
    _save_scan_reports(data, output_text, args)


if __name__ == "__main__":
    main()
