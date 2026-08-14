"""全市场量化体检聚合引擎 (Market Scan Engine)。

职责:
    1. 协调宏观周期、中观行业与微观情绪 7 大分析器执行全量量化计算；
    2. 执行业务层研判定性 (一句话结论、宏观四信号定性、微观健康度状态与操作备忘)；
    3. 输出强类型聚合根 DailyMarketScanSummary；
    4. 提供按日目录 (reports/scan/{YYYY-MM-DD}/data.json) 的数据物化持久化与极速反序列化加载。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from stock.analytics.industry.classifier import IndustryClassifier
from stock.analytics.industry.momentum_spread import IndustryMomentumSpreadAnalyzer
from stock.analytics.industry.pb_roe import IndustryPBROEAnalyzer
from stock.analytics.industry.tcr import TCRCalculator
from stock.analytics.macro.regime import MacroRegimeAnalyzer
from stock.analytics.micro.breadth import MultiPeriodMarketBreadthAnalyzer
from stock.analytics.micro.margin import MarginPenetrationCalculator
from stock.analytics.micro.sentiment import MarketSentimentAnalyzer
from stock.analytics.models import (
    DailyMarketScanSummary,
    MacroRegimeResult,
    MacroSignalItem,
    MarketBreadthResult,
    MarketSentimentResult,
    MicroHealthSummary,
)
from stock.utils.logger import logger


def _evaluate_one_sentence_summary(
    macro: MacroRegimeResult | None,
    undervalued: list[str],
    crowded: list[str],
) -> str:
    """构建一句话核心决策结论。"""
    if macro is None:
        return "数据暂缺，建议保持防守仓位并等待数据完整。"

    eyby = macro.ey_by
    all_m = macro.all_market
    buffett = macro.buffett

    eyby_val = eyby.ey_by_ratio if eyby else 0.0
    eyby_pctl = eyby.percentile_10y if eyby else 0.0
    pb_pctl = all_m.pb_percentile_10y if all_m else 50.0
    buf_pctl = buffett.percentile_10y if buffett else 0.0
    exp_pct = macro.suggested_equity_exposure * 100

    uv_str = "/".join(undervalued[:3]) if undervalued else "低估高股息"
    crowd_str = "/".join(crowded[:2]) if crowded else "高位题材"

    if eyby_pctl >= 70.0 and (buf_pctl >= 80.0 or pb_pctl > 60.0):
        return (
            f"股票性价比处于历史高位（沪深300 股债比 {eyby_val:.2f}x，"
            f"10 年 {eyby_pctl:.0f}% 分位），"
            f"但全 A 水位处于 {pb_pctl:.0f}% 中枢偏上，证券化率达 {buf_pctl:.0f}% 高分位——"
            f"便宜主要靠超低国债利率与大盘蓝筹，全 A 并非全面低估。"
            f"**保持 {exp_pct:.0f}% 仓位，只买便宜好货（{uv_str}），回避过热板块（{crowd_str}）。**"
        )
    if eyby_pctl >= 70.0:
        return (
            f"股票资产处于高性价比战略建仓期（股债比 {eyby_val:.2f}x，"
            f"10 年 {eyby_pctl:.0f}% 分位）。"
            f"**保持 {exp_pct:.0f}% 积极仓位，重点配置质优价廉资产（{uv_str}）。**"
        )
    if eyby_pctl < 30.0 or buf_pctl >= 90.0:
        return (
            f"市场估值与杠杆处于偏热风险区。"
            f"**建议将仓位严格控制在 {exp_pct:.0f}% 防御水平，坚决避险。**"
        )
    return (
        f"宏观估值处于常态中枢区间，无系统性风险。"
        f"**建议维持 {exp_pct:.0f}% 标准配置，优选 {uv_str}。**"
    )


def _build_eyby_signal(macro: MacroRegimeResult | None) -> MacroSignalItem | None:
    eyby = macro.ey_by if macro else None
    if not eyby:
        return None
    pctl = eyby.percentile_10y
    if pctl >= 70.0:
        st, desc = "🟢 高", f"历史性机会，仅 {100 - pctl:.0f}% 时间更便宜"
    elif pctl >= 30.0:
        st, desc = "🟡 中", "估值中枢合理，性价比适中"
    else:
        st, desc = "🔴 低", "股票吸引力偏弱，注意防御"
    return MacroSignalItem(
        category="真实估值 (相对债券)",
        name="股债比 EY/BY (沪深300)",
        value_str=f"{eyby.ey_by_ratio:.2f}x",
        percentile_str=f"{pctl:.0f}%",
        status=st,
        description=desc,
    )


def _build_all_m_signal(macro: MacroRegimeResult | None) -> MacroSignalItem | None:
    all_m = macro.all_market if macro else None
    if not all_m:
        return None
    pctl = all_m.pb_percentile_10y
    if pctl >= 75.0:
        st, desc = "🔴 偏高", "全 A 整体估值具备一定溢价"
    elif pctl >= 55.0:
        st, desc = "🟡 中枢偏上", "估值中枢偏上，全 A 非全面低估"
    elif pctl >= 30.0:
        st, desc = "🟢 中枢合理", "资产估值处于历史中枢带"
    else:
        st, desc = "🟢 偏低", "全 A 资产深度折价，安全边际高"
    return MacroSignalItem(
        category="真实估值 (全 A 资产)",
        name="全 A 水位 (中证全指 PB)",
        value_str=f"{all_m.pb_ew:.2f}x",
        percentile_str=f"{pctl:.0f}%",
        status=st,
        description=desc,
    )


def _build_buffett_signal(macro: MacroRegimeResult | None) -> MacroSignalItem | None:
    buf = macro.buffett if macro else None
    if not buf:
        return None
    pctl = buf.percentile_10y
    if pctl >= 85.0:
        st, desc = "🟡 偏高", "规模高位，受超低利率与扩容推升"
    elif pctl >= 70.0:
        st, desc = "🟡 中偏高", "总市值相对 GDP 具备一定扩张"
    elif pctl >= 30.0:
        st, desc = "🟢 合理", "总市值与经济总量基本匹配"
    else:
        st, desc = "🟢 极低", "全市场总市值大幅折价"
    return MacroSignalItem(
        category="宏观规模水位",
        name="证券化率 (市值/GDP)",
        value_str=f"{buf.securitization_ratio:.1f}%",
        percentile_str=f"{pctl:.0f}%",
        status=st,
        description=desc,
    )


def _build_breadth_signal(breadth: MarketBreadthResult | None) -> MacroSignalItem | None:
    if not breadth:
        return None
    r20 = breadth.above_ma20_ratio
    if r20 > 80.0:
        st, desc = "🔴 过热", "短线亢奋，勿追高"
    elif r20 >= 40.0:
        st, desc = "🟢 健康", "短线处于常态健康带"
    else:
        st, desc = "⚪ 冰点", "短线悲观冰点，酝酿反弹"
    return MacroSignalItem(
        category="短线情绪",
        name="站上 20 日线比例",
        value_str=f"{r20:.0f}%",
        percentile_str="—",
        status=st,
        description=desc,
    )


def _build_signals(
    macro: MacroRegimeResult | None,
    breadth: MarketBreadthResult | None,
) -> list[MacroSignalItem]:
    """生成宏观四维信号列表。"""
    signals: list[MacroSignalItem] = []
    for item in [
        _build_eyby_signal(macro),
        _build_all_m_signal(macro),
        _build_buffett_signal(macro),
        _build_breadth_signal(breadth),
    ]:
        if item is not None:
            signals.append(item)
    return signals


def _evaluate_micro_health(
    margin_res: Any,
    sentiment_res: MarketSentimentResult | None,
    breadth_res: MarketBreadthResult | None,
) -> MicroHealthSummary:
    """评估微观健康度状态。"""
    m_ratio = margin_res.margin_penetration if margin_res else 0.0
    m_desc = "温和健康" if 2.2 <= m_ratio <= 2.8 else ("杠杆出清" if m_ratio < 2.2 else "杠杆偏热")

    pb_break = sentiment_res.pb_break_ratio if sentiment_res else 0.0
    pb_desc = "大面积折价" if pb_break > 7.0 else ("部分折价" if pb_break >= 4.0 else "常态区间")

    turnover = sentiment_res.turnover_ratio if sentiment_res else 0.0
    to_desc = "交易火热" if turnover > 6.0 else ("情绪适中" if turnover >= 3.0 else "交投低迷")

    r60 = breadth_res.above_ma60_ratio if breadth_res else 0.0
    r60_desc = "多头走强" if r60 > 60.0 else ("修复中" if r60 >= 30.0 else "弱势寻底")

    return MicroHealthSummary(
        margin_ratio=round(m_ratio, 2),
        margin_status=m_desc,
        pb_break_ratio=round(pb_break, 2),
        pb_break_status=pb_desc,
        turnover_ratio=round(turnover, 2),
        turnover_status=to_desc,
        above_ma60_ratio=round(r60, 1),
        ma60_status=r60_desc,
    )


def _build_action_items(
    macro: MacroRegimeResult | None,
    undervalued: list[str],
    crowded: list[str],
) -> list[str]:
    """生成精简操作备忘清单。"""
    exp_pct = (macro.suggested_equity_exposure if macro else 0.7) * 100
    exp_min = max(20, int(exp_pct - 10))
    exp_max = min(95, int(exp_pct + 10))

    uv_text = "、".join(undervalued[:3]) if undervalued else "低估核心资产"
    avoid_line = (
        f"- ❌ 不追{'/'.join(crowded)}等成交占比 >20% 的板块"
        if crowded
        else "- ❌ 不追短线涨幅过大的过热题材"
    )

    return [
        f"- ✅ 保持 {exp_min}~{exp_max}% 仓位，定投低估宽基/高股息",
        f"- ✅ 回踩加仓{uv_text}",
        avoid_line,
        "- ❌ 不加高倍杠杆",
    ]


class MarketScanEngine:
    """全市场每日量化体检聚合引擎。"""

    def __init__(self) -> None:
        """初始化聚合引擎与各领域分析器。"""
        self.classifier = IndustryClassifier()
        self.regime_analyzer = MacroRegimeAnalyzer()
        self.tcr_calc = TCRCalculator()
        self.pbroe_analyzer = IndustryPBROEAnalyzer()
        self.momentum_analyzer = IndustryMomentumSpreadAnalyzer()
        self.margin_calc = MarginPenetrationCalculator()
        self.breadth_analyzer = MultiPeriodMarketBreadthAnalyzer()
        self.sentiment_analyzer = MarketSentimentAnalyzer()

    def compute(
        self,
        target_date: date | None = None,
        index_symbol: str = "000300",
    ) -> DailyMarketScanSummary:
        """执行各子系统全量计算并合成研判结论。"""
        regime_res = self.regime_analyzer.evaluate_regime(
            target_date=target_date, index_symbol=index_symbol
        )
        tcr_res = self.tcr_calc.calculate_daily_tcr(target_date=target_date)
        pbroe_res = self.pbroe_analyzer.analyze_cross_section(target_date=target_date)
        momentum_res = self.momentum_analyzer.calculate_spread(target_date=target_date)
        margin_res = self.margin_calc.calculate_latest(target_date=target_date)
        breadth_res = self.breadth_analyzer.diagnose_latest(target_date=target_date)
        sentiment_res = self.sentiment_analyzer.diagnose_latest(target_date=target_date)

        eval_date = (
            target_date
            or (regime_res.trade_date if regime_res else None)
            or (tcr_res.trade_date if tcr_res else date.today())
        )

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

        one_sentence = _evaluate_one_sentence_summary(regime_res, undervalued, crowded)
        signals = _build_signals(regime_res, breadth_res)
        micro_health = _evaluate_micro_health(margin_res, sentiment_res, breadth_res)
        action_items = _build_action_items(regime_res, undervalued, crowded)

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
            macro=regime_res,
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
