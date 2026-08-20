"""期权 Black-Scholes 隐含波动率 (BS-IV) Polars 高性能算子与 Fallback 调度。"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
from polars.plugins import register_plugin_function

if TYPE_CHECKING:
    from polars._typing import IntoExpr

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PLUGIN_LIBRARY_NAMES = (
    "libstock_plugins.dylib",
    "libstock_plugins.so",
    "stock_plugins.dll",
    "stock_plugins.pyd",
    "stock_plugins.so",
)


def _find_plugin_path() -> Path | None:
    """定位已编译的 Rust 动态库，而不是仅检查 Polars API 是否存在。"""
    for build_dir in (_PROJECT_ROOT / "target" / "release", _PROJECT_ROOT / "target" / "debug"):
        for library_name in _PLUGIN_LIBRARY_NAMES:
            candidate = build_dir / library_name
            if candidate.is_file():
                return candidate

    for module_name in ("stock_plugins", "_stock_plugins"):
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, ModuleNotFoundError, ValueError):
            continue
        origin = spec.origin if spec is not None else None
        if origin is None or origin in {"built-in", "frozen"}:
            continue
        candidate = Path(origin)
        if candidate.is_file():
            return candidate
    return None


def _probe_plugin(plugin_path: Path) -> bool:
    """执行一次最小表达式，确认动态库不仅存在且能被当前 Polars 加载。"""
    try:
        expression = register_plugin_function(
            args=[
                pl.lit(0.05),
                pl.lit(1.0),
                pl.lit(1.0),
                pl.lit(0.25),
                pl.lit(0.0),
                pl.lit("C"),
            ],
            plugin_path=plugin_path,
            function_name="fast_bs_implied_volatility",
            is_elementwise=True,
            use_abs_path=True,
        )
        value = pl.DataFrame({"_probe": [0]}).select(expression.alias("_iv"))["_iv"][0]
        return value is not None and math.isfinite(float(value))
    except Exception:
        return False


_PLUGIN_PATH = _find_plugin_path()
_RUST_AVAILABLE: bool = _PLUGIN_PATH is not None and _probe_plugin(_PLUGIN_PATH)


def is_rust_plugin_available() -> bool:
    """返回当前环境是否启用了 Rust 插件加速。"""
    return _RUST_AVAILABLE


def _into_expr(val: IntoExpr) -> pl.Expr:
    if isinstance(val, str):
        return pl.col(val)
    if isinstance(val, pl.Expr):
        return val
    return pl.lit(val)


def _to_float(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise TypeError(f"无法转换为 float: {type(value)}")


def compute_fast_bs_iv(
    settlement: IntoExpr,
    spot: IntoExpr,
    strike: IntoExpr,
    time_years: IntoExpr,
    rate: IntoExpr,
    call_put: IntoExpr,
) -> pl.Expr:
    """计算 Black-Scholes 隐含波动率的 Polars 表达式。

    若编译了 Rust 插件，走底层零拷贝向量化求解；
    若未编译，自动平滑回退到 Python 求解器，保证 100% 兼容。
    """
    args = [
        _into_expr(settlement),
        _into_expr(spot),
        _into_expr(strike),
        _into_expr(time_years),
        _into_expr(rate),
        _into_expr(call_put),
    ]

    if is_rust_plugin_available() and _PLUGIN_PATH is not None:
        try:
            return register_plugin_function(
                args=args,
                plugin_path=_PLUGIN_PATH,
                function_name="fast_bs_implied_volatility",
                is_elementwise=True,
                use_abs_path=True,
            )
        except Exception:
            pass

    # Fallback 到 Python 纯逻辑
    from stock_analytics.marts.option_volatility import settlement_implied_volatility

    fallback_names = (
        "_settlement",
        "_spot",
        "_strike",
        "_time_years",
        "_rate",
        "_call_put",
    )
    fallback_args = [expr.alias(name) for expr, name in zip(args, fallback_names)]

    def _eval_fallback_row(s: dict[str, object] | None) -> float | None:
        if s is None or not isinstance(s, dict):
            return None
        settlement_value = s.get("_settlement")
        spot_value = s.get("_spot")
        strike_value = s.get("_strike")
        time_years_value = s.get("_time_years")
        rate_value = s.get("_rate")
        call_put_value = s.get("_call_put")
        if any(
            value is None
            for value in (
                settlement_value,
                spot_value,
                strike_value,
                time_years_value,
                rate_value,
                call_put_value,
            )
        ):
            return None
        try:
            return settlement_implied_volatility(
                settlement=_to_float(settlement_value),
                spot=_to_float(spot_value),
                strike=_to_float(strike_value),
                time_years=_to_float(time_years_value),
                rate=_to_float(rate_value),
                call_put=str(call_put_value),
            )
        except (TypeError, ValueError):
            return None

    return pl.struct(fallback_args).map_elements(_eval_fallback_row, return_dtype=pl.Float64)
