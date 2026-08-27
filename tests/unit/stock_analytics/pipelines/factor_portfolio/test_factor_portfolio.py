"""因子组合分数管线测试。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import yaml

from stock_analytics.pipelines.factor_portfolio.config import (
    DEFAULT_CONFIG_PATH,
    FactorPortfolioConfig,
    load_factor_portfolio_config,
)
from stock_analytics.pipelines.factor_portfolio.pipeline import (
    _compute_composite_scores,
    _direction_map,
    _load_factor_source,
    run_factor_portfolio,
)
from stock_analytics.pipelines.factor_research.pipeline import run_factor_research
from stock_core.exceptions import DataValidationError

_N_SYMBOLS = 24
_N_DAYS = 150
_END = date(2024, 6, 28)
_WHITELIST = ("mom_20d", "reversal_5d", "realized_vol_20d")


def _make_base_panel(n_symbols: int = _N_SYMBOLS, n_days: int = _N_DAYS) -> pl.DataFrame:
    """构造含全部 13 个引擎基础列的 mock 日线面板（确定性随机游走价格）。"""
    symbols = [f"60000{i:02d}.SH" for i in range(n_symbols)]
    dates = [_END - timedelta(days=n_days - 1 - i) for i in range(n_days)]
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


def _make_config(tmp_path: Path, **overrides: object) -> tuple[Path, FactorPortfolioConfig]:
    """写临时 YAML 配置并加载（仅写入覆盖字段，其余取默认）。"""
    payload = {"factor_portfolio": {str(key): value for key, value in overrides.items()}}
    path = tmp_path / "factor_portfolio.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path, load_factor_portfolio_config(path)


def _write_research_report(root: Path, verdicts: dict[str, str] | None = None) -> Path:
    """用真实因子评估管线生成准入报告，并按需改写因子判定（默认全部 pass）。

    改写后同步重算 latest 与源运行目录的 manifest 完整性记录，保持产物自洽。
    """
    from stock_analytics.pipelines.artifacts import build_artifact_integrity

    run_factor_research(end_date=_END, output_root=root, panel=_make_base_panel())
    verdicts = verdicts or {}
    targets = list(root.glob("runs/as_of=*/*")) + [root / "latest"]
    for target in targets:
        report_path = target / "factor_research.json"
        manifest_path = target / "manifest.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for factor in report["factors"]:
            factor["verdict"] = verdicts.get(factor["feature_id"], "pass")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        names = [name for name in manifest.get("artifact_files", []) if name != "manifest.json"]
        manifest["artifact_integrity"] = build_artifact_integrity(target, names)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return root


class TestConfig:
    def test_default_config_roundtrip(self) -> None:
        config = load_factor_portfolio_config(DEFAULT_CONFIG_PATH)
        assert config.window_days == 1095
        assert config.rebalance_days == 5
        assert config.top_n == 10
        assert config.min_valid_factors == 3
        assert config.min_trade_days == 200
        assert config.price_col == "close"

    def test_with_artifact_root_override(self, tmp_path: Path) -> None:
        config = load_factor_portfolio_config(DEFAULT_CONFIG_PATH)
        override = str(tmp_path / "overridden")
        updated = config.with_artifact_root(override)
        assert updated.artifact_root == override
        assert config.artifact_root != updated.artifact_root


class TestFactorSource:
    def test_whitelist_overrides_report(self) -> None:
        config = FactorPortfolioConfig(factor_whitelist=_WHITELIST)
        source = _load_factor_source(config, list(_WHITELIST))
        assert source.factor_ids == _WHITELIST

    def test_whitelist_filters_to_existing_columns(self) -> None:
        config = FactorPortfolioConfig(factor_whitelist=("mom_20d", "not_in_wide"))
        source = _load_factor_source(config, ("mom_20d",))
        assert source.factor_ids == ("mom_20d",)

    def test_whitelist_all_missing_raises(self) -> None:
        config = FactorPortfolioConfig(factor_whitelist=("nope_1", "nope_2"))
        with pytest.raises(DataValidationError, match="白名单"):
            _load_factor_source(config, ("mom_20d",))

    def test_report_pass_factors_loaded(self, tmp_path: Path) -> None:
        research_root = _write_research_report(tmp_path / "factor_research")
        config = FactorPortfolioConfig(factor_research_dir=str(research_root))
        source = _load_factor_source(config, ("mom_20d", "reversal_5d", "realized_vol_20d"))
        assert source.factor_ids == ("mom_20d", "reversal_5d", "realized_vol_20d")
        assert source.run_dir.name == "latest"

    def test_missing_report_raises(self, tmp_path: Path) -> None:
        config = FactorPortfolioConfig(factor_research_dir=str(tmp_path / "absent"))
        with pytest.raises(DataValidationError, match="准入报告"):
            _load_factor_source(config, ("mom_20d",))

    def test_no_pass_factor_raises(self, tmp_path: Path) -> None:
        research_root = _write_research_report(
            tmp_path / "factor_research", verdicts=dict.fromkeys(_WHITELIST, "fail")
        )
        config = FactorPortfolioConfig(factor_research_dir=str(research_root))
        with pytest.raises(DataValidationError, match="无通过因子"):
            _load_factor_source(config, list(_WHITELIST))


class TestComputeScores:
    def _wide(self) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "trade_date": [date(2024, 1, 2)] * 3,
                "symbol": ["A", "B", "C"],
                "f1": [1.0, 2.0, 3.0],
                "f2": [3.0, 1.0, 2.0],
            }
        )

    def test_aligned_zscore_composite_matches_hand_calc(self) -> None:
        wide = self._wide()
        scores = _compute_composite_scores(
            wide, ["f1", "f2"], {"f1": "positive", "f2": "negative"}, min_valid_factors=2
        )
        # f1: mean=2, std(ddof=1)=1 -> z=[-1, 0, 1]
        # f2: mean=2, std(ddof=1)=1 -> z=[1, -1, 0]; negative 方向取反 -> [-1, 1, 0]
        # composite = mean([z1, z2]) = [-1, 0.5, 0.5]
        assert scores["composite_score"].to_list() == [-1.0, 0.5, 0.5]
        assert scores["symbol"].to_list() == ["A", "B", "C"]

    def test_degenerate_std_yields_null(self) -> None:
        wide = self._wide().with_columns(pl.lit(2.0).alias("flat"))
        scores = _compute_composite_scores(
            wide, ["f1", "flat"], {"f1": "positive", "flat": "positive"}, min_valid_factors=1
        )
        # flat 截面 std=0 -> z 为 null；每行仅 1 个有效因子，min_valid=1 时取 f1 的 z
        assert scores["composite_score"].to_list() == [-1.0, 0.0, 1.0]

    def test_min_valid_factors_gate(self) -> None:
        wide = self._wide().with_columns(pl.lit(2.0).alias("flat"))
        scores = _compute_composite_scores(
            wide, ["f1", "flat"], {"f1": "positive", "flat": "positive"}, min_valid_factors=2
        )
        assert scores["composite_score"].null_count() == 3

    def test_scores_sorted_by_date_then_symbol(self) -> None:
        wide = pl.DataFrame(
            {
                "trade_date": [date(2024, 1, 3)] * 3 + [date(2024, 1, 2)] * 3,
                "symbol": ["A", "B", "C", "A", "B", "C"],
                "f1": [2.0, 1.0, 3.0, 1.0, 2.0, 3.0],
                "f2": [1.0, 2.0, 3.0, 3.0, 1.0, 2.0],
            }
        )
        scores = _compute_composite_scores(
            wide, ["f1", "f2"], {"f1": "positive", "f2": "negative"}, min_valid_factors=2
        )
        assert scores["trade_date"].to_list() == [date(2024, 1, 2)] * 3 + [date(2024, 1, 3)] * 3

    def test_direction_map_defaults_positive(self) -> None:
        direction_map = _direction_map(("not_registered",))
        assert direction_map == {"not_registered": "positive"}


class TestRunFactorPortfolio:
    def test_end_to_end_with_research_report(self, tmp_path: Path) -> None:
        research_root = _write_research_report(tmp_path / "factor_research")
        config_path, _ = _make_config(tmp_path, min_trade_days=100)
        output_root = tmp_path / "analytics"
        result = run_factor_portfolio(
            end_date=_END,
            config_path=config_path,
            output_root=output_root,
            panel=_make_base_panel(),
            research_dir=research_root,
        )
        assert result.as_of_date == _END
        assert result.summary["factor_pool_size"] > 0
        assert result.summary["factor_research_run"]
        assert result.scores["composite_score"].null_count() < result.scores.height
        assert result.scores.height == len(set(result.scores["symbol"].to_list())) * len(
            set(result.scores["trade_date"].to_list())
        )

        assert result.paths.run_dir.is_dir()
        assert result.paths.manifest.is_file()
        assert result.paths.scores_csv.is_file()
        assert result.paths.summary_json.is_file()
        assert result.paths.latest_dir.is_dir()
        assert (result.paths.latest_dir / "factor_portfolio_scores.csv").is_file()

    def test_end_to_end_with_whitelist(self, tmp_path: Path) -> None:
        config_path, _ = _make_config(
            tmp_path, factor_whitelist=list(_WHITELIST), window_days=200, min_trade_days=100
        )
        result = run_factor_portfolio(
            end_date=_END,
            config_path=config_path,
            output_root=tmp_path / "analytics",
            panel=_make_base_panel(),
        )
        assert result.summary["factor_pool_size"] == len(_WHITELIST)
        assert {f["feature_id"] for f in result.summary["factors"]} == set(_WHITELIST)
        # reversal_5d 与 realized_vol_20d 为 negative 方向，合成时已取反
        assert result.scores["composite_score"].null_count() < result.scores.height

    def test_window_too_short_raises(self, tmp_path: Path) -> None:
        config_path, _ = _make_config(tmp_path, min_trade_days=10_000)
        with pytest.raises(DataValidationError, match="交易日不足"):
            run_factor_portfolio(
                end_date=_END,
                config_path=config_path,
                output_root=tmp_path / "analytics",
                panel=_make_base_panel(),
            )

    def test_no_latest_skip(self, tmp_path: Path) -> None:
        research_root = _write_research_report(tmp_path / "factor_research")
        config_path, _ = _make_config(tmp_path, min_trade_days=100)
        run_factor_portfolio(
            end_date=_END,
            config_path=config_path,
            output_root=tmp_path / "analytics",
            panel=_make_base_panel(),
            research_dir=research_root,
            update_latest=False,
        )
        assert not (tmp_path / "analytics" / "latest").exists()
