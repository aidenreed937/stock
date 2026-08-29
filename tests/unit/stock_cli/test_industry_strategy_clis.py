from stock_cli.industry_factors import _build_parser as build_factors_parser
from stock_cli.industry_strategy import _build_parser as build_strategy_parser


def test_industry_factors_cli_parser() -> None:
    parser = build_factors_parser()
    args = parser.parse_args(["--as-of", "2026-08-28", "--output-dir", "data/test"])
    assert args.as_of_date == "2026-08-28"
    assert args.output_dir == "data/test"


def test_industry_strategy_cli_parser() -> None:
    parser = build_strategy_parser()
    args = parser.parse_args(["--strategy", "industry_momentum", "--list"])
    assert args.strategy_name == "industry_momentum"
    assert args.list_strategies is True
