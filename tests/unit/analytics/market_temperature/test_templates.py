"""市场温度计报告模板测试。"""

from pathlib import Path

import polars as pl

from stock.analytics.market_temperature.config import MarketTemperatureConfig
from stock.analytics.market_temperature.facts import FACT_SCHEMA
from stock.analytics.market_temperature.templates import render_human_report_markdown


def test_human_report_includes_interpretation_priority() -> None:
    config = MarketTemperatureConfig(
        schema_version=1,
        title="测试温度计",
        artifact_root=Path("data/analytics/market_temperature"),
        main_window=20,
        short_windows=(5, 10),
        dimensions=(),
        datasets=(),
    )
    manifest = {
        "as_of_date": "2026-08-14",
        "trade_dates": ["2026-07-20", "2026-08-14"],
        "main_window": 20,
        "short_windows": [5, 10],
    }
    scores = {
        "composite": {"temperature": 61.79, "status": "ready"},
        "systemic_risk": {
            "level": "中等偏高",
            "message": "存在明确风险源，但尚未形成全面风险扩散。",
            "red_flags": ["估值面 81.23 已进入高温，安全边际收缩。"],
            "warnings": ["技术面偏热但资金面未同步确认，价格修复的资金质量需要继续观察。"],
            "offsets": ["情绪面 52.41 未明显过热。"],
        },
        "dimensions": [
            _dimension("valuation", "估值面", 81.23),
            _dimension("fund_flow", "资金面", 47.64),
            _dimension("sentiment", "情绪面", 52.06),
            _dimension("technical", "技术面", 67.39),
            _dimension("fundamental", "基本面", 60.70),
            _dimension("macro_liquidity", "宏观流动性", 59.96),
        ],
    }

    report = render_human_report_markdown(
        config=config,
        manifest=manifest,
        scores=scores,
        facts=pl.DataFrame(schema=FACT_SCHEMA),
    )

    assert "## 解读顺序" in report
    assert "## 系统性风险" in report
    assert "- 风险等级: 中等偏高" in report
    assert "技术面偏热但资金面未同步确认" in report
    assert "| 短线信号 | 技术面 | 67.39 | 最快 |" in report
    assert "| 确认信号 | 资金面 | 47.64 | 较快 |" in report
    assert "| 盈利底座 | 基本面 | 60.70 | 偏慢 |" in report
    assert "财报是低频底座，预告和研报才反映近20日预期变化" in report


def _dimension(dimension_id: str, name: str, temperature: float) -> dict[str, object]:
    return {
        "dimension_id": dimension_id,
        "name": name,
        "weight": 0.15,
        "temperature": temperature,
        "status": "ready",
        "configured_metric_count": 1,
        "metric_count": 1,
        "ok_metric_count": 1,
        "data_issue_count": 0,
        "reason": "test",
    }
