"""stock.cli.scan 单元测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

from stock.cli.scan import (
    _build_parser,
    format_console_report,
    format_investor_report,
    format_pro_report,
    main,
    run_market_scan,
)


def test_scan_parser() -> None:
    parser = _build_parser()
    args = parser.parse_args(["-d", "2026-08-14", "-s", "000300", "-f", "investor"])
    assert args.target_date == "2026-08-14"
    assert args.symbol == "000300"
    assert args.format == "investor"


def test_format_reports() -> None:
    mock_data = {
        "trade_date": "2026-08-14",
        "macro": {
            "regime": "OPPORTUNITY_ZONE",
            "regime_desc": "战略级大底",
            "suggested_equity_exposure": 0.85,
            "ey_by": {
                "ey_by_ratio": 2.5,
                "pe_ttm": 20.0,
                "bond_yield_10y": 2.0,
                "percentile_10y": 88.0,
            },
            "buffett": {
                "securitization_ratio": 64.0,
                "total_market_cap_yi": 800000.0,
                "gdp_ttm_yi": 1250000.0,
                "percentile_10y": 15.0,
            },
            "key_drivers": ["股债收益比极高"],
        },
        "tcr": {
            "total_amount_yi": 15000.0,
            "top1_industry": "801080.SI",
            "top1_tcr": 18.5,
            "crowded_industries": ["801080.SI"],
        },
        "pbroe": {
            "r_squared": 0.45,
            "undervalued_industries": ["480000", "760000"],
        },
        "momentum": {
            "spread": 25.0,
            "diagnostics": "常态分化",
        },
        "margin": {
            "margin_penetration": 2.1,
            "margin_balance_yi": 14000.0,
            "circ_mv_yi": 650000.0,
            "zone_desc": "杠杆彻底出清底",
        },
        "breadth": {
            "above_ma20_ratio": 65.0,
            "above_ma60_ratio": 50.0,
            "above_ma120_ratio": 45.0,
            "diagnostics": ["市场宽度健康"],
        },
        "sentiment": {
            "pb_break_ratio": 8.5,
            "turnover_ratio": 3.2,
            "diagnostics": ["情绪中性"],
        },
    }

    investor_report = format_investor_report(mock_data)
    assert "A 股量化每日体检报告（投资者通俗版）" in investor_report
    assert "一分钟决策指南" in investor_report
    assert "银行" in investor_report  # 480000 成功映射为银行
    assert "85%" in investor_report

    pro_report = format_pro_report(mock_data)
    assert "A 股量化全景体检专业报告" in pro_report
    assert "OPPORTUNITY_ZONE" in pro_report

    console_report = format_console_report(mock_data)
    assert "A 股量化体检全景摘要" in console_report
    assert "85.0%" in console_report


def test_run_market_scan() -> None:
    with (
        patch("stock.cli.scan.MacroRegimeAnalyzer") as mock_reg_cls,
        patch("stock.cli.scan.TCRCalculator"),
        patch("stock.cli.scan.IndustryPBROEAnalyzer"),
        patch("stock.cli.scan.IndustryMomentumSpreadAnalyzer"),
        patch("stock.cli.scan.MarginPenetrationCalculator"),
        patch("stock.cli.scan.MultiPeriodMarketBreadthAnalyzer"),
        patch("stock.cli.scan.MarketSentimentAnalyzer"),
    ):
        mock_instance = mock_reg_cls.return_value
        mock_res = MagicMock()
        mock_res.trade_date = date(2026, 8, 14)
        mock_res.model_dump.return_value = {"regime": "OPPORTUNITY_ZONE"}
        mock_instance.evaluate_regime.return_value = mock_res

        res = run_market_scan(target_date=date(2026, 8, 14))
        assert res["trade_date"] == "2026-08-14"
        assert res["macro"] == {"regime": "OPPORTUNITY_ZONE"}


def test_main_cli(tmp_path: object) -> None:
    test_file = f"{tmp_path}/report.md"
    with (
        patch("sys.argv", ["scan", "-d", "2026-08-14", "-f", "investor", "-o", test_file]),
        patch("stock.cli.scan.run_market_scan", return_value={"trade_date": "2026-08-14"}),
    ):
        main()

    # 测试 --save 分支
    with (
        patch("sys.argv", ["scan", "-d", "2026-08-14", "--save"]),
        patch("stock.cli.scan.run_market_scan", return_value={"trade_date": "2026-08-14"}),
        patch("pathlib.Path.write_text") as mock_write,
    ):
        main()
        assert mock_write.call_count == 2
