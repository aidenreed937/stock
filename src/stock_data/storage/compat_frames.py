"""嵌套字段、稳定实体与历史数据集后处理兼容规则。"""

from __future__ import annotations

import ast
import json
import math
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import polars as pl

from stock_data.storage.legacy_compat import normalize_legacy_index_valuation

_LEGACY_INTEREST_RATE_COLUMNS = frozenset({"lpr_y1", "lpr_y5"})
_STABLE_SYMBOL_DATASETS = frozenset(
    {
        "cn_gdp",
        "cn_cpi",
        "cn_ppi",
        "cn_pmi",
        "cn_m",
        "sf_month",
        "shibor",
        "shibor_lpr",
        "stk_account",
        "index_classify",
        "index_member",
    }
)

_LIXINGER_INDUSTRY_FINANCIAL_DATASETS = frozenset(
    {
        f"sw_2021_{level}fs_{sector}"
        for level in ("", "l2_", "l3_")
        for sector in ("non_financial", "bank", "security", "insurance")
    }
)


def _contains_empty_struct(dtype: object) -> bool:
    """递归判断嵌套类型中是否存在 Parquet 不支持的空 struct。"""
    if isinstance(dtype, pl.Struct):
        return not dtype.fields or any(
            _contains_empty_struct(field.dtype) for field in dtype.fields
        )
    inner = getattr(dtype, "inner", None)
    return inner is not None and _contains_empty_struct(inner)


def _json_encode_nested_value(value: object) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(value)


def _parse_legacy_braced_struct(value: str) -> list[Any] | None:
    """解析 Polars 将旧嵌套 struct 强制转成的无名大括号字符串。"""
    text = value.strip()
    if not text.startswith("{"):
        return None
    position = 0

    def parse_group() -> tuple[list[Any], int]:
        nonlocal position
        if position >= len(text) or text[position] != "{":
            raise ValueError("invalid group start")
        position += 1
        items: list[Any] = []
        while position < len(text):
            while position < len(text) and text[position].isspace():
                position += 1
            if position >= len(text):
                raise ValueError("unterminated group")
            item: Any
            if text[position] == "}":
                position += 1
                return items, position
            if text[position] == "{":
                item, _ = parse_group()
            else:
                start = position
                while position < len(text) and text[position] not in ",}":
                    position += 1
                token = text[start:position].strip()
                item = None if token.lower() in {"", "none", "null", "nan"} else float(token)
            items.append(item)
            while position < len(text) and text[position].isspace():
                position += 1
            if position < len(text) and text[position] == ",":
                position += 1
                continue
            if position < len(text) and text[position] == "}":
                position += 1
                return items, position
            raise ValueError("invalid group separator")
        raise ValueError("unterminated group")

    try:
        tree, end = parse_group()
    except (TypeError, ValueError):
        return None
    return tree if not text[end:].strip() else None


