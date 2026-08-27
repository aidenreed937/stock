"""pipelines 共享的日线面板装配工具。

统一基于 ``stock_daily_bar``（主数据集，fail-closed）与 ``daily_basic`` /
``moneyflow``（可选增强，缺失不阻塞）装配 ``FactorEngine`` 基础列面板，
供因子评估（factor_research）与因子组合（factor_portfolio）等业务管线复用。
只做读取与列装配，不含任何业务规则。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger

BAR_COLUMNS = (
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
BASIC_COLUMNS = ("symbol", "trade_date", "turnover_rate", "pe_ttm", "pb")
FLOW_COLUMNS = ("symbol", "trade_date", "net_mf_amount")

OPTIONAL_DATASETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("daily_basic", BASIC_COLUMNS),
    ("moneyflow", FLOW_COLUMNS),
)

#: compute_all_factors 期望的输入基础列全集（引擎校验派生列全集用）。
BASE_COLUMNS = frozenset(
    {
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
    }
)


def load_optional_dataset(
    catalog: Any,
    dataset: str,
    columns: Sequence[str],
    start: date,
    end: date,
) -> pl.DataFrame:
    """读取可选增强数据集；异常或空表时返回空帧（不阻塞业务管线）。"""
    try:
        frame = load_dataset_compat(
            catalog,
            dataset,
            start_date=start,
            end_date=end,
            columns=list(columns),
        )
    except Exception as exc:  # noqa: BLE001 - 可选数据集缺失不阻塞管线
        logger.debug(f"加载可选数据集 {dataset} 失败: {exc}")
        return pl.DataFrame()
    return frame if not frame.is_empty() else pl.DataFrame()


def assemble_panel(bar: pl.DataFrame, basic: pl.DataFrame, flow: pl.DataFrame) -> pl.DataFrame:
    """把日线与可选增强数据装配为引擎基础列面板（缺失列补 null，不推断）。"""
    if bar.is_empty():
        raise DataValidationError("stock_daily_bar 评估窗口内无数据，无法评估因子")
    panel = bar
    for optional in (basic, flow):
        if optional.is_empty():
            continue
        panel = panel.join(optional, on=("symbol", "trade_date"), how="left")
    missing = sorted(BASE_COLUMNS - set(panel.columns))
    if missing:
        panel = panel.with_columns(pl.lit(None, dtype=pl.Float64).alias(col) for col in missing)
    return panel


__all__ = [
    "BAR_COLUMNS",
    "BASE_COLUMNS",
    "BASIC_COLUMNS",
    "FLOW_COLUMNS",
    "OPTIONAL_DATASETS",
    "assemble_panel",
    "load_optional_dataset",
]
