"""从领域 Mart 生成不参与主评分的观察事实。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, cast

import polars as pl

from stock_analytics.features.store import FeatureStore

_OBSERVATION_SPECS: tuple[dict[str, str], ...] = (
    {
        "mart": "convertible_bond_daily",
        "date_column": "trade_date",
        "dimension": "sentiment",
        "metric_id": "cb_price_median_observation",
        "value_column": "cb_price_median",
        "unit": "CNY/bond",
        "note": "可转债全市场价格中位数，仅作股债混合风险偏好观察，不进入六维主温度",
    },
    {
        "mart": "convertible_bond_daily",
        "date_column": "trade_date",
        "dimension": "sentiment",
        "metric_id": "cb_conversion_premium_observation",
        "value_column": "cb_conversion_premium_median",
        "unit": "percent",
        "note": "可转债转股溢价率中位数，仅作股性/债性切换观察，不进入六维主温度",
    },
    {
        "mart": "convertible_bond_daily",
        "date_column": "trade_date",
        "dimension": "sentiment",
        "metric_id": "cb_low_price_share_observation",
        "value_column": "cb_low_price_count",
        "unit": "ratio",
        "note": "可转债低于低价阈值的数量占有效样本比例，不进入六维主温度",
    },
    {
        "mart": "insider_activity_daily",
        "date_column": "announcement_date",
        "dimension": "fund_flow",
        "metric_id": "insider_net_buy_amount_observation",
        "value_column": "insider_net_buy_amount",
        "unit": "CNY",
        "note": "产业资本增减持公告日净买入金额，不进入六维主温度",
    },
    {
        "mart": "repurchase_daily",
        "date_column": "announcement_date",
        "dimension": "fund_flow",
        "metric_id": "repurchase_amount_observation",
        "value_column": "repurchase_amount",
        "unit": "CNY",
        "note": "上市公司回购公告日金额，不进入六维主温度",
    },
    {
        "mart": "block_trade_daily",
        "date_column": "trade_date",
        "dimension": "fund_flow",
        "metric_id": "block_trade_discount_observation",
        "value_column": "block_trade_discount_rate_median",
        "unit": "ratio",
        "note": "大宗交易相对收盘价折溢价中位数，折价为负，不进入六维主温度",
    },
    {
        "mart": "settlement_iv_proxy_daily",
        "date_column": "trade_date",
        "dimension": "sentiment",
        "metric_id": "settlement_iv_proxy_observation",
        "value_column": "settlement_iv_proxy_median",
        "unit": "ratio",
        "note": "期权结算价 Black-Scholes 波动率代理，仅作风险偏好观察，不等同标准 VIX",
    },
)


def collect_domain_mart_observations(
    *,
    as_of_date: date,
    storage_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """读取各领域 Mart 最新可用行并转成观察事实。"""
    store = FeatureStore(mart_dir=Path(storage_dir) / "mart" if storage_dir else None)
    rows: list[dict[str, Any]] = []
    for spec in _OBSERVATION_SPECS:
        frame = store.get_domain_mart(
            spec["mart"],
            date_column=spec["date_column"],
            end_date=as_of_date,
        )
        if frame.is_empty() or spec["date_column"] not in frame.columns:
            rows.append(_unavailable_row(spec, as_of_date, "领域 Mart 不可用"))
            continue

        latest_date = frame[spec["date_column"]].max()
        if not isinstance(latest_date, date):
            rows.append(_unavailable_row(spec, as_of_date, "领域 Mart 无可解析业务日期"))
            continue
        rows.extend(_observation_rows(spec, frame, latest_date, as_of_date))
    return rows


def _observation_rows(
    spec: dict[str, str],
    frame: pl.DataFrame,
    latest_date: date,
    as_of_date: date,
) -> list[dict[str, Any]]:
    value_column = spec["value_column"]
    if value_column not in frame.columns:
        return [_unavailable_row(spec, as_of_date, f"缺少字段: {value_column}")]

    latest = frame.filter(pl.col(spec["date_column"]) == latest_date)
    rows: list[dict[str, Any]] = []
    for row in latest.to_dicts():
        value = _observation_value(spec, row)
        sample_size = _sample_size(spec, row)
        observation_id = spec["metric_id"]
        underlying = str(row.get("underlying_symbol") or "").strip()
        if underlying:
            observation_id = f"{observation_id}.{underlying}"
        note = f"{spec['note']}; metric_date={latest_date.isoformat()}"
        rows.append(
            _fact_row(
                spec,
                as_of_date=as_of_date,
                metric_id=observation_id,
                value_float=value,
                sample_size=sample_size,
                status="ok" if value is not None else "insufficient",
                note=note if value is not None else f"{note}; 数值为空",
            )
        )
    return rows or [_unavailable_row(spec, as_of_date, "最新业务日期无记录")]


def _sample_size(spec: dict[str, str], row: dict[str, Any]) -> int | None:
    candidates = (
        "cb_valid_count",
        "insider_event_count",
        "repurchase_announcement_count",
        "block_trade_event_count",
        "settlement_iv_proxy_valid_count",
    )
    if spec["mart"] == "convertible_bond_daily":
        valid_count = _as_float(row.get("cb_valid_count"))
        if spec["metric_id"] == "cb_low_price_share_observation":
            return int(valid_count) if valid_count is not None else None
    for column in candidates:
        value = _as_float(row.get(column))
        if value is not None:
            return int(value)
    return None


def _observation_value(spec: dict[str, str], row: dict[str, Any]) -> float | None:
    if spec["metric_id"] == "cb_low_price_share_observation":
        low_count = _as_float(row.get("cb_low_price_count"))
        valid_count = _as_float(row.get("cb_valid_count"))
        if low_count is None or valid_count is None or valid_count <= 0:
            return None
        return low_count / valid_count
    return _as_float(row.get(spec["value_column"]))


def _unavailable_row(spec: dict[str, str], as_of_date: date, note: str) -> dict[str, Any]:
    return _fact_row(
        spec,
        as_of_date=as_of_date,
        metric_id=spec["metric_id"],
        value_float=None,
        sample_size=0,
        status="unavailable",
        note=f"{spec['note']}; {note}",
    )


def _fact_row(
    spec: dict[str, str],
    *,
    as_of_date: date,
    metric_id: str,
    value_float: float | None,
    sample_size: int | None,
    status: str,
    note: str,
) -> dict[str, Any]:
    return {
        "fact_id": f"observation.{metric_id}",
        "category": "domain_observation",
        "dimension": spec["dimension"],
        "data_source": "mart",
        "dataset": spec["mart"],
        "as_of_date": as_of_date,
        "window": 0,
        "metric_id": metric_id,
        "value_float": value_float,
        "value_text": "" if value_float is None else f"{value_float:.6g}",
        "unit": spec["unit"],
        "sample_size": sample_size,
        "source": f"FeatureStore.{spec['mart']}",
        "status": status,
        "note": note,
    }


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(cast("Any", value))
    except (TypeError, ValueError):
        return None


__all__ = ["collect_domain_mart_observations"]
