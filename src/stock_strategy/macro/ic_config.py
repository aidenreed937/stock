"""宏观风控因子时序 Rank IC 验证的配置层（IcConfig 与加载）。

从 ``config/strategy/macro_risk.yaml`` 的 ``ic`` 段读取验证参数，
缺省回退到模块默认值，避免研究参数在代码里散落硬编码。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path("config/strategy/macro_risk.yaml")
_DEFAULT_RISK_ROOT = Path("data/analytics/macro_risk")
_DEFAULT_OUTPUT_DIR = Path("data/analytics/macro_strategy/ic")

# 时序 IC 需要的因子列白名单（来自 config/analytics/macro_risk.yaml 产物的核心列）
_CORE_FACTOR_COLS = (
    "overheat_index",
    "panic_index",
    "dim_valuation",
    "dim_leverage",
    "dim_flow",
    "dim_breadth",
    "dim_fear",
    "dim_euphoria",
    "dim_crowding",
    "dim_corporate",
    "dim_cross_asset",
    "dim_smart_money",
)

_DEFAULT_HORIZONS = (5, 20, 60)
_DEFAULT_MAX_MIN_SAMPLES = 30
_DEFAULT_TRAILING_WINDOW = 756  # 约 3 年，作为「当前截面/时窗」口径


@dataclass(frozen=True)
class IcConfig:
    """IC 验证配置（可从 ``config/strategy/macro_risk.yaml`` 的 ``ic`` 段读取）。"""

    factors: tuple[str, ...] = _CORE_FACTOR_COLS
    horizons: tuple[int, ...] = _DEFAULT_HORIZONS
    min_samples: int = _DEFAULT_MAX_MIN_SAMPLES
    trailing_window: int = _DEFAULT_TRAILING_WINDOW
    benchmark_symbol: str = "000985.CSI"
    single_factors: tuple[str, ...] = ()
    n_permutations: int = 500
    seed: int = 42
    alpha: float = 0.05


def load_ic_config(config_path: Path | str = _DEFAULT_CONFIG_PATH) -> IcConfig:
    """读取 IC 验证配置，缺省回退到模块默认值（不为研究参数在代码里散落硬编码）。"""
    defaults = IcConfig()
    try:
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            ic = payload.get("ic", {})
            if isinstance(ic, dict):
                factors = tuple(ic.get("factors", defaults.factors))
                horizons = tuple(int(h) for h in ic.get("horizons", defaults.horizons))
                single_factors = tuple(ic.get("single_factors", ()))
                return IcConfig(
                    factors=factors,
                    horizons=horizons,
                    min_samples=int(ic.get("min_samples", defaults.min_samples)),
                    trailing_window=int(ic.get("trailing_window", defaults.trailing_window)),
                    benchmark_symbol=str(ic.get("benchmark_symbol", defaults.benchmark_symbol)),
                    single_factors=single_factors,
                    n_permutations=int(ic.get("n_permutations", defaults.n_permutations)),
                    seed=int(ic.get("seed", defaults.seed)),
                    alpha=float(ic.get("alpha", defaults.alpha)),
                )
    except (OSError, ValueError, TypeError):
        pass
    return defaults


__all__ = ["IcConfig", "load_ic_config"]
