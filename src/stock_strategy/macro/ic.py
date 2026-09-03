"""宏观风控因子时序 Rank IC 验证核心计算（路线 A：单序列时序 IC）。

SOP S3「四件套」之首为 IC 验证：确认候选特征是否为有效因子（整体 + 年度 + 截面）。

宏观双轨制指数（``overheat_index`` / ``panic_index``）及其 ``dim_*`` 维度分是
**单基准时序序列**（非多标的横截面），因此采用「单序列时序 Rank IC」：
对每个因子与基准指数的前瞻收益计算 Spearman 秩相关，作为该因子对后市预测力的证据。

口径：
- 前向收益由 ``stock_analytics.primitives.factor_evaluation.add_forward_returns`` 构造
  （名义收益、百分数、fail-closed：末 h 行无未来数据输出缺失）；
- 整体 IC：全样本池化的 Spearman(因子_t, fwd_ret_{t→t+h})；
- 年度 IC：按自然年分组池化，观察 IC 跨周期是否稳定；
- 当前截面/时窗 IC：最近 ``window_days`` 交易日滚动池化，代表最近信号的即时有效性；
- 任一分组样本不足 / 常数输入时 IC 为 None（fail-closed，不推断）。

词义：本层（``stock_strategy``）是**验证层**——消费 ``stock_analytics`` 产出的特征，
通过 IC / 回测 / 敏感性扫描验证其是否为有效因子（factor）。本层不产生新特征。

配置（``IcConfig`` / ``load_ic_config``）见 ``ic_config``；报告渲染（``build_ic_report``）
见 ``ic_report``。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from stock_analytics.pipelines.macro_risk import load_latest_risk_factors
from stock_analytics.primitives import add_forward_returns
from stock_data.catalog import DataCatalog
from stock_strategy.macro.ic_config import (
    _CORE_FACTOR_COLS,
    _DEFAULT_HORIZONS,
    _DEFAULT_MAX_MIN_SAMPLES,
    _DEFAULT_RISK_ROOT,
    _DEFAULT_TRAILING_WINDOW,
)


def build_ic_panel(
    *,
    catalog: DataCatalog,
    risk_root: Path | str = _DEFAULT_RISK_ROOT,
    benchmark_symbol: str = "000985.CSI",
    horizons: tuple[int, ...] = _DEFAULT_HORIZONS,
    factor_cols: tuple[str, ...] = _CORE_FACTOR_COLS,
) -> pl.DataFrame:
    """构造时序 IC 输入面板：基准收盘轴 × 因子 + 前瞻收益。

    以基准指数日线交易日为轴，左连接风险因子产物面板（含 ``overheat_index`` /
    ``panic_index`` 及各 ``dim_*``；或经 ``factor_cols`` 指定单因子 score 列），
    前向填充因子值，再构造各前瞻收益列。

    Returns:
        ``trade_date / {factor...} / fwd_ret_{h}d`` 面板，按 trade_date 升序；
        仅在产物中存在的因子列会被保留（缺失列跳过，由 IC 计算 fail-closed 兜底）。
    """
    risk_root = Path(risk_root)
    _run_dir, factors, _manifest = load_latest_risk_factors(risk_root)
    if factors.is_empty() or "trade_date" not in factors.columns:
        raise FileNotFoundError(f"宏观风控因子产物缺失: {risk_root}/latest")

    close = catalog.load_bars(
        symbol=benchmark_symbol,
        dataset="index_daily_bar",
        columns=["trade_date", "close"],
    )
    if close.is_empty():
        raise RuntimeError(f"基准指数日线为空: {benchmark_symbol}")

    # 只保留产物中实际存在的因子列（单因子分支可能声明了尚未产出的列）
    existing_cols = [c for c in factor_cols if c in factors.columns]
    factors = (
        factors.select(["trade_date", *existing_cols])
        .with_columns(pl.col("trade_date").cast(pl.Date))
        .sort("trade_date")
    )
    axis = (
        close.select([pl.col("trade_date").cast(pl.Date), pl.col("close").cast(pl.Float64)])
        .unique(subset=["trade_date"], keep="last")
        .sort("trade_date")
    )

    panel = (
        axis.join(factors, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns([pl.col(c).forward_fill() for c in existing_cols])
    )

    # 构造前向收益（单序列无 symbol：整表 shift(-h)，末 h 行 fail-closed 输出缺失）
    panel = add_forward_returns(
        panel.select(["trade_date", *existing_cols, "close"]),
        horizons=horizons,
        price_col="close",
    )
    return panel.select(["trade_date", *existing_cols, *[f"fwd_ret_{h}d" for h in horizons]])


def _pooled_spearman(
    frame: pl.DataFrame, factor: str, fwd_col: str, min_samples: int
) -> float | None:
    """单序列池化 Spearman Rank IC；样本不足/常数输入返回 None（fail-closed）。"""
    sub = frame.drop_nulls([factor, fwd_col])
    if len(sub) < min_samples or sub[factor].n_unique() < 2 or sub[fwd_col].n_unique() < 2:
        return None
    s = sub[factor].to_list()
    r = sub[fwd_col].to_list()
    rho, _ = stats.spearmanr(s, r)
    if rho is None or (isinstance(rho, float) and math.isnan(rho)):
        return None
    return round(float(rho), 3)


def _permutation_test(
    x: np.ndarray, y: np.ndarray, n_permutations: int, rng: np.random.Generator
) -> tuple[float, float, float]:
    """置换检验：固定因子秩，打乱收益秩构建零假设分布。

    返回 ``(p_value, ci_lo, ci_hi)``：
    - p_value：双侧，``(|perm_ic| >= |obs_ic| 次数 + 1) / (n_permutations + 1)``（+1 避免 p=0）；
    - ci_lo / ci_hi：零分布 2.5% / 97.5% 分位，即「运气区间」（95% 中心区间）。
    打乱假设样本可交换；对重叠前瞻收益为近似，用于「运气区间」而非精确检验。
    """
    rx = stats.rankdata(x)
    ry = stats.rankdata(y)
    obs = float(np.corrcoef(rx, ry)[0, 1])
    perms = np.empty(n_permutations)
    for i in range(n_permutations):
        perms[i] = float(np.corrcoef(rx, rng.permutation(ry))[0, 1])
    p_value = (float((np.abs(perms) >= abs(obs)).sum()) + 1.0) / (n_permutations + 1.0)
    ci_lo, ci_hi = np.percentile(perms, [2.5, 97.5])
    return p_value, float(ci_lo), float(ci_hi)


def permutation_ic(
    frame: pl.DataFrame,
    factors: tuple[str, ...],
    horizons: tuple[int, ...],
    min_samples: int = _DEFAULT_MAX_MIN_SAMPLES,
    n_permutations: int = 500,
    seed: int = 42,
    alpha: float = 0.05,
) -> pl.DataFrame:
    """整体时序 IC 的置换检验：给每个 (因子, 窗口) 补「运气区间」与显著性。

    对全样本池化 IC 打乱收益序列 ``n_permutations`` 次（固定 seed 可复现），
    输出真实 IC 在零假设分布中的双侧 p 值与 95% 运气区间（``ci_lo`` / ``ci_hi``），
    ``significant`` 为 ``p_value < alpha``。IC 无法计算（fail-closed）时
    p 值 / 区间 / 显著性均为 None，不推断。

    Returns:
        ``{factor, horizon, ic, n, p_value, ci_lo, ci_hi, significant}`` 表。
    """
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for factor in factors:
        if factor not in frame.columns:
            continue
        for h in horizons:
            fwd = f"fwd_ret_{h}d"
            if fwd not in frame.columns:
                continue
            sub = frame.drop_nulls([factor, fwd])
            n = len(sub)
            ic = _pooled_spearman(frame, factor, fwd, min_samples)
            if ic is None:
                rows.append(
                    {
                        "factor": factor,
                        "horizon": h,
                        "ic": None,
                        "n": n,
                        "p_value": None,
                        "ci_lo": None,
                        "ci_hi": None,
                        "significant": None,
                    }
                )
                continue
            x = sub[factor].to_numpy()
            y = sub[fwd].to_numpy()
            p_value, ci_lo, ci_hi = _permutation_test(x, y, n_permutations, rng)
            rows.append(
                {
                    "factor": factor,
                    "horizon": h,
                    "ic": ic,
                    "n": n,
                    "p_value": round(p_value, 4),
                    "ci_lo": round(ci_lo, 3),
                    "ci_hi": round(ci_hi, 3),
                    "significant": bool(p_value < alpha),
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "factor": pl.String,
            "horizon": pl.Int64,
            "ic": pl.Float64,
            "n": pl.Int64,
            "p_value": pl.Float64,
            "ci_lo": pl.Float64,
            "ci_hi": pl.Float64,
            "significant": pl.Boolean,
        },
    )


def overall_ic(
    frame: pl.DataFrame,
    factors: tuple[str, ...],
    horizons: tuple[int, ...],
    min_samples: int = _DEFAULT_MAX_MIN_SAMPLES,
) -> pl.DataFrame:
    """整体时序 IC 表：`{factor, horizon, ic, n}`（pooled 全样本）。"""
    rows: list[dict[str, object]] = []
    for factor in factors:
        if factor not in frame.columns:
            continue
        for h in horizons:
            fwd = f"fwd_ret_{h}d"
            if fwd not in frame.columns:
                continue
            ic = _pooled_spearman(frame, factor, fwd, min_samples)
            sub = frame.drop_nulls([factor, fwd])
            rows.append({"factor": factor, "horizon": h, "ic": ic, "n": len(sub)})
    return pl.DataFrame(
        rows, schema={"factor": pl.String, "horizon": pl.Int64, "ic": pl.Float64, "n": pl.Int64}
    )


def yearly_ic(
    frame: pl.DataFrame,
    factors: tuple[str, ...],
    horizons: tuple[int, ...],
    min_samples: int = _DEFAULT_MAX_MIN_SAMPLES,
) -> pl.DataFrame:
    """分年度时序 IC 表：`{year, factor, horizon, ic, n}`。"""
    rows: list[dict[str, object]] = []
    for year in sorted(frame["trade_date"].dt.year().unique().to_list()):
        sub = frame.filter(pl.col("trade_date").dt.year() == year)
        for factor in factors:
            if factor not in sub.columns:
                continue
            for h in horizons:
                fwd = f"fwd_ret_{h}d"
                if fwd not in sub.columns:
                    continue
                ic = _pooled_spearman(sub, factor, fwd, min_samples)
                val_sub = sub.drop_nulls([factor, fwd])
                rows.append(
                    {"year": year, "factor": factor, "horizon": h, "ic": ic, "n": len(val_sub)}
                )
    return pl.DataFrame(
        rows,
        schema={
            "year": pl.Int64,
            "factor": pl.String,
            "horizon": pl.Int64,
            "ic": pl.Float64,
            "n": pl.Int64,
        },
    )


def trailing_ic(
    frame: pl.DataFrame,
    factors: tuple[str, ...],
    horizons: tuple[int, ...],
    min_samples: int = _DEFAULT_MAX_MIN_SAMPLES,
    window: int = _DEFAULT_TRAILING_WINDOW,
) -> pl.DataFrame:
    """当前截面/时窗 IC：最近 ``window`` 交易日滚动池化。"""
    if frame.is_empty():
        return pl.DataFrame(
            schema={"factor": pl.String, "horizon": pl.Int64, "ic": pl.Float64, "n": pl.Int64}
        )
    tail = frame.sort("trade_date").tail(window)
    rows: list[dict[str, object]] = []
    for factor in factors:
        if factor not in tail.columns:
            continue
        for h in horizons:
            fwd = f"fwd_ret_{h}d"
            if fwd not in tail.columns:
                continue
            ic = _pooled_spearman(tail, factor, fwd, min_samples)
            val_sub = tail.drop_nulls([factor, fwd])
            rows.append({"factor": factor, "horizon": h, "ic": ic, "n": len(val_sub)})
    return pl.DataFrame(
        rows, schema={"factor": pl.String, "horizon": pl.Int64, "ic": pl.Float64, "n": pl.Int64}
    )


__all__ = [
    "build_ic_panel",
    "overall_ic",
    "permutation_ic",
    "trailing_ic",
    "yearly_ic",
]
