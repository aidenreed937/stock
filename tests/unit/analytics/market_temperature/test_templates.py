"""市场温度计报告模板测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock.analytics.market_temperature.config import MarketTemperatureConfig
from stock.analytics.market_temperature.facts import FACT_SCHEMA
from stock.reporting.templates.market_temperature import render_human_report_markdown


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
    assert "- 状态: 可用" in report
    assert "- 系统性风险: 中等偏高" in report
    assert "- 状态: ready" not in report
    assert "## 读法总览" in report
    assert "先定市场环境" in report
    assert "## 系统性风险" in report
    assert "- 风险等级: 中等偏高" in report
    assert "技术面偏热但资金面未同步确认" in report
    assert "| 短线信号 | 技术面 | 67.39 | 最快 |" in report
    assert "| 确认信号 | 资金面 | 47.64 | 较快 |" in report
    assert "| 盈利底座 | 基本面 | 60.70 | 偏慢 |" in report
    assert "财报是低频底座，预告和研报才反映近20日预期变化" in report


def test_human_report_surfaces_quality_divergence_and_followups() -> None:
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
        "composite": {"temperature": 62.53, "status": "ready"},
        "systemic_risk": {"level": "中等偏高", "message": "测试"},
        "dimensions": [
            _dimension("valuation", "估值面", 81.23),
            _dimension("fund_flow", "资金面", 47.64),
            _dimension("sentiment", "情绪面", 56.36),
            _dimension("technical", "技术面", 67.39),
            _dimension("fundamental", "基本面", 60.70),
            _dimension("macro_liquidity", "宏观流动性", 60.57),
        ],
        "short_term": [
            {"window": 5, "temperature": None, "status": "pending"},
            {"window": 10, "temperature": None, "status": "pending"},
        ],
    }
    facts = pl.DataFrame(
        [
            _fact(
                category="data_watermark",
                data_source="tushare",
                dataset="moneyflow",
                value_text="2026-08-13",
                status="ok",
                note="个股资金流，通常晚于行情一个交易日",
            ),
            _fact(
                category="data_watermark",
                data_source="lixinger",
                dataset="cn_m",
                value_text="2026-07-01",
                status="lagging",
                note="M1/M2 月度货币数据",
            ),
            _fact(
                category="data_watermark",
                data_source="lixinger",
                dataset="sw_2021_fs_non_financial",
                value_text="2026-03-31",
                status="lagging",
                note="非金融行业季频财报",
            ),
            _fact(
                category="metric_value",
                dimension="sentiment",
                metric_id="investor_account_temperature",
                value_float=90.77,
                sample_size=130,
                status="ok",
                note="latest_date=2026-07-31",
            ),
            _fact(
                category="metric_value",
                dimension="fund_flow",
                metric_id="margin_balance_growth_20d",
                value_float=-0.0638,
                status="ok",
                note="metric_date=2026-08-13",
            ),
            _fact(
                category="metric_value",
                dimension="fund_flow",
                metric_id="main_money_net_inflow_share",
                value_float=-0.0517,
                status="ok",
                note="metric_date=2026-08-13",
            ),
            _fact(
                category="metric_value",
                dimension="macro_liquidity",
                metric_id="macro_fred_t10y2y_temperature",
                value_float=72.0,
                sample_size=3000,
                status="ok",
                note="FRED T10Y2Y期限利差历史分位，美国期限结构压力日频背景观察",
            ),
            _fact(
                category="metric_value",
                dimension="macro_liquidity",
                metric_id="macro_cnh_20d_change_temperature",
                value_float=68.0,
                sample_size=3000,
                status="ok",
                note=(
                    "Alpha Vantage 离岸人民币USD/CNH 20日变化历史反向分位，人民币贬值压力外部观察"
                ),
            ),
            _fact(
                category="metric_value",
                dimension="macro_liquidity",
                metric_id="macro_external_pressure_temperature",
                value_float=76.67,
                sample_size=3,
                status="ok",
                note="总体外部压力=避险、通胀、需求三类压力可用子项最大值",
            ),
            _fact(
                category="metric_value",
                dimension="macro_liquidity",
                metric_id="macro_safe_haven_pressure_temperature",
                value_float=75.0,
                sample_size=4,
                status="ok",
                note="避险压力=黄金上涨、VIX升温、美股下跌压力可用子项等权平均",
            ),
            _fact(
                category="metric_value",
                dimension="macro_liquidity",
                metric_id="macro_inflation_pressure_temperature",
                value_float=76.67,
                sample_size=3,
                status="ok",
                note="通胀压力=原油上涨、美债收益率上行、美国CPI压力可用子项等权平均",
            ),
            _fact(
                category="metric_value",
                dimension="macro_liquidity",
                metric_id="macro_demand_pressure_temperature",
                value_float=57.5,
                sample_size=4,
                status="ok",
                note="需求压力=铜、原油、美股走弱压力可用子项等权平均",
            ),
        ],
        schema=FACT_SCHEMA,
    )

    report = render_human_report_markdown(
        config=config,
        manifest=manifest,
        scores=scores,
        facts=facts,
    )

    assert "## 数据质量提示" in report
    assert "lixinger.cn_m=lagging(2026-07-01)" not in report
    assert "lixinger.sw_2021_fs_non_financial" not in report
    assert "行业季频财报: 更新偏慢，最新 2026-03-31" in report
    assert "M1/M2 月度货币数据: 更新偏慢，最新 2026-07-01" in report
    assert "行业季频财报 2026-03-31" in report
    assert "## 关键背离" in report
    assert "价格修复的资金确认不足" in report
    assert "慢变量情绪: 月度新增投资者处于高温" in report
    assert "开户热度与日频情绪背离" in report
    assert "估值约束与流动性支撑并存" in report
    assert "基本面分数可用但正式财报偏慢" in report
    assert "## 后续跟踪" in report
    assert "5/10日短线温度仍待接入或待计算" in report
    assert "人民币汇率20日变化温度" in report
    assert "美国期限利差温度" in report
    assert "美国期限结构压力日频背景观察" in report
    assert "## 外部压力提示" in report
    assert "该模块默认 weight=0，不进入六维综合温度" in report
    assert "| 总体外部压力 | 76.67 | 中等偏高 | 压力偏高" in report
    assert "| 避险压力 | 75.00 | 中等偏高 | 压力偏高" in report
    assert "| 需求压力 | 57.50 | 中性 | 压力中性" in report


def test_human_report_can_render_cross_period_driver_change() -> None:
    config = MarketTemperatureConfig(
        schema_version=1,
        title="测试温度计",
        artifact_root=Path("data/analytics/market_temperature"),
        main_window=20,
        short_windows=(5, 10),
        dimensions=(),
        datasets=(),
    )
    previous_manifest = {
        "as_of_date": "2026-06-30",
        "trade_dates": ["2026-06-02", "2026-06-30"],
        "main_window": 20,
        "short_windows": [5, 10],
    }
    current_manifest = {
        "as_of_date": "2026-08-14",
        "trade_dates": ["2026-07-20", "2026-08-14"],
        "main_window": 20,
        "short_windows": [5, 10],
    }
    previous_scores = {
        "composite": {"temperature": 64.41, "status": "ready"},
        "systemic_risk": {"level": "中等偏高", "message": "测试"},
        "dimensions": [
            _dimension("valuation", "估值面", 86.46),
            _dimension("fund_flow", "资金面", 81.87),
            _dimension("sentiment", "情绪面", 74.46),
            _dimension("technical", "技术面", 22.81),
            _dimension("fundamental", "基本面", 58.80),
            _dimension("macro_liquidity", "宏观流动性", 48.89),
        ],
    }
    current_scores = {
        "composite": {"temperature": 62.96, "status": "ready"},
        "systemic_risk": {"level": "中等偏高", "message": "测试"},
        "dimensions": [
            _dimension("valuation", "估值面", 81.23),
            _dimension("fund_flow", "资金面", 47.64),
            _dimension("sentiment", "情绪面", 56.36),
            _dimension("technical", "技术面", 67.39),
            _dimension("fundamental", "基本面", 60.70),
            _dimension("macro_liquidity", "宏观流动性", 63.44),
        ],
    }

    report = render_human_report_markdown(
        config=config,
        manifest=current_manifest,
        scores=current_scores,
        facts=pl.DataFrame(schema=FACT_SCHEMA),
        comparison={
            "previous_manifest": previous_manifest,
            "previous_scores": previous_scores,
        },
    )

    assert "## 跨期驱动变化" in report
    assert "2026-06-30 -> 2026-08-14" in report
    assert "| 综合温度 | 64.41 | 62.96 | -1.45 | 总分接近" in report
    assert "| 资金面 | 81.87 | 47.64 | -34.23 | 明显降温" in report
    assert "| 技术面 | 22.81 | 67.39 | +44.58 | 明显升温" in report


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


def _fact(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "fact_id": "test",
        "category": "",
        "dimension": "",
        "data_source": "",
        "dataset": "",
        "as_of_date": date(2026, 8, 14),
        "window": 0,
        "metric_id": "",
        "value_float": None,
        "value_text": "",
        "unit": "",
        "sample_size": None,
        "source": "test",
        "status": "ok",
        "note": "",
    }
    row.update(overrides)
    return row
