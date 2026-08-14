"""单元测试: 全市场量化体检聚合引擎 MarketScanEngine 与数据物化。"""

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from stock.analytics.engine import MarketScanEngine
from stock.analytics.models import (
    DailyMarketScanSummary,
    MacroRegime,
    MacroRegimeResult,
    MicroHealthSummary,
    TCRAnalysisResult,
)


def _make_mock_summary(dt: date = date(2026, 8, 12)) -> DailyMarketScanSummary:
    return DailyMarketScanSummary(
        trade_date=dt,
        one_sentence_summary="保持 75% 仓位，优选低估资产。",
        signals=[],
        undervalued_industries=["银行", "非银金融"],
        crowded_industries=["电子"],
        top1_industry="电子",
        top1_tcr=27.6,
        micro_health=MicroHealthSummary(
            margin_ratio=2.62,
            margin_status="温和健康",
            pb_break_ratio=7.55,
            pb_break_status="大面积折价",
            turnover_ratio=4.79,
            turnover_status="情绪适中",
            above_ma60_ratio=43.9,
            ma60_status="修复中",
        ),
        action_items=["- ✅ 保持 65~85% 仓位", "- ❌ 不加杠杆"],
        macro=MacroRegimeResult(
            trade_date=dt,
            regime=MacroRegime.OPPORTUNITY_ZONE,
            regime_desc="结构性战略机会区",
            suggested_equity_exposure=0.75,
            key_drivers=["股债比极高"],
        ),
        tcr=TCRAnalysisResult(
            trade_date=dt,
            total_amount_yi=20000.0,
            top1_industry="电子",
            top1_tcr=27.6,
            crowded_industries=["电子"],
        ),
    )


def test_market_scan_engine_save_and_load(tmp_path: Path) -> None:
    engine = MarketScanEngine()
    summary = _make_mock_summary(date(2026, 8, 12))

    data_file = engine.save_data(summary, base_dir=tmp_path)
    assert data_file.exists()
    assert data_file.name == "data.json"
    assert "2026-08-12" in str(data_file)

    # 验证 JSON 内容
    content = json.loads(data_file.read_text(encoding="utf-8"))
    assert content["top1_industry"] == "电子"
    assert content["micro_health"]["margin_status"] == "温和健康"

    # 验证反序列化加载
    loaded = engine.load_data(date(2026, 8, 12), base_dir=tmp_path)
    assert loaded.trade_date == date(2026, 8, 12)
    assert loaded.one_sentence_summary == summary.one_sentence_summary
    assert loaded.undervalued_industries == ["银行", "非银金融"]
    assert loaded.macro is not None
    assert loaded.macro.regime == MacroRegime.OPPORTUNITY_ZONE


def test_market_scan_engine_get_or_compute_cache(tmp_path: Path) -> None:
    engine = MarketScanEngine()
    summary = _make_mock_summary(date(2026, 8, 12))
    engine.save_data(summary, base_dir=tmp_path)

    # 不传入 recompute 时，应直接命中已物化的 data.json
    loaded_summary, is_cache = engine.get_or_compute(
        target_date=date(2026, 8, 12),
        recompute=False,
        base_dir=tmp_path,
    )
    assert is_cache is True
    assert loaded_summary.top1_tcr == 27.6


def test_market_scan_engine_compute_mocked() -> None:
    engine = MarketScanEngine()
    engine.regime_analyzer = MagicMock()
    engine.regime_analyzer.evaluate_regime.return_value = MacroRegimeResult(
        trade_date=date(2026, 8, 12),
        regime=MacroRegime.OPPORTUNITY_ZONE,
        regime_desc="机会区",
        suggested_equity_exposure=0.75,
    )
    engine.tcr_calc = MagicMock()
    engine.tcr_calc.calculate_daily_tcr.return_value = TCRAnalysisResult(
        trade_date=date(2026, 8, 12),
        total_amount_yi=10000.0,
        top1_industry="801080.SI",
        top1_tcr=25.0,
        crowded_industries=["801080.SI"],
    )
    engine.pbroe_analyzer = MagicMock()
    engine.pbroe_analyzer.analyze_cross_section.return_value = None
    engine.momentum_analyzer = MagicMock()
    engine.momentum_analyzer.calculate_spread.return_value = None
    engine.margin_calc = MagicMock()
    engine.margin_calc.calculate_latest.return_value = None
    engine.breadth_analyzer = MagicMock()
    engine.breadth_analyzer.diagnose_latest.return_value = None
    engine.sentiment_analyzer = MagicMock()
    engine.sentiment_analyzer.diagnose_latest.return_value = None

    summary = engine.compute(target_date=date(2026, 8, 12))
    assert summary.trade_date == date(2026, 8, 12)
    assert summary.top1_industry == "电子"
    assert "电子" in summary.crowded_industries
