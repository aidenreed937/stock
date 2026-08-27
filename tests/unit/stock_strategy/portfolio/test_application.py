"""因子组合回测应用端到端测试。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import yaml

from stock_analytics.pipelines.artifact_reader import ArtifactUnavailableError
from stock_analytics.pipelines.factor_portfolio.pipeline import run_factor_portfolio
from stock_core.exceptions import DataValidationError
from stock_strategy.portfolio.application import run_backtest_application

_END = date(2024, 6, 28)
_N_DAYS = 150
_N_SYMBOLS = 12
_WHITELIST = ("mom_20d", "reversal_5d", "realized_vol_20d")


def _make_base_panel() -> pl.DataFrame:
    """构造含全部引擎基础列的 mock 日线面板（确定性随机游走价格）。"""
    symbols = [f"60000{i:02d}.SH" for i in range(_N_SYMBOLS)]
    dates = [_END - timedelta(days=_N_DAYS - 1 - i) for i in range(_N_DAYS)]
    rows: list[dict[str, object]] = []
    for symbol_idx, symbol in enumerate(symbols):
        price = 10.0 + symbol_idx * 0.5
        for day_idx, trade_date in enumerate(dates):
            shock = ((symbol_idx * 31 + day_idx * 17) % 101 - 50) / 100 * 0.02
            price = price * (1.0 + shock)
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": price,
                    "high": price * 1.005,
                    "low": price * 0.995,
                    "close": price,
                    "volume": 1_000_000 + day_idx * 100,
                    "amount": 10_000_000.0 + day_idx * 1_000,
                    "pre_close": price / (1.0 + shock),
                    "turnover_rate": 1.5 + (day_idx % 5) * 0.2,
                    "net_mf_amount": 5_000.0 * (1 if (symbol_idx + day_idx) % 2 == 0 else -1),
                    "pe_ttm": 15.0 + (day_idx % 10) * 0.5,
                    "pb": 1.8 + (day_idx % 8) * 0.1,
                }
            )
    return pl.DataFrame(rows)


def _make_portfolio_config(tmp_path: Path, **overrides: object) -> Path:
    """写临时 factor_portfolio YAML 配置（覆盖字段，其余取默认）。"""
    payload = {"factor_portfolio": {str(key): value for key, value in overrides.items()}}
    path = tmp_path / "factor_portfolio.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _make_portfolio_product(tmp_path: Path) -> Path:
    """生成组合分数产物（白名单模式）并返回产物根目录。"""
    config_path = _make_portfolio_config(
        tmp_path,
        factor_whitelist=list(_WHITELIST),
        window_days=200,
        min_trade_days=100,
    )
    portfolio_root = tmp_path / "analytics" / "factor_portfolio"
    run_factor_portfolio(
        end_date=_END,
        config_path=config_path,
        output_root=portfolio_root,
        panel=_make_base_panel(),
    )
    return portfolio_root


class TestBacktestApplication:
    def test_end_to_end(self, tmp_path: Path) -> None:
        portfolio_root = _make_portfolio_product(tmp_path)
        output_root = tmp_path / "analytics" / "factor_backtest"
        result = run_backtest_application(
            portfolio_root=portfolio_root,
            output_root=output_root,
            prices=_make_base_panel().select("symbol", "trade_date", "close"),
            top_n=5,
            rebalance_days=5,
        )
        stats = result.report_json["stats"]
        assert stats["n_trading_days"] > 0
        assert result.report_json["factor_pool"] == list(_WHITELIST)
        assert result.report_json["data_note"]
        assert result.as_of_date == _END

        assert result.paths.run_dir.is_dir()
        assert result.paths.manifest.is_file()
        assert result.paths.report_md.is_file()
        assert result.paths.report_json.is_file()
        assert result.paths.nav_csv.is_file()
        assert result.paths.latest_dir.is_dir()
        assert (result.paths.latest_dir / "factor_backtest.md").is_file()
        assert (result.paths.latest_dir / "factor_backtest_nav.csv").is_file()
        assert "因子组合回测报告" in result.report_markdown

    def test_missing_scores_product_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ArtifactUnavailableError):
            run_backtest_application(
                portfolio_root=tmp_path / "absent",
                output_root=tmp_path / "analytics" / "factor_backtest",
                prices=_make_base_panel().select("symbol", "trade_date", "close"),
            )

    def test_empty_prices_raises(self, tmp_path: Path) -> None:
        portfolio_root = _make_portfolio_product(tmp_path)
        with pytest.raises(DataValidationError, match="价格数据为空"):
            run_backtest_application(
                portfolio_root=portfolio_root,
                output_root=tmp_path / "analytics" / "factor_backtest",
                prices=pl.DataFrame(),
            )

    def test_no_latest_skip(self, tmp_path: Path) -> None:
        portfolio_root = _make_portfolio_product(tmp_path)
        run_backtest_application(
            portfolio_root=portfolio_root,
            output_root=tmp_path / "analytics" / "factor_backtest",
            prices=_make_base_panel().select("symbol", "trade_date", "close"),
            update_latest=False,
        )
        assert not (tmp_path / "analytics" / "factor_backtest" / "latest").exists()
