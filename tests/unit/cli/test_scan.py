"""CLI 量化扫描命令与报告格式化单元测试。"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from stock.analytics.models import DailyMarketScanSummary, MicroHealthSummary
from stock.cli.scan import main, run_market_scan
from stock.cli.scan_report import (
    format_console_report,
    format_investor_report,
    format_pro_report,
)


def _make_sample_summary() -> DailyMarketScanSummary:
    return DailyMarketScanSummary(
        trade_date=date(2026, 8, 14),
        one_sentence_summary="保持 85% 仓位，优选低估资产。",
        signals=[],
        undervalued_industries=["银行", "非银金融"],
        crowded_industries=["电子"],
        top1_industry="电子",
        top1_tcr=25.0,
        micro_health=MicroHealthSummary(
            margin_ratio=2.1,
            margin_status="杠杆出清",
            pb_break_ratio=8.5,
            pb_break_status="大面积折价",
            turnover_ratio=3.2,
            turnover_status="情绪中性",
            above_ma60_ratio=50.0,
            ma60_status="修复中",
        ),
        action_items=["- ✅ 保持 75~95% 仓位", "- ❌ 不追高"],
    )


def test_format_reports_with_dict_and_summary() -> None:
    mock_data = {
        "trade_date": "2026-08-14",
        "one_sentence_summary": "保持 85% 仓位，优选低估资产。",
        "signals": [
            {
                "category": "真实估值 (全 A 资产)",
                "name": "全 A 水位 (中证全指 PB)",
                "value_str": "2.16x",
                "percentile_str": "63%",
                "status": "🟡 中枢偏上",
                "description": "估值中枢偏上",
            }
        ],
        "undervalued_industries": ["银行", "非银金融"],
        "crowded_industries": ["电子"],
        "top1_industry": "电子",
        "top1_tcr": 25.0,
        "micro_health": {
            "margin_ratio": 2.1,
            "margin_status": "杠杆出清",
            "pb_break_ratio": 8.5,
            "pb_break_status": "大面积折价",
            "turnover_ratio": 3.2,
            "turnover_status": "情绪中性",
            "above_ma60_ratio": 50.0,
            "ma60_status": "修复中",
        },
        "action_items": ["- ✅ 保持 75~95% 仓位", "- ❌ 不追高"],
        "macro": {
            "trade_date": "2026-08-14",
            "regime": "OPPORTUNITY_ZONE",
            "regime_desc": "战略黄金机会区",
            "suggested_equity_exposure": 0.85,
            "key_drivers": ["股债比极高"],
        },
        "tcr": {
            "trade_date": "2026-08-14",
            "total_amount_yi": 15000.0,
            "top1_industry": "801080.SI",
            "top1_tcr": 18.5,
            "crowded_industries": ["801080.SI"],
        },
    }

    investor_report = format_investor_report(mock_data)
    assert "A 股每日体检" in investor_report
    assert "一句话结论" in investor_report
    assert "四个关键信号" in investor_report
    assert "中证全指" in investor_report
    assert "行业怎么选" in investor_report
    assert "银行" in investor_report
    assert "85%" in investor_report

    pro_report = format_pro_report(mock_data)
    assert "A 股量化全景体检专业报告" in pro_report
    assert "OPPORTUNITY_ZONE" in pro_report

    console_report = format_console_report(mock_data)
    assert "A 股量化体检全景摘要" in console_report
    assert "85.0%" in console_report


def test_run_market_scan() -> None:
    mock_engine = MagicMock()
    mock_summary = _make_sample_summary()
    mock_engine.get_or_compute.return_value = (mock_summary, False)

    res = run_market_scan(target_date=date(2026, 8, 14), engine=mock_engine)
    assert res.trade_date == date(2026, 8, 14)
    assert res.top1_industry == "电子"


def test_main_cli(tmp_path: Path) -> None:
    test_file = tmp_path / "report.md"
    mock_summary = _make_sample_summary()

    with (
        patch("sys.argv", ["scan", "-d", "2026-08-14", "-f", "investor", "-o", str(test_file)]),
        patch("stock.cli.scan.run_market_scan", return_value=mock_summary),
    ):
        main()
    assert test_file.exists()
    assert "A 股每日体检" in test_file.read_text(encoding="utf-8")

    # 测试 --save 分支
    with (
        patch("sys.argv", ["scan", "-d", "2026-08-14", "--save"]),
        patch("stock.cli.scan.run_market_scan", return_value=mock_summary),
        patch.object(Path, "mkdir"),
        patch.object(Path, "write_text") as mock_write,
    ):
        main()
        assert mock_write.called
