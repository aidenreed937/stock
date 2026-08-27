"""因子准入评估管线测试。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import yaml

from stock_analytics.features.builtin_factor_specs import FACTOR_ENGINE_SPECS
from stock_analytics.pipelines.factor_research.config import (
    DEFAULT_CONFIG_PATH,
    FactorResearchConfig,
    load_factor_research_config,
)
from stock_analytics.pipelines.factor_research.pipeline import (
    _assemble_panel,
    _evaluate_factor,
    _select_factor_pool,
    run_factor_research,
)
from stock_core.exceptions import DataValidationError

_N_SYMBOLS = 24
_N_DAYS = 150
_END = date(2024, 6, 28)


def _make_base_panel(n_symbols: int = _N_SYMBOLS, n_days: int = _N_DAYS) -> pl.DataFrame:
    """构造含全部 13 个引擎基础列的 mock 日线面板（确定性随机游走价格）。"""
    symbols = [f"60000{i:02d}.SH" for i in range(n_symbols)]
    dates = [_END - timedelta(days=n_days - 1 - i) for i in range(n_days)]
    rows: list[dict[str, object]] = []
    for symbol_idx, symbol in enumerate(symbols):
        price = 10.0 + symbol_idx * 0.5
        for day_idx, trade_date in enumerate(dates):
            # 确定性伪随机日收益（±1%），保证前向收益有截面与时序方差
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


def _make_config(tmp_path: Path, **overrides: object) -> tuple[Path, FactorResearchConfig]:
    """写临时 YAML 配置并加载（仅写入覆盖字段，其余取默认）。"""
    payload = {"factor_research": {str(key): value for key, value in overrides.items()}}
    path = tmp_path / "factor_research.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path, load_factor_research_config(path)


class TestConfig:
    def test_default_config_roundtrip(self) -> None:
        config = load_factor_research_config(DEFAULT_CONFIG_PATH)
        assert config.decision_horizon in config.horizons
        assert config.horizons == (1, 5, 20)
        assert config.allowed_units == (
            "ratio",
            "percent",
            "percentile",
            "zscore",
            "score_0_100",
        )

    def test_with_artifact_root_override(self, tmp_path: Path) -> None:
        config = load_factor_research_config(DEFAULT_CONFIG_PATH)
        override = str(tmp_path / "overridden")
        updated = config.with_artifact_root(override)
        assert updated.artifact_root == override
        assert config.artifact_root != updated.artifact_root


class TestAssemblePanel:
    def test_missing_optional_datasets_fill_null_columns(self) -> None:
        bar = _make_base_panel().select(
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "pre_close",
        )
        panel = _assemble_panel(bar, pl.DataFrame(), pl.DataFrame())
        for column in (
            "trade_date",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "pre_close",
            "turnover_rate",
            "net_mf_amount",
            "pe_ttm",
            "pb",
        ):
            assert column in panel.columns, f"缺少基础列 {column}"
        assert panel.height == bar.height

    def test_optional_join_attaches_columns(self) -> None:
        bar = _make_base_panel().select(
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "pre_close",
        )
        basic = _make_base_panel().select("symbol", "trade_date", "turnover_rate", "pe_ttm", "pb")
        panel = _assemble_panel(bar, basic, pl.DataFrame())
        assert panel["turnover_rate"].null_count() == 0

    def test_empty_bar_raises(self) -> None:
        with pytest.raises(DataValidationError):
            _assemble_panel(pl.DataFrame(), pl.DataFrame(), pl.DataFrame())


class TestFactorPool:
    def test_pool_excludes_dimension_units(self) -> None:
        config = load_factor_research_config(DEFAULT_CONFIG_PATH)
        all_factor_ids = tuple(spec.feature_id for spec in FACTOR_ENGINE_SPECS)
        pool = _select_factor_pool(config, all_factor_ids)
        assert "atr_14d" not in pool  # CNY / neutral，不可横截面排序
        assert pool, "因子池不应为空"

    def test_whitelist_overrides_rules(self) -> None:
        config = FactorResearchConfig(factor_whitelist=("atr_14d", "whatever"))
        pool = _select_factor_pool(config, ("atr_14d",))
        assert pool == ["atr_14d"]

    def test_pool_keeps_only_existing_columns(self) -> None:
        config = FactorResearchConfig(factor_whitelist=("mom_20d", "not_in_wide"))
        pool = _select_factor_pool(config, ("mom_20d",))
        assert pool == ["mom_20d"]


class TestEvaluateFactor:
    def _wide_with_forward(self) -> pl.DataFrame:
        base = _make_base_panel()
        wide = base.with_columns(
            (pl.col("close").shift(-5).over("symbol") / pl.col("close") - 1.0).alias("fwd_ret_5d"),
            pl.lit(None, dtype=pl.Float64).alias("fwd_ret_1d"),
            pl.lit(None, dtype=pl.Float64).alias("fwd_ret_20d"),
        )
        return wide

    def test_perfect_predictor_passes(self) -> None:
        wide = self._wide_with_forward()
        # 与 fwd_ret_5d 高度相关但非恒等：截面秩排序每日有微扰，IC 序列有方差
        noise = pl.Series(
            "noise",
            [((i * 9973) % 1000) / 1000 * 0.03 for i in range(wide.height)],
        )
        wide = wide.with_columns((pl.col("fwd_ret_5d") + noise).alias("perfect"))
        config = load_factor_research_config(DEFAULT_CONFIG_PATH)
        result = _evaluate_factor(
            wide,
            "perfect",
            {"perfect": {"unit": "ratio", "direction": "positive"}},
            config,
        )
        assert result["verdict"] == "pass"
        assert result["icir"] is not None and abs(result["icir"]) >= 0.9

    def test_noise_factor_fails(self) -> None:
        wide = self._wide_with_forward()
        wide = wide.with_columns(pl.Series("noise", [float(i % 7) for i in range(wide.height)]))
        config = load_factor_research_config(DEFAULT_CONFIG_PATH)
        result = _evaluate_factor(
            wide,
            "noise",
            {"noise": {"unit": "ratio", "direction": "positive"}},
            config,
        )
        assert result["verdict"] == "fail"
        assert result["reasons"]

    def test_wrong_direction_sign_fails(self) -> None:
        wide = self._wide_with_forward()
        wide = wide.with_columns(pl.col("fwd_ret_5d").alias("fake_pos"))
        config = load_factor_research_config(DEFAULT_CONFIG_PATH)
        result = _evaluate_factor(
            wide,
            "fake_pos",
            {"fake_pos": {"unit": "ratio", "direction": "negative"}},
            config,
        )
        assert result["verdict"] == "fail"

    def test_insufficient_days(self) -> None:
        wide = self._wide_with_forward()
        wide = wide.with_columns(pl.col("fwd_ret_5d").alias("perfect"))
        config = FactorResearchConfig(min_ic_days=10_000)
        result = _evaluate_factor(
            wide,
            "perfect",
            {"perfect": {"unit": "ratio", "direction": "positive"}},
            config,
        )
        assert result["verdict"] == "insufficient"


class TestRunFactorResearch:
    def test_end_to_end_with_injected_panel(self, tmp_path: Path) -> None:
        output_root = tmp_path / "analytics"
        config_path = DEFAULT_CONFIG_PATH
        result = run_factor_research(
            end_date=_END,
            config_path=config_path,
            output_root=output_root,
            panel=_make_base_panel(),
        )
        assert result.as_of_date == _END
        assert result.report_json["factor_pool_size"] > 0
        assert result.report_json["factors"]
        for factor in result.report_json["factors"]:
            assert factor["verdict"] in {"pass", "fail", "insufficient"}
            assert factor["horizon_stats"]

        assert result.paths.run_dir.is_dir()
        assert result.paths.manifest.is_file()
        assert result.paths.report_md.is_file()
        assert result.paths.report_json.is_file()
        assert result.paths.latest_dir.is_dir()
        assert (result.paths.latest_dir / "factor_research.md").is_file()
        assert result.paths.latest_dir / "manifest.json"

    def test_report_content(self, tmp_path: Path) -> None:
        result = run_factor_research(
            end_date=_END,
            output_root=tmp_path / "analytics",
            panel=_make_base_panel(),
        )
        assert "因子准入结论" in result.report_markdown
        assert result.report_json["decision_horizon"] == 5
        assert result.report_json["pass_count"] == sum(
            1 for f in result.report_json["factors"] if f["verdict"] == "pass"
        )

    def test_high_min_ic_days_marks_insufficient(self, tmp_path: Path) -> None:
        config_path, _ = _make_config(tmp_path, min_ic_days=10_000)
        result = run_factor_research(
            end_date=_END,
            config_path=config_path,
            output_root=tmp_path / "analytics",
            panel=_make_base_panel(),
        )
        assert result.report_json["factors"]
        assert all(f["verdict"] == "insufficient" for f in result.report_json["factors"])

    def test_empty_panel_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DataValidationError):
            run_factor_research(
                end_date=_END, output_root=tmp_path / "analytics", panel=pl.DataFrame()
            )

    def test_no_latest_skip(self, tmp_path: Path) -> None:
        run_factor_research(
            end_date=_END,
            output_root=tmp_path / "analytics",
            panel=_make_base_panel(),
            update_latest=False,
        )
        assert not (tmp_path / "analytics" / "latest").exists()
