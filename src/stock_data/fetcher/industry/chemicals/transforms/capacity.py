"""化工产能利用率 RAW/Curated 转换（支持 1-2 月双轨拆解还原）。"""

from __future__ import annotations

import calendar
import math
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.chemicals.schemas import (
    CAPACITY_RAW_SCHEMA,
    CAPACITY_UTILIZATION_SCHEMA,
)
from stock_data.fetcher.industry.common import now_utc_iso


def build_capacity_raw_frame(df: pl.DataFrame) -> pl.DataFrame:
    """校正并返回产能利用率 RAW 表。"""
    return df if not df.is_empty() else pl.DataFrame(schema=CAPACITY_RAW_SCHEMA)


def build_capacity_utilization_frame(
    df: pl.DataFrame,
    weekly_survey_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """从 NBS/产能 RAW 计算 Curated 利用率与同比（支持 1-2 月双轨拆解还原）。"""
    if df.is_empty():
        return pl.DataFrame(schema=CAPACITY_UTILIZATION_SCHEMA)

    if weekly_survey_df is None:
        weekly_survey_df = _load_default_weekly_survey()

    now_iso = now_utc_iso()
    records: list[dict[str, object]] = []

    # 1. 建立 (product_name, year) -> {month: row} 索引，识别 1-2 月合并累计事实
    rows = df.to_dicts()
    prod_year_groups: dict[tuple[str, int], dict[int, dict[str, object]]] = {}
    for r in rows:
        m_str = str(r.get("report_month") or "").strip()
        try:
            yr, mo = int(m_str[:4]), int(m_str[5:7])
        except (TypeError, ValueError):
            continue
        p_name = str(r.get("product_name") or "纯碱")
        prod_year_groups.setdefault((p_name, yr), {})[mo] = r

    # 2. 跟踪已生成的 (product_name, month_key) 避免重复
    processed_months: set[tuple[str, str]] = set()

    # 3. 处理常规月份（已有当月有效产量 output_current_raw）
    for r in rows:
        m_str = str(r.get("report_month") or "").strip()
        try:
            year, month = int(m_str[:4]), int(m_str[5:7])
            report_date = date(year, month, 1)
        except (TypeError, ValueError):
            continue

        p_name = str(r.get("product_name") or "纯碱")
        sym = str(r.get("symbol") or "SA")
        unit_str = str(r.get("unit") or "万吨")

        output = _safe_float(r.get("output_current_raw"))
        if output is None or not math.isfinite(output) or output < 0:
            continue

        capacity = _safe_float(r.get("annual_capacity_raw"))
        monthly_capacity: float | None = None
        implied_utilization: float | None = None
        annual_capacity_val: float | None = None

        if capacity is not None and math.isfinite(capacity) and capacity > 0:
            annual_capacity_val = capacity
            days_in_mo = calendar.monthrange(year, month)[1]
            monthly_capacity = round(capacity * (days_in_mo / 365.0), 2)
            implied_utilization = round(output / monthly_capacity * 100.0, 2)

        yoy = _safe_float(r.get("output_yoy_raw"))

        records.append(
            {
                "trade_date": report_date,
                "report_date": report_date,
                "year": year,
                "month": month,
                "product_name": p_name,
                "symbol": sym,
                "actual_output_w_tons": output,
                "annual_capacity_w_tons": annual_capacity_val,
                "monthly_capacity_w_tons": monthly_capacity,
                "implied_capacity_utilization_pct": implied_utilization,
                "yoy_growth": round(yoy / 100.0, 4) if yoy is not None else None,
                "unit": unit_str,
                "source": (
                    f"{r.get('source') or 'NBS_Official'}/"
                    f"{r.get('capacity_source') or 'capacity_raw'}"
                ),
                "release_date": r.get("release_date"),
                "collected_at": r.get("collected_at") or now_iso,
            }
        )
        processed_months.add((p_name, m_str))

    # 4. 双轨拆解 1-2 月合并累计数据（方案2周度优先 + 方案1天数保底）
    for (p_name, yr), months_map in prod_year_groups.items():
        m1_key = f"{yr:04d}-01"
        m2_key = f"{yr:04d}-02"
        # 若 1 月和 2 月均已存在有效常规数据，无需拆解
        if (p_name, m1_key) in processed_months and (p_name, m2_key) in processed_months:
            continue

        r2 = months_map.get(2)
        if r2 is None:
            continue

        cum2_output = _safe_float(r2.get("output_cumulative_raw"))
        if cum2_output is None or not math.isfinite(cum2_output) or cum2_output <= 0:
            continue

        r1 = months_map.get(1) or r2
        sym = str(r2.get("symbol") or (r1.get("symbol") if r1 else "SA"))
        unit_str = str(r2.get("unit") or (r1.get("unit") if r1 else "万吨"))
        cap_val = _safe_float(r2.get("annual_capacity_raw")) or (
            _safe_float(r1.get("annual_capacity_raw")) if r1 else None
        )
        cap_source = str(r2.get("capacity_source") or "CPCIF") if cap_val is not None else None

        # 计算双轨权重
        w1, _w2, split_method = _calculate_jan_feb_weights(yr, p_name, weekly_survey_df)
        split_src = (
            f"{r2.get('source') or 'NBS_Official'}/{split_method}/{cap_source}"
            if cap_source
            else f"{r2.get('source') or 'NBS_Official'}/{split_method}"
        )

        # 严格守恒拆解实物产量
        output_jan = round(cum2_output * w1, 2)
        output_feb = round(cum2_output - output_jan, 2)

        # 同比增速继承 1-2 月累计同比
        cum_yoy = _safe_float(r2.get("output_cum_yoy_raw"))
        yoy_val = round(cum_yoy / 100.0, 4) if cum_yoy is not None else None

        feb_days = calendar.monthrange(yr, 2)[1]
        release_d = date(yr, 3, 18)

        # 构建 1 月记录（若尚未存在）
        if (p_name, m1_key) not in processed_months:
            mo_cap_jan: float | None = None
            util_jan: float | None = None
            if cap_val is not None and math.isfinite(cap_val) and cap_val > 0:
                mo_cap_jan = round(cap_val * (31.0 / 365.0), 2)
                util_jan = round(output_jan / mo_cap_jan * 100.0, 2)

            records.append(
                {
                    "trade_date": date(yr, 1, 1),
                    "report_date": date(yr, 1, 1),
                    "year": yr,
                    "month": 1,
                    "product_name": p_name,
                    "symbol": sym,
                    "actual_output_w_tons": output_jan,
                    "annual_capacity_w_tons": cap_val,
                    "monthly_capacity_w_tons": mo_cap_jan,
                    "implied_capacity_utilization_pct": util_jan,
                    "yoy_growth": yoy_val,
                    "unit": unit_str,
                    "source": split_src,
                    "release_date": release_d,
                    "collected_at": now_iso,
                }
            )
            processed_months.add((p_name, m1_key))

        # 构建 2 月记录（若尚未存在）
        if (p_name, m2_key) not in processed_months:
            mo_cap_feb: float | None = None
            util_feb: float | None = None
            if cap_val is not None and math.isfinite(cap_val) and cap_val > 0:
                mo_cap_feb = round(cap_val * (feb_days / 365.0), 2)
                util_feb = round(output_feb / mo_cap_feb * 100.0, 2)

            records.append(
                {
                    "trade_date": date(yr, 2, 1),
                    "report_date": date(yr, 2, 1),
                    "year": yr,
                    "month": 2,
                    "product_name": p_name,
                    "symbol": sym,
                    "actual_output_w_tons": output_feb,
                    "annual_capacity_w_tons": cap_val,
                    "monthly_capacity_w_tons": mo_cap_feb,
                    "implied_capacity_utilization_pct": util_feb,
                    "yoy_growth": yoy_val,
                    "unit": unit_str,
                    "source": split_src,
                    "release_date": release_d,
                    "collected_at": now_iso,
                }
            )
            processed_months.add((p_name, m2_key))

    if not records:
        return pl.DataFrame(schema=CAPACITY_UTILIZATION_SCHEMA)

    return (
        pl.DataFrame(records, schema=CAPACITY_UTILIZATION_SCHEMA)
        .unique(subset=["product_name", "report_date"], keep="last")
        .sort(["product_name", "report_date"])
    )


def _calculate_jan_feb_weights(
    year: int,
    product_name: str,
    weekly_survey_df: pl.DataFrame | None,
) -> tuple[float, float, str]:
    """计算 1 月与 2 月的拆分权重，返回 (w1, w2, split_method)。"""
    feb_days = calendar.monthrange(year, 2)[1]
    default_w1 = 31.0 / (31.0 + feb_days)
    default_w2 = feb_days / (31.0 + feb_days)

    if weekly_survey_df is not None and not weekly_survey_df.is_empty():
        prod_col = "product_name" if "product_name" in weekly_survey_df.columns else None
        date_col = "report_date" if "report_date" in weekly_survey_df.columns else "trade_date"
        output_col = (
            "weekly_output_w_tons" if "weekly_output_w_tons" in weekly_survey_df.columns else None
        )

        if prod_col and date_col and output_col:
            sub = weekly_survey_df.filter(
                (pl.col(prod_col) == product_name)
                & (pl.col(date_col).dt.year() == year)
                & (pl.col(date_col).dt.month().is_in([1, 2]))
            )
            if not sub.is_empty():
                jan_sub = sub.filter(pl.col(date_col).dt.month() == 1)
                feb_sub = sub.filter(pl.col(date_col).dt.month() == 2)
                jan_w = jan_sub.select(pl.col(output_col).drop_nulls().sum()).item() or 0.0
                feb_w = feb_sub.select(pl.col(output_col).drop_nulls().sum()).item() or 0.0
                total_w = jan_w + feb_w
                if total_w > 0 and jan_w > 0 and feb_w > 0:
                    w1 = jan_w / total_w
                    w2 = feb_w / total_w
                    return w1, w2, "weekly_survey_split"

    return default_w1, default_w2, "day_weighted_split"


def _load_default_weekly_survey() -> pl.DataFrame | None:
    """尝试加载本地周度调查数据。"""
    survey_path = Path("data/curated/industry/chemical_weekly_survey.parquet")
    if survey_path.exists():
        try:
            return pl.read_parquet(survey_path)
        except Exception:
            pass
    return None


def _safe_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"nan", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


__all__ = ["build_capacity_raw_frame", "build_capacity_utilization_frame"]
