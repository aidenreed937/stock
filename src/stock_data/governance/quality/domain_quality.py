"""可转债、公司行为与领域 Mart 的专用质量断言。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger

DOMAIN_MART_RULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "convertible_bond_daily": ("trade_date", ("trade_date",)),
    "insider_activity_daily": ("announcement_date", ("announcement_date",)),
    "repurchase_daily": ("announcement_date", ("announcement_date",)),
    "block_trade_daily": ("trade_date", ("trade_date",)),
    "settlement_iv_proxy_daily": (
        "trade_date",
        ("trade_date", "underlying_symbol"),
    ),
    "industry_daily": ("trade_date", ("trade_date", "industry_code")),
    "industry_panel_daily": ("as_of_date", ("as_of_date", "industry_code")),
    "industry_l2_daily": ("trade_date", ("trade_date", "industry_code")),
    "market_temperature_derived_facts": (
        "as_of_date",
        ("as_of_date", "fact_id"),
    ),
    "global_macro_daily": ("trade_date", ("trade_date",)),
    "dragon_tiger_daily": ("trade_date", ("trade_date",)),
    "etf_flow_daily": ("trade_date", ("trade_date",)),
    "unlock_pressure_daily": ("trade_date", ("trade_date",)),
    "northbound_industry_daily": ("trade_date", ("trade_date", "industry_code")),
    "capital_game_daily": ("trade_date", ("trade_date",)),
    "smart_money_daily": ("trade_date", ("trade_date",)),
}

DOMAIN_INPUT_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "cb_basic": ("symbol", "bond_short_name", "stk_code", "list_date", "exchange"),
    "cb_daily": ("symbol", "trade_date", "close"),
    "stk_holdertrade": ("symbol", "ann_date", "holder_name", "in_de", "change_vol"),
    "repurchase": ("symbol", "ann_date", "proc"),
    "block_trade": ("symbol", "trade_date", "price", "volume", "amount"),
}

DOMAIN_INPUT_DATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "cb_basic": ("list_date", "delist_date"),
    "cb_daily": ("trade_date",),
    "stk_holdertrade": ("ann_date",),
    "repurchase": ("ann_date",),
    "block_trade": ("trade_date",),
}

DOMAIN_INPUT_NON_NEGATIVE_COLUMNS: dict[str, tuple[str, ...]] = {
    "cb_daily": ("close", "volume", "amount"),
    "repurchase": ("vol", "volume", "amount"),
    "block_trade": ("price", "volume", "amount"),
}


def _dataset_name_from_path(file: Path) -> str:
    dataset_name = file.parent.name
    if dataset_name.startswith("month="):
        return file.parent.parent.parent.name
    return dataset_name


def assert_domain_mart_quality(_gate: object, files: list[Path]) -> bool:
    """校验领域 Mart 的日期、主键唯一性与数值有限性。"""
    for file in files:
        if file.parent.name != "mart" or file.stem not in DOMAIN_MART_RULES:
            continue
        mart_name = file.stem
        date_column, keys = DOMAIN_MART_RULES[mart_name]
        try:
            frame = pl.read_parquet(file)
            if frame.is_empty():
                continue
            if date_column not in frame.columns or frame[date_column].dtype != pl.Date:
                logger.error(f"领域 Mart [{file}] 日期列缺失或不是 pl.Date: {date_column}")
                return False
            if any(key not in frame.columns for key in keys):
                logger.error(f"领域 Mart [{file}] 缺少主键列: {keys}")
                return False
            if frame.height != frame.unique(subset=list(keys)).height:
                logger.error(f"领域 Mart [{file}] 存在重复主键: {keys}")
                return False
            float_columns = [
                column
                for column, dtype in frame.schema.items()
                if dtype in (pl.Float32, pl.Float64)
            ]
            if float_columns:
                invalid = frame.filter(
                    pl.any_horizontal(
                        [
                            pl.col(column).is_not_null() & ~pl.col(column).is_finite()
                            for column in float_columns
                        ]
                    )
                )
                if not invalid.is_empty():
                    logger.error(f"领域 Mart [{file}] 存在非有限数值")
                    return False
        except Exception as exc:
            logger.error(f"领域 Mart [{file}] 质量校验异常: {exc}")
            return False
    return True


def assert_domain_input_quality(_gate: object, files: list[Path]) -> bool:
    """校验可转债与公司行为 Curated 输入的字段、日期和数值契约。"""
    for file in files:
        dataset_name = _dataset_name_from_path(file)
        if dataset_name not in DOMAIN_INPUT_REQUIRED_COLUMNS:
            continue
        try:
            frame = pl.read_parquet(file)
            if frame.is_empty():
                continue
            required = DOMAIN_INPUT_REQUIRED_COLUMNS[dataset_name]
            missing = [column for column in required if column not in frame.columns]
            if missing:
                logger.error(f"输入数据集 [{file}] 缺少必需列: {missing}")
                return False
            for column in DOMAIN_INPUT_DATE_COLUMNS.get(dataset_name, ()):
                if column not in frame.columns:
                    continue
                if frame[column].dtype != pl.Date:
                    logger.error(f"输入数据集 [{file}] 日期列不是 pl.Date: {column}")
                    return False
            numeric_columns = [
                column
                for column in DOMAIN_INPUT_NON_NEGATIVE_COLUMNS.get(dataset_name, ())
                if column in frame.columns
            ]
            if numeric_columns:
                invalid = frame.filter(
                    pl.any_horizontal(
                        [
                            pl.col(column).is_not_null()
                            & (
                                ~pl.col(column).cast(pl.Float64, strict=False).is_finite()
                                | (pl.col(column).cast(pl.Float64, strict=False) < 0)
                            )
                            for column in numeric_columns
                        ]
                    )
                )
                if not invalid.is_empty():
                    logger.error(f"输入数据集 [{file}] 存在负值或非有限数值")
                    return False
        except Exception as exc:
            logger.error(f"输入数据集 [{file}] 质量校验异常: {exc}")
            return False
    return True


def assert_industry_growth_rate_sanity(_gate: object, files: list[Path]) -> bool:
    """校验行业与宏观事实表中所有增长率/同比/环比指标的物理数值合理性 (必须为小数制，严禁 100 倍错位)。

    已知数据质量案例 (负基数导致 yoy < -100%，属官方原始值、非单位错误)：
    - ``industry_panel_daily`` 的 ``revenue_growth_ttm`` 在 801230.SI (申万一级"综合") 2020-06-30 出现 -1.225，
      来源于理杏仁 ``sw_2021_fs_non_financial`` symbol=510000 的官方 ``q.ps.toi.ttm_y2y``，为基期 TTM 营收为负
      造成的负基数失真。该断言按设计照常拦截；下游消费方应过滤 ``revenue_growth_ttm < -1.01`` 的无效点。
    """
    for file in files:
        if file.suffix != ".parquet" or "industry" not in str(file):
            continue
        try:
            frame = pl.read_parquet(file)
            if frame.is_empty():
                continue
            try:
                from stock_data.core.task_resolution import resolve_task

                task_units = resolve_task("industry", file.stem).units
            except Exception:
                task_units = {}
            percent_point_columns = {
                column
                for column, unit in task_units.items()
                if unit in {"percent_points", "percentage_points"}
            }
            rate_columns = [
                col
                for col, dtype in frame.schema.items()
                if dtype in (pl.Float32, pl.Float64)
                and any(k in col.lower() for k in ("growth", "yoy", "mom", "penetration"))
                and col not in percent_point_columns
                and not any(
                    k in col.lower()
                    for k in (
                        "price",
                        "cny",
                        "usd",
                        "jpy",
                        "ton",
                        "index",
                        "vol",
                        "heads",
                        "cases",
                        "weeks",
                        "utilization_pct",
                        "operating_rate_pct",
                        "spread",
                    )
                )
            ]
            for col in sorted(percent_point_columns.intersection(frame.columns)):
                series = frame[col].drop_nulls()
                if not series.is_empty() and float(str(series.min())) < -100.0:
                    logger.error(
                        f"行业事实表 [{file.name}] 列 [{col}] 百分点评分低于 -100: "
                        f"min={float(str(series.min())):.2f}"
                    )
                    return False
            for col in rate_columns:
                series = frame[col].drop_nulls()
                if series.is_empty():
                    continue
                # 物理下限断言: 增长率不可能低于 -100% (-1.0)
                min_val = float(str(series.min()))
                if min_val < -1.01:
                    logger.error(
                        f"行业事实表 [{file.name}] 列 [{col}] 存在物理下限超限 (增长率 < -100%): min={min_val}"
                    )
                    return False

                # 整体分布断言: 排除低基数黑天鹅暴增后，中位数与 75% 分位数绝不能大于 2.0 (200%)
                # 若中位数落在 10~50 之间，必然是百分制未除以 100 的 100 倍单位错乱
                median_obj = series.median()
                q75_obj = series.quantile(0.75)
                median_val = float(str(median_obj)) if median_obj is not None else 0.0
                q75_val = float(str(q75_obj)) if q75_obj is not None else 0.0
                if median_val > 2.0 or q75_val > 5.0:
                    logger.error(
                        f"行业事实表 [{file.name}] 列 [{col}] 存在 100 倍单位错乱 (百分制未归一为小数): "
                        f"median={median_val:.2f}, q75={q75_val:.2f} (预期中位数在 [-0.5, 1.0])"
                    )
                    return False
        except Exception as exc:
            logger.error(f"校验行业指标合理性异常 [{file}]: {exc}")
            return False
    return True


__all__ = [
    "DOMAIN_INPUT_DATE_COLUMNS",
    "DOMAIN_INPUT_NON_NEGATIVE_COLUMNS",
    "DOMAIN_INPUT_REQUIRED_COLUMNS",
    "DOMAIN_MART_RULES",
    "assert_domain_input_quality",
    "assert_domain_mart_quality",
    "assert_industry_growth_rate_sanity",
]
