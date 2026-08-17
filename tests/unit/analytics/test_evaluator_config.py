"""单元测试: 扫描研判阈值配置 (ScanEvaluatorConfig) 与可配置分析器。"""

from datetime import date

from stock.analytics.domains.industry.tcr import TCRCalculator
from stock.analytics.domains.micro.sentiment import MarketSentimentAnalyzer
from stock.analytics.evaluators import (
    _build_eyby_signal,
    build_action_items,
    build_signals,
    evaluate_micro_health,
    evaluate_one_sentence_summary,
)
from stock.analytics.models import (
    AllMarketValuationResult,
    BuffettRatioResult,
    EYBYRatioResult,
    MacroRegime,
    MacroRegimeResult,
    MarketBreadthResult,
    MarketSentimentResult,
    ScanEvaluatorConfig,
    ValuationZone,
)


def _make_mock_macro(
    eyby_pctl: float = 75.0,
    pb_pctl: float = 50.0,
    buf_pctl: float = 40.0,
    exposure: float = 0.8,
) -> MacroRegimeResult:
    dt = date(2026, 8, 14)
    return MacroRegimeResult(
        trade_date=dt,
        regime=MacroRegime.OPPORTUNITY_ZONE,
        regime_desc="机会区",
        suggested_equity_exposure=exposure,
        ey_by=EYBYRatioResult(
            trade_date=dt,
            symbol="000300",
            pe_ttm=12.5,
            earnings_yield=8.0,
            bond_yield_10y=2.15,
            ey_by_ratio=3.72,
            percentile_10y=eyby_pctl,
            zone=ValuationZone.EXTREME_LOW,
            zone_desc="极度低估",
        ),
        all_market=AllMarketValuationResult(
            trade_date=dt,
            pb_ew=1.5,
            pb_percentile_10y=pb_pctl,
            pe_ttm_ew=18.0,
            pe_percentile_10y=50.0,
            zone=ValuationZone.FAIR,
            zone_desc="合理",
        ),
        buffett=BuffettRatioResult(
            trade_date=dt,
            total_market_cap_yi=800000.0,
            gdp_ttm_yi=1200000.0,
            securitization_ratio=66.7,
            percentile_10y=buf_pctl,
            zone=ValuationZone.FAIR,
            zone_desc="合理",
        ),
    )


def test_scan_evaluator_config_defaults() -> None:
    cfg = ScanEvaluatorConfig()
    assert cfg.eyby_high_pctl == 70.0
    assert cfg.eyby_low_pctl == 30.0
    assert cfg.margin_healthy_min == 2.2
    assert cfg.margin_healthy_max == 2.8
    assert cfg.turnover_hot == 6.0


def test_eyby_signal_custom_threshold() -> None:
    macro = _make_mock_macro(eyby_pctl=75.0)

    # 默认 70% 阈值下为高
    item_default = _build_eyby_signal(macro)
    assert item_default is not None
    assert "高" in item_default.status

    # 提高阈值至 80% 后变为中
    custom_cfg = ScanEvaluatorConfig(eyby_high_pctl=80.0)
    item_custom = _build_eyby_signal(macro, config=custom_cfg)
    assert item_custom is not None
    assert "中" in item_custom.status


def test_evaluate_micro_health_custom_threshold() -> None:
    class MockMargin:
        margin_penetration = 2.6

    sent = MarketSentimentResult(
        trade_date=date(2026, 8, 14),
        pb_break_ratio=5.0,
        turnover_ratio=5.0,
    )
    breadth = MarketBreadthResult(
        trade_date=date(2026, 8, 14),
        total_stocks=5000,
        above_ma20_ratio=50.0,
        above_ma60_ratio=50.0,
        above_ma120_ratio=50.0,
    )

    # 默认阈值下: 2.6 是温和健康, 5.0 换手是情绪适中
    res_default = evaluate_micro_health(MockMargin(), sent, breadth)
    assert res_default.margin_status == "温和健康"
    assert res_default.turnover_status == "情绪适中"

    # 自定义阈值: 收紧健康上限到 2.5, 降低换手过热线到 4.5
    custom_cfg = ScanEvaluatorConfig(margin_healthy_max=2.5, turnover_hot=4.5)
    res_custom = evaluate_micro_health(MockMargin(), sent, breadth, config=custom_cfg)
    assert res_custom.margin_status == "杠杆偏热"
    assert res_custom.turnover_status == "交易火热"


def test_evaluate_one_sentence_summary_custom_threshold() -> None:
    macro = _make_mock_macro(eyby_pctl=75.0, buf_pctl=85.0, pb_pctl=65.0)
    summary = evaluate_one_sentence_summary(macro, ["银行"], ["电子"])
    assert "并非全面低估" in summary

    # 提高 buffett 门槛至 90%，触发单纯的建仓期结论
    cfg = ScanEvaluatorConfig(buffett_high_pctl=90.0, pb_high_pctl=70.0)
    summary2 = evaluate_one_sentence_summary(macro, ["银行"], ["电子"], config=cfg)
    assert "高性价比战略建仓期" in summary2


def test_tcr_calculator_custom_threshold() -> None:
    calc = TCRCalculator(default_crowded_threshold=25.0)
    assert calc.default_crowded_threshold == 25.0


def test_sentiment_analyzer_custom_threshold() -> None:
    analyzer = MarketSentimentAnalyzer(turnover_huge_threshold=4.5)
    assert analyzer.turnover_huge_threshold == 4.5


def test_all_signals_custom_thresholds() -> None:
    macro = _make_mock_macro(eyby_pctl=60.0, pb_pctl=80.0, buf_pctl=75.0)
    breadth = MarketBreadthResult(
        trade_date=date(2026, 8, 14),
        total_stocks=5000,
        above_ma20_ratio=85.0,
        above_ma60_ratio=50.0,
        above_ma120_ratio=50.0,
    )
    # 默认阈值下
    signals = build_signals(macro, breadth)
    assert len(signals) == 4
    assert any("偏高" in s.status for s in signals)
    assert any("过热" in s.status for s in signals)

    # 自定义阈值
    cfg = ScanEvaluatorConfig(pb_extreme_high_pctl=85.0, above_ma20_hot=90.0)
    signals_custom = build_signals(macro, breadth, config=cfg)
    assert any("中枢偏上" in s.status for s in signals_custom)
    assert any("健康" in s.status for s in signals_custom)


def test_build_action_items_custom_config() -> None:
    macro = _make_mock_macro(exposure=0.6)
    actions = build_action_items(macro, ["银行"], ["电子"])
    assert any("50~70%" in a for a in actions)

    # 自定义缓冲区间
    cfg = ScanEvaluatorConfig(exposure_buffer_pct=5)
    actions_custom = build_action_items(macro, ["银行"], ["电子"], config=cfg)
    assert any("55~65%" in a for a in actions_custom)
