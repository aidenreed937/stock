"""宏观风控产物的完整性检测与维度退化披露。

从 ``pipeline`` 拆出（类规模 / 文件行数门禁）：本模块只回答两个问题——
as_of 日双轨核心字段是否齐全、非双轨成分是否退化；不参与因子计算与产物落盘。
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl

from stock_core.constants import (
    MACRO_RISK_DEGRADED_MONITORS,
    MACRO_RISK_DEGRADED_ZERO_RUN_DAYS,
)

logger = logging.getLogger(__name__)

# 完整性检测字段：双轨指数本身 + 其构成的 6 个维度
# （overheat: valuation/leverage/fear/flow/crowding；panic: breadth/fear/flow）
_COMPLETENESS_FIELDS: tuple[str, ...] = (
    "overheat_index",
    "panic_index",
    "dim_valuation",
    "dim_leverage",
    "dim_fear",
    "dim_flow",
    "dim_crowding",
    "dim_breadth",
)


def _trailing_zero_run(frame: pl.DataFrame, column: str) -> int:
    """统计目标列截至末行的连续 0 值天数（空值即中断）。"""
    if column not in frame.columns:
        return 0
    run = 0
    for value in reversed(frame[column].to_list()):
        if value is None:
            break
        try:
            if float(value) != 0.0:
                break
        except (TypeError, ValueError):
            break
        run += 1
    return run


def _detect_degraded_dimensions(
    row_dict: dict[str, object],
    frame: pl.DataFrame | None,
) -> list[dict[str, object]]:
    """检出非双轨成分、但研报必须披露的退化维度。

    这类维度不进 overheat/panic，``complete`` 检查也不含它；上游缺数会被打分
    打成 0.0（而非 null），若静默会被后续引用当成真实读数。

    Args:
        row_dict: as_of 日因子快照。
        frame: 因子面板（用于判定连续 0 天；None 时只判缺失）。

    Returns:
        退化维度列表，元素含 field/source_score/value/zero_run/state。
    """
    degraded: list[dict[str, object]] = []
    for dim_field, column in MACRO_RISK_DEGRADED_MONITORS.items():
        value = row_dict.get(dim_field)
        zero_run = _trailing_zero_run(frame, column) if frame is not None else 0
        if value is None:
            state = "missing"
        elif zero_run >= MACRO_RISK_DEGRADED_ZERO_RUN_DAYS:
            state = "stuck_zero"
        else:
            continue
        degraded.append(
            {
                "field": dim_field,
                "source_score": column,
                "value": value,
                "zero_run": zero_run,
                "state": state,
            }
        )
    return degraded


def _check_data_completeness(
    row_dict: dict[str, object],
    frame: pl.DataFrame | None = None,
) -> dict[str, object]:
    """检测 as_of 日核心字段缺失，返回完整性报告。

    缺失可能来自上游黄金表/Mart 缺数或已知口径缺口（如估值冷启动期 dim_valuation
    为 null）；调用方结合业务判断是「已知缺口」还是「异常缺失」。

    ``degraded_dimensions`` 披露非双轨成分的退化维度（缺失/被上游打成 0.0），
    不参与 ``complete`` 判定，但必须随 manifest 一起暴露，避免坏值静默通过。
    """
    missing = [k for k in _COMPLETENESS_FIELDS if not isinstance(row_dict.get(k), int | float)]
    return {
        "checked_fields": list(_COMPLETENESS_FIELDS),
        "total": len(_COMPLETENESS_FIELDS),
        "available": len(_COMPLETENESS_FIELDS) - len(missing),
        "missing_fields": missing,
        "complete": not missing,
        "degraded_dimensions": _detect_degraded_dimensions(row_dict, frame),
    }


def _log_completeness_warnings(completeness: dict[str, object], as_of: date) -> None:
    """完整性/退化告警的统一出口，避免在管线主流程内堆砌日志分支。"""
    missing = completeness.get("missing_fields") or []
    if missing:
        logger.warning(
            "宏观风控产物数据不完整 (as_of=%s)：缺失字段 %s（完整度 %s/%s），"
            "可能来自上游缺数或已知口径缺口（如估值冷启动），引用前需核验",
            as_of,
            missing,
            completeness.get("available"),
            completeness.get("total"),
        )
    degraded = completeness.get("degraded_dimensions") or []
    if degraded:
        logger.warning(
            "宏观风控产物维度退化 (as_of=%s)：%s；该类维度不进双轨指数，但引用时必须披露",
            as_of,
            degraded,
        )


__all__ = ["_check_data_completeness", "_log_completeness_warnings"]