def _parse_nested_value(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(value)
        except (TypeError, ValueError, SyntaxError):
            continue
        if isinstance(parsed, dict):
            return parsed
    tree = _parse_legacy_braced_struct(value)
    if not isinstance(tree, list) or len(tree) < 2:
        return {}

    ps_tree = tree[0] if isinstance(tree[0], list) else []
    toi_values = ps_tree[0] if len(ps_tree) > 0 and isinstance(ps_tree[0], list) else []
    np_values = ps_tree[1] if len(ps_tree) > 1 and isinstance(ps_tree[1], list) else []
    m_tree = tree[1] if isinstance(tree[1], list) else []
    roe_values = m_tree[0] if m_tree and isinstance(m_tree[0], list) else []

    def legacy_metric(values: list[Any]) -> dict[str, Any]:
        if len(values) >= 3:
            return {"t": values[0], "c_y2y": values[1], "ttm_y2y": values[2]}
        if len(values) == 2:
            return {"t": None, "c_y2y": values[0], "ttm_y2y": values[1]}
        return {
            "t": None,
            "c_y2y": values[0] if values else None,
            "ttm_y2y": None,
        }

    return {
        "ps": {"toi": legacy_metric(toi_values), "np": legacy_metric(np_values)},
        "m": {"roe": {"ttm": roe_values[0] if roe_values else None}},
    }


def _nested_path(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


_DERIVED_TTM_Y2Y_FIELD = "ttm_y2y_derived"


def _canonical_industry_q(
    dataset_name: str, value: object, *, include_derived: bool = False
) -> dict[str, Any]:
    parsed = _parse_nested_value(value)

    def metric(path: str) -> dict[str, Any]:
        current = _nested_path(parsed, "ps", path)
        result = {
            "t": _nested_path(current, "t") if isinstance(current, dict) else None,
            "c_y2y": _nested_path(current, "c_y2y") if isinstance(current, dict) else None,
            "ttm_y2y": _nested_path(current, "ttm_y2y") if isinstance(current, dict) else None,
        }
        if include_derived:
            result[_DERIVED_TTM_Y2Y_FIELD] = (
                _nested_path(current, _DERIVED_TTM_Y2Y_FIELD) if isinstance(current, dict) else None
            )
        return result

    ps: dict[str, Any] = {"toi": metric("toi"), "np": metric("np")}
    if dataset_name.endswith("fs_non_financial"):
        ps["gp_m"] = {"ttm": _nested_path(parsed, "ps", "gp_m", "ttm")}
    return {
        "ps": ps,
        "m": {"roe": {"ttm": _nested_path(parsed, "m", "roe", "ttm")}},
    }


def _industry_q_dtype(dataset_name: str, *, include_derived: bool = False) -> pl.DataType:
    metric_fields: dict[str, Any] = {
        "t": pl.Int64,
        "c_y2y": pl.Float64,
        "ttm_y2y": pl.Float64,
    }
    if include_derived:
        metric_fields[_DERIVED_TTM_Y2Y_FIELD] = pl.Float64
    metric_dtype = pl.Struct(metric_fields)
    ps_fields: dict[str, pl.DataType] = {"toi": metric_dtype, "np": metric_dtype}
    if dataset_name.endswith("fs_non_financial"):
        ps_fields["gp_m"] = pl.Struct({"ttm": pl.Float64})
    return pl.Struct(
        {
            "ps": pl.Struct(ps_fields),
            "m": pl.Struct({"roe": pl.Struct({"ttm": pl.Float64})}),
        }
    )


def _parse_industry_period(value: object) -> int | None:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        year, month = value.year, value.month
    else:
        text = str(value).strip()[:10]
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            return None
        year, month = parsed.year, parsed.month
    if month not in {3, 6, 9, 12}:
        return None
    return year * 4 + month // 3 - 1


def _as_finite_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _derive_industry_ttm_y2y(frame: pl.DataFrame, metric: str) -> list[float | None]:
    """按行业和自然季度从 YTD 累计值还原 TTM 同比。"""
    if not {"symbol", "standardDate", "q"}.issubset(frame.columns):
        return [None] * frame.height

    symbols = frame["symbol"].cast(pl.Utf8, strict=False).to_list()
    periods = [_parse_industry_period(value) for value in frame["standardDate"].to_list()]
    q_values = frame["q"].to_list()
    period_values: dict[str, dict[int, float | None]] = {}
    row_periods: list[tuple[str, int] | None] = []
    for symbol, period, q_value in zip(symbols, periods, q_values, strict=True):
        if symbol is None or period is None:
            row_periods.append(None)
            continue
        metric_value = (
            _nested_path(q_value, "ps", metric, "t") if isinstance(q_value, dict) else None
        )
        period_values.setdefault(symbol, {})[period] = _as_finite_float(metric_value)
        row_periods.append((symbol, period))

    derived_by_period: dict[tuple[str, int], float | None] = {}
    for symbol, values in period_values.items():
        quarterly: dict[int, float | None] = {}
        for period, cumulative in values.items():
            if cumulative is None:
                quarterly[period] = None
            elif period % 4 == 0:
                quarterly[period] = cumulative
            else:
                previous = values.get(period - 1)
                quarterly[period] = cumulative - previous if previous is not None else None

        ttm: dict[int, float] = {}
        for period in values:
            window = [quarterly.get(item) for item in range(period - 3, period + 1)]
            if all(item is not None for item in window):
                ttm[period] = sum(item for item in window if item is not None)
        for period, current in ttm.items():
            previous = ttm.get(period - 4)
            derived_by_period[(symbol, period)] = (
                (current - previous) / abs(previous)
                if previous is not None and previous != 0.0
                else None
            )

    return [
        derived_by_period.get(row_period) if row_period is not None else None
        for row_period in row_periods
    ]


class FrameCompatMixin:
    """处理嵌套字段、稳定标识和历史数据集后处理。"""

    @classmethod
    def normalize_nested_columns(
        cls,
        df: pl.DataFrame,
        reference_frames: Sequence[pl.DataFrame] = (),
    ) -> pl.DataFrame:
        """对齐空嵌套字段，避免 RAW/Curated 写入不可序列化的空 struct。"""
        if df.is_empty():
            return df
        expressions = []
        for column, dtype in df.schema.items():
            if not _contains_empty_struct(dtype):
                continue
            reference_dtype = next(
                (
                    frame.schema[column]
                    for frame in reference_frames
                    if column in frame.columns
                    and isinstance(frame.schema[column], pl.Struct)
                    and not _contains_empty_struct(frame.schema[column])
                ),
                None,
            )
            if isinstance(dtype, pl.Struct) and isinstance(reference_dtype, pl.Struct):
                expressions.append(pl.col(column).cast(reference_dtype, strict=False).alias(column))
            elif isinstance(dtype, pl.Struct):
                expressions.append(pl.col(column).struct.json_encode().alias(column))
            else:
                expressions.append(
                    pl.col(column)
                    .map_elements(_json_encode_nested_value, return_dtype=pl.Utf8)
                    .alias(column)
                )
        return df.with_columns(expressions) if expressions else df

    @staticmethod
    def normalize_lixinger_industry_financial_q(
        dataset_name: str, df: pl.DataFrame, *, include_derived: bool = False
    ) -> pl.DataFrame:
        """将申万行业财报的历史 q 字符串/旧结构体归一为稳定嵌套 Schema。"""
        if (
            df.is_empty()
            or dataset_name not in _LIXINGER_INDUSTRY_FINANCIAL_DATASETS
            or "q" not in df.columns
        ):
            return df
        dtype = _industry_q_dtype(dataset_name, include_derived=include_derived)
        values = [
            _canonical_industry_q(dataset_name, value, include_derived=include_derived)
            for value in df["q"].to_list()
        ]
        return df.with_columns(pl.Series("q", values, dtype=dtype))

    @staticmethod
    def derive_lixinger_industry_financial_ttm(dataset_name: str, df: pl.DataFrame) -> pl.DataFrame:
        """在 Curated 中补充缺失的行业财报 TTM 同比字段。

        RAW 保留源端 ``q.ps.{toi,np}.ttm_y2y``；Curated 额外写入
        ``q.ps.{toi,np}.ttm_y2y_derived``。派生值由 ``t`` 的 YTD 累计值还原单季后，
        对连续四个季度求和，再与四季度前的 TTM 比较。源端已有值时不覆盖，也不写入派生值。
        """
        if (
            df.is_empty()
            or dataset_name not in _LIXINGER_INDUSTRY_FINANCIAL_DATASETS
            or "q" not in df.columns
            or not {"symbol", "standardDate"}.issubset(df.columns)
        ):
            return df

        normalized = FrameCompatMixin.normalize_lixinger_industry_financial_q(
            dataset_name, df, include_derived=True
        )
        derived_by_metric = {
            metric: _derive_industry_ttm_y2y(normalized, metric) for metric in ("toi", "np")
        }
        values: list[dict[str, Any]] = []
        for index, value in enumerate(normalized["q"].to_list()):
            q_value = _canonical_industry_q(dataset_name, value, include_derived=True)
            for metric in ("toi", "np"):
                source_value = q_value["ps"][metric].get("ttm_y2y")
                if source_value is None:
                    q_value["ps"][metric][_DERIVED_TTM_Y2Y_FIELD] = derived_by_metric[metric][index]
                else:
                    q_value["ps"][metric][_DERIVED_TTM_Y2Y_FIELD] = None
            values.append(q_value)
        return normalized.with_columns(
            pl.Series(
                "q",
                values,
                dtype=_industry_q_dtype(dataset_name, include_derived=True),
            )
        )

    @staticmethod
    def ensure_dataset_identity(dataset_name: str, df: pl.DataFrame) -> pl.DataFrame:
        """为只有期间主键的宏观序列补齐稳定实体标识。"""
        if df.is_empty() or dataset_name not in _STABLE_SYMBOL_DATASETS:
            return df
        if "symbol" not in df.columns:
            return df.with_columns(pl.lit(dataset_name).alias("symbol"))
        return df.with_columns(
            pl.col("symbol").cast(pl.Utf8, strict=False).fill_null(dataset_name).alias("symbol")
        )

    @staticmethod
    def safe_normalize_frame(df: pl.DataFrame) -> pl.DataFrame:
        """对加载的单个 Parquet 分区执行在线容错预规范化。"""
        if df.is_empty():
            return df
        from stock_data.storage.compat_columns import ColumnCompatMixin

        normalized = ColumnCompatMixin.normalize_identity_columns(df)
        normalized = ColumnCompatMixin.normalize_date_columns(normalized)
        normalized = ColumnCompatMixin.normalize_datetime_columns(normalized)
        return ColumnCompatMixin.normalize_numeric_columns(normalized)

    @staticmethod
    def normalize_dataset_contract_columns(dataset_name: str, df: pl.DataFrame) -> pl.DataFrame:
        """将历史字段映射到数据集规范字段，并固定关键数值类型。"""
        if df.is_empty():
            return df
        normalized = df
        if dataset_name == "express" and "yoy_net_profit" in normalized.columns:
            if "prior_period_net_profit" not in normalized.columns:
                normalized = normalized.rename({"yoy_net_profit": "prior_period_net_profit"})
            else:
                normalized = normalized.with_columns(
                    pl.coalesce(
                        [
                            pl.col("prior_period_net_profit").cast(pl.Float64, strict=False),
                            pl.col("yoy_net_profit").cast(pl.Float64, strict=False),
                        ]
                    ).alias("prior_period_net_profit")
                ).drop("yoy_net_profit")
        if dataset_name == "national_debt" and "tcm_y10" in normalized.columns:
            normalized = normalized.with_columns(
                pl.col("tcm_y10").cast(pl.Float64, strict=False).alias("tcm_y10")
            )
        return normalized

    @staticmethod
    def post_process_dataset(dataset_name: str, df: pl.DataFrame) -> pl.DataFrame:
        from stock_data.storage.compat_columns import ColumnCompatMixin

        df = ColumnCompatMixin.normalize_financial_statement_columns(dataset_name, df)
        df = ColumnCompatMixin.normalize_date_columns(df)
        df = ColumnCompatMixin.normalize_numeric_columns(df, dataset_name)
        df = FrameCompatMixin.ensure_dataset_identity(dataset_name, df)
        df = normalize_legacy_index_valuation(df) if dataset_name == "index_valuation" else df
        if dataset_name in _LIXINGER_INDUSTRY_FINANCIAL_DATASETS and "q" in df.columns:
            df = FrameCompatMixin.derive_lixinger_industry_financial_ttm(dataset_name, df)
        if dataset_name == "hk_hold" and "symbol" in df.columns:
            qualified = df.filter(pl.col("symbol").cast(pl.Utf8, strict=False).str.contains(r"\."))
            if not qualified.is_empty():
                return qualified
        if dataset_name == "margin" and "symbol" in df.columns:
            return df.drop("symbol")
        if dataset_name == "moneyflow_hsgt":
            normalized = df.drop("symbol") if "symbol" in df.columns else df
            return normalized.with_columns(
                pl.lit("CN").alias("market"),
                pl.lit("CNY").alias("currency"),
                pl.lit("SOURCE").alias("exchange"),
            )
        if dataset_name == "sw_daily":
            legacy_cols = [
                "fetched_at",
                "field_provenance",
                "index_id",
                "index_name",
                "industry_id",
                "industry_name",
                "pct_chg",
                "scope_note",
                "source_id",
                "source_index_code",
                "source_scope",
                "source_unit_note",
                "turnover_amount",
            ]
            to_drop = [column for column in legacy_cols if column in df.columns]
            if to_drop:
                return df.drop(to_drop)
        if dataset_name == "interest_rates":
            to_drop = [column for column in _LEGACY_INTEREST_RATE_COLUMNS if column in df.columns]
            if to_drop:
                return df.drop(to_drop)
        return df
