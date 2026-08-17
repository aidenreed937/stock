"""全市场量化体检聚合引擎 (Market Scan Engine)。

职责:
    1. 协调中观行业与微观情绪各分析器执行全量量化计算；
    2. 执行业务层研判定性 (一句话结论、微观健康度状态与操作备忘)；
    3. 输出强类型聚合根 DailyMarketScanSummary；
    4. 提供按日目录 (reports/scan/{YYYY-MM-DD}/data.json) 的数据物化持久化与极速反序列化加载。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from stock.analytics.domains.industry.classifier import IndustryClassifier
from stock.analytics.domains.industry.momentum_spread import IndustryMomentumSpreadAnalyzer
from stock.analytics.domains.industry.pb_roe import IndustryPBROEAnalyzer
from stock.analytics.domains.industry.tcr import TCRCalculator
from stock.analytics.domains.micro.breadth import MultiPeriodMarketBreadthAnalyzer
from stock.analytics.domains.micro.margin import MarginPenetrationCalculator
from stock.analytics.domains.micro.sentiment import MarketSentimentAnalyzer
from stock.analytics.evaluators import (
    build_action_items,
    build_signals,
    evaluate_micro_health,
    evaluate_one_sentence_summary,
)
from stock.analytics.models import DailyMarketScanSummary, ScanEvaluatorConfig
from stock.data.catalog import DataCatalog
from stock.utils.logger import logger


class MarketScanEngine:
    """全市场每日量化体检聚合引擎。"""

    def __init__(
        self,
        catalog: DataCatalog | None = None,
        config: ScanEvaluatorConfig | None = None,
    ) -> None:
        """初始化聚合引擎与各领域分析器。"""
        self.catalog = catalog or DataCatalog(data_source="tushare")
        self.config = config or ScanEvaluatorConfig()
        self.classifier = IndustryClassifier()
        self.tcr_calc = TCRCalculator(catalog=self.catalog)
        self.pbroe_analyzer = IndustryPBROEAnalyzer()
        self.momentum_analyzer = IndustryMomentumSpreadAnalyzer(catalog=self.catalog)
        self.margin_calc = MarginPenetrationCalculator(catalog=self.catalog)
        self.breadth_analyzer = MultiPeriodMarketBreadthAnalyzer(catalog=self.catalog)
        self.sentiment_analyzer = MarketSentimentAnalyzer(
            catalog=self.catalog,
            pb_break_warning=self.config.pb_break_warning,
            pb_break_moderate=self.config.pb_break_moderate,
            turnover_hot=self.config.turnover_hot,
            turnover_moderate=self.config.turnover_moderate,
        )

    def compute(
        self,
        target_date: date | None = None,
        index_symbol: str = "000300",
    ) -> DailyMarketScanSummary:
        """执行各子系统全量计算并合成研判结论 (支持共享内存预加载与多核并行)。"""
        # 1. 预加载共享的 daily_basic (单次读取，供两融、情绪等模块复用)
        df_daily_basic = self.catalog.load_dataset("daily_basic", end_date=target_date)

        # 2. 多核并发执行独立分析器
        with ThreadPoolExecutor(max_workers=6) as executor:
            f_tcr = executor.submit(self.tcr_calc.calculate_daily_tcr, target_date=target_date)
            f_pbroe = executor.submit(
                self.pbroe_analyzer.analyze_cross_section, target_date=target_date
            )
            f_mom = executor.submit(
                self.momentum_analyzer.calculate_spread, target_date=target_date
            )
            f_margin = executor.submit(
                self.margin_calc.calculate_latest,
                target_date=target_date,
                daily_basic_df=df_daily_basic,
            )
            f_breadth = executor.submit(
                self.breadth_analyzer.diagnose_latest, target_date=target_date
            )
            f_sent = executor.submit(
                self.sentiment_analyzer.diagnose_latest,
                target_date=target_date,
                daily_basic_df=df_daily_basic,
            )

            tcr_res = f_tcr.result()
            pbroe_res = f_pbroe.result()
            momentum_res = f_mom.result()
            margin_res = f_margin.result()
            breadth_res = f_breadth.result()
            sentiment_res = f_sent.result()

        result_dates = [
            getattr(result, "trade_date", None)
            for result in (
                tcr_res,
                pbroe_res,
                momentum_res,
                margin_res,
                breadth_res,
                sentiment_res,
            )
        ]
        actual_dates = [value for value in result_dates if isinstance(value, date)]
        eval_date = max(actual_dates) if actual_dates else (target_date or date.today())

        undervalued_raw = pbroe_res.undervalued_industries if pbroe_res else []
        undervalued = [self.classifier.resolve_name(c) for c in undervalued_raw]

        crowded_raw = tcr_res.crowded_industries if tcr_res else []
        crowded = [self.classifier.resolve_name(c) for c in crowded_raw]

        top1_ind = (
            self.classifier.resolve_name(tcr_res.top1_industry)
            if (tcr_res and tcr_res.top1_industry)
            else "无"
        )
        top1_tcr = tcr_res.top1_tcr if tcr_res else 0.0

        one_sentence = evaluate_one_sentence_summary(None, undervalued, crowded, self.config)
        signals = build_signals(None, breadth_res, self.config)
        micro_health = evaluate_micro_health(margin_res, sentiment_res, breadth_res, self.config)
        action_items = build_action_items(None, undervalued, crowded, self.config)

        return DailyMarketScanSummary(
            trade_date=eval_date,
            one_sentence_summary=one_sentence,
            signals=signals,
            undervalued_industries=undervalued,
            crowded_industries=crowded,
            top1_industry=top1_ind,
            top1_tcr=top1_tcr,
            micro_health=micro_health,
            action_items=action_items,
            macro=None,
            tcr=tcr_res,
            pbroe=pbroe_res,
            momentum=momentum_res,
            margin=margin_res,
            breadth=breadth_res,
            sentiment=sentiment_res,
        )

    def save_data(
        self,
        summary: DailyMarketScanSummary,
        base_dir: Path | str = "reports/scan",
    ) -> Path:
        """将扫描强类型数据物化持久化为 reports/scan/{date}/data.json。"""
        dt_str = summary.trade_date.strftime("%Y-%m-%d")
        target_dir = Path(base_dir) / dt_str
        target_dir.mkdir(parents=True, exist_ok=True)
        data_file = target_dir / "data.json"

        # 写入格式化 JSON
        data_file.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
        return data_file

    def load_data(
        self,
        date_or_path: date | str | Path,
        base_dir: Path | str = "reports/scan",
    ) -> DailyMarketScanSummary:
        """从已物化的 data.json 文件反序列化加载。"""
        if isinstance(date_or_path, Path) and date_or_path.is_file():
            target_file = date_or_path
        elif isinstance(date_or_path, str) and (
            date_or_path.endswith(".json") or "/" in date_or_path
        ):
            target_file = Path(date_or_path)
        else:
            dt_str = (
                date_or_path.strftime("%Y-%m-%d")
                if isinstance(date_or_path, date)
                else str(date_or_path).replace("_", "-")
            )
            target_file = Path(base_dir) / dt_str / "data.json"

        if not target_file.exists():
            raise FileNotFoundError(f"未找到指定的扫描数据文件: {target_file}")

        content = target_file.read_text(encoding="utf-8")
        data_dict = json.loads(content)
        return DailyMarketScanSummary.model_validate(data_dict)

    def get_or_compute(
        self,
        target_date: date | None = None,
        index_symbol: str = "000300",
        *,
        recompute: bool = False,
        base_dir: Path | str = "reports/scan",
    ) -> tuple[DailyMarketScanSummary, bool]:
        """获取或计算扫描数据 (返回 (summary, is_from_cache))。"""
        if not recompute and target_date is not None:
            dt_str = target_date.strftime("%Y-%m-%d")
            data_file = Path(base_dir) / dt_str / "data.json"
            if data_file.exists():
                try:
                    summary = self.load_data(data_file)
                    return summary, True
                except Exception as e:
                    logger.debug("反序列化本地数据文件失败，将回退至重新计算: %s", e)

        summary = self.compute(target_date=target_date, index_symbol=index_symbol)
        return summary, False
