"""申万二级行业基本面面板 Mart（财报滞后验证 · 量价齐升接入）。

按 `.agents/skills/industry-trend-tracking` 的因子定义，把理杏仁 L2 财务黄金表
``sw_2021_l2_fs_*``（25 报告期营收/净利 TTM 同比、毛利率）合并进 ``industry_l2_daily``
（行情/估值/动量），输出三级行业基本面面板：

- ``revenue_growth_ttm`` / ``profit_growth_ttm`` / ``gross_margin_ttm``：L2 财务事实；
- ``supply_demand_score``：财报滞后验证 · 量价齐升质量分（双正→双增速分位；供给收缩→20；双负→10）；
- ``bargaining_score``：财报滞后验证 · 毛利率扩张/议价权分（量价齐升门内→(净利−营收)增速分位；门外→30）；
- ``crowding_score``：拥挤度（成交额截面分位，缺失用中性 50）；
- ``direction_score``：全球方向（数据缺口，中性 50）；
- ``d_state`` / ``s_state`` / ``quadrant``：供需象限打标（需求态 × 供给态 9 宫格，
  阈值对齐 `scripts/industry_supply_demand_quadrant.py` 实证口径：方向 >55/<35、capex >30/<0）。

报告期滞后：财务行以 ``reportDate``（发布日）为可用起点，日频面板按发布日生效，
避免前视偏差。
"""

from __future__ import annotations

import warnings
from datetime import date
from typing import Any

import polars as pl

INDUSTRY_L2_PANEL_MART_NAME = "industry_l2_panel_daily"

# 面板输出 schema（按此顺序落盘）
INDUSTRY_L2_PANEL_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "industry_code": pl.Utf8,
    "industry_name": pl.Utf8,
    "parent_l1_code": pl.Utf8,
    "parent_l1_name": pl.Utf8,
    "close": pl.Float64,
    "amount_yi": pl.Float64,
    "return_20d": pl.Float64,
    "return_60d": pl.Float64,
    "pe_ttm_ew_percentile_5y": pl.Float64,
    "pb_ew_percentile_5y": pl.Float64,
    "revenue_growth_ttm": pl.Float64,
    "profit_growth_ttm": pl.Float64,
    "gross_margin_ttm": pl.Float64,
    "supply_demand_score": pl.Float64,
    "bargaining_score": pl.Float64,
    "crowding_score": pl.Float64,
    "direction_score": pl.Float64,
    "demand_score": pl.Float64,
    "supply_score": pl.Float64,
    "price_score": pl.Float64,
    "scissors_score": pl.Float64,
    "cip_yoy": pl.Float64,
    "fix_assets_yoy": pl.Float64,
    "cip_to_fa_ratio": pl.Float64,
    "capex_growth_ttm": pl.Float64,
    "inventory_scissors": pl.Float64,
    "d_state": pl.Utf8,  # 需求态（方向分）：高(>55)/中(35-55)/低(<35)，缺失→未知
    "s_state": pl.Utf8,  # 供给态（capex + 化工开工率/库存）：扩张/平稳/收缩，缺失→未知
    "quadrant": pl.Utf8,  # 供需象限 = d_state × s_state（9 宫格标签）
    "leg_type": pl.Utf8,  # 信号腿供需属性：demand（需求）/price（价格）/supply/finance
    "chem_operating_rate": pl.Float64,  # 化工开工率%（MDI/TiO2，chemical_market；仅化工行业非空）
    "chem_inventory_days": pl.Float64,  # 化工库存天数（chemical_market；仅化工行业非空）
    # 剪刀差形态诊断（270100 实证口径，framework.md:142-152；仅半导体计算，其余行业中性）
    "scissors_zone": pl.Utf8,  # 剪刀差区间：LONG(>+20) / AVOID(<-20) / NEUTRAL(|sci|<=20 或非 270100)
    "scissors_zone_days": pl.Int32,  # 当前连续区间已持续交易日数（1-based；非 270100 → -1）
    "scissors_diagnosis": pl.Utf8,  # 形态标签：LONG_SUSTAINED/LONG_SHORT/AVOID_SUPPLY_PEAK/AVOID_SHORT/AVOID_DEMAND_STRONG/AVOID_UNCLASSIFIED/NEUTRAL
    "days_since_turn_negative": pl.Int32,  # 剪刀差自 >=0 转 <0 以来交易日数（1-based；未转负/已回正/非 270100 → -1）
}

# 量价齐升质量分参数（对齐 config/analytics/industry_trend_tracking.yaml）
_SUPPLY_CONTRACT_PENALTY = 20.0  # 供给收缩（营收负、净利正）：假繁荣
_DOUBLE_NEGATIVE_PENALTY = 10.0  # 双负（营收负、净利负）
_BARGAINING_NEUTRAL = 30.0  # 量价齐升门外的议价权中性分
_DIRECTION_NEUTRAL = 50.0  # 全球方向数据缺口中性分

# 供需象限阈值（对齐 scripts/industry_supply_demand_quadrant.py 实证口径）
_DEMAND_HIGH = 55.0  # direction_score > 55 = 需求扩张
_DEMAND_LOW = 35.0  # direction_score < 35 = 需求收缩
_CAPEX_HIGH = 30.0  # capex_growth_ttm > 30 = 供给扩张
_CAPEX_LOW = 0.0  # capex_growth_ttm < 0 = 供给收缩
# 化工开工率供给过剩阈值（chemical_market 实证：开工率≥75 且库存高 = 满产过剩）
_CHEM_RATE_HIGH = 75.0
_CHEM_INV_HIGH = 30.0  # 库存天数（天）高位阈值

# 剪刀差形态诊断阈值（270100 实证，framework.md:142-152，对齐 scratch/semi_scissors_signal_table.py）
_SCISSORS_TH_POS = 20.0  # LONG：剪刀差 > +20
_SCISSORS_TH_NEG = -20.0  # AVOID：剪刀差 < -20
_LONG_SUSTAIN_MIN_DAYS = 30  # LONG 持续型有效下限（2019-06/2020-03 实证）
_AVOID_SHORT_MAX_DAYS = 10  # AVOID 短触发误报上限（<10 天迅速回正）
_AVOID_PEAK_MIN_DAYS = 90  # AVOID 供给洪峰型成立下限（>90 天）
_SUPPLY_PEAK_SCORE = 100.0  # 供给分=100（SEAJ 设备出货 3 年分位极值）
_DEMAND_STRONG_SCORE = 65.0  # 需求仍强误报阈值（需求分 >65）
_MORPHOLOGY_SCOPE = "270100"  # 仅半导体：形态参数在该行业拟合，不外推其他行业


def _demand_state_expr() -> pl.Expr:
    """需求态三分：高(>55) / 中(35-55) / 低(<35)，方向分缺失→未知。

    leg_type=price 的腿（铜/金/运价等价格信号）标注为「价格驱动」——价格涨跌不等于
    需求扩张，避免把价格信号误当需求态参与象限判定。
    """
    return (
        pl.when(pl.col("leg_type") == "price")
        .then(pl.lit("价格驱动"))
        .when(pl.col("direction_score").is_null())
        .then(pl.lit("未知"))
        .when(pl.col("direction_score") > _DEMAND_HIGH)
        .then(pl.lit("需求高"))
        .when(pl.col("direction_score") < _DEMAND_LOW)
        .then(pl.lit("需求低"))
        .otherwise(pl.lit("需求中"))
    )


def _supply_state_expr() -> pl.Expr:
    """供给态三分：扩张 / 平稳 / 收缩。

    - 基础：capex_growth_ttm（>30 扩张 / <0 收缩 / 之间平稳，缺失→未知）；
    - 化工行业（化学原料/化学纤维/农化）叠加实体供给指标：开工率≥75 且库存≥30 天
      = 满产过剩（即便 capex 平稳也升级为供给扩张）；有开工率但未达阈值→维持 capex 判定。
    """
    chem_base = pl.col("industry_code").is_in(["220200", "220400", "220800"])
    has_chem = pl.col("chem_operating_rate").is_not_null()
    chem_over = (pl.col("chem_operating_rate") >= _CHEM_RATE_HIGH) & (
        pl.col("chem_inventory_days") >= _CHEM_INV_HIGH
    )
    return (
        pl.when(pl.col("capex_growth_ttm").is_null() & ~has_chem)
        .then(pl.lit("未知"))
        .when(chem_base & has_chem & chem_over)
        .then(pl.lit("供给扩张"))  # 满产+高库存 = 供给过剩风险
        .when(pl.col("capex_growth_ttm") > _CAPEX_HIGH)
        .then(pl.lit("供给扩张"))
        .when(pl.col("capex_growth_ttm") < _CAPEX_LOW)
        .then(pl.lit("供给收缩"))
        .otherwise(pl.lit("供给平稳"))
    )


def _quadrant_expr() -> pl.Expr:
    """供需象限 9 宫格标签（d_state × s_state）。"""
    return pl.col("d_state") + "|" + pl.col("s_state")


def _attach_scissors_morphology(base: pl.DataFrame) -> pl.DataFrame:
    """剪刀差形态诊断列（270100 实证口径，framework.md:142-152）。

    仅对 270100（半导体，SEAJ 设备出货供给腿）计算；其他行业形态参数未验证，
    一律中性（zone=NEUTRAL / diagnosis=NEUTRAL / days=-1）。连续区间口径对齐
    ``scratch/semi_scissors_signal_table.py``：LONG=scissors>+20、AVOID=scissors<-20，
    区间持续天数 = 组内交易日序号（1-based）。诊断优先级（AVOID 内）：
    供给洪峰型（供给分=100 且 >90 天）> 短触发（<10 天误报）> 需求仍强
    （需求分>65 且 <90 天误报）> 未分类。
    """
    has_scissors = all(
        col in base.columns for col in ["scissors_score", "supply_score", "demand_score"]
    )
    if not has_scissors:
        return base.with_columns(
            [
                pl.lit("NEUTRAL", dtype=pl.Utf8).alias("scissors_zone"),
                pl.lit(-1, dtype=pl.Int32).alias("scissors_zone_days"),
                pl.lit("NEUTRAL", dtype=pl.Utf8).alias("scissors_diagnosis"),
                pl.lit(-1, dtype=pl.Int32).alias("days_since_turn_negative"),
            ]
        )

    df = base.sort(["industry_code", "trade_date"]).with_columns(
        (pl.col("industry_code") != _MORPHOLOGY_SCOPE).alias("_out_of_scope"),
        pl.when(pl.col("scissors_score") > _SCISSORS_TH_POS)
        .then(pl.lit("LONG"))
        .when(pl.col("scissors_score") < _SCISSORS_TH_NEG)
        .then(pl.lit("AVOID"))
        .otherwise(pl.lit("NEUTRAL"))
        .alias("_zone"),
    )
    # 连续区间分组：zone 变化处 +1（按行业分组累计），组内行号 = 区间持续交易日数
    df = (
        df.with_columns(
            ((pl.col("_zone") != pl.col("_zone").shift(1)).fill_null(True)).alias("_zone_change")
        )
        .with_columns(
            pl.col("_zone_change").cum_sum().over("industry_code").alias("_zone_id"),
        )
        .with_columns(
            (pl.int_range(0, pl.len()).over(["industry_code", "_zone_id"]) + 1).alias("_zone_days"),
        )
    )
    # 转负窗口：每次剪刀差回正（>=0）组号 +1，组内行号 = 自回正以来天数（负区间内 1-based）
    df = (
        df.with_columns((pl.col("scissors_score") >= 0.0).alias("_non_neg"))
        .with_columns(
            pl.col("_non_neg").cum_sum().over("industry_code").alias("_turn_grp"),
        )
        .with_columns(
            (pl.int_range(0, pl.len()).over(["industry_code", "_turn_grp"]) + 1).alias(
                "_turn_days"
            ),
        )
    )

    diagnosis = (
        pl.when(pl.col("_out_of_scope"))
        .then(pl.lit("NEUTRAL"))
        .when((pl.col("_zone") == "LONG") & (pl.col("_zone_days") >= _LONG_SUSTAIN_MIN_DAYS))
        .then(pl.lit("LONG_SUSTAINED"))
        .when(pl.col("_zone") == "LONG")
        .then(pl.lit("LONG_SHORT"))
        .when(
            (pl.col("_zone") == "AVOID")
            & (pl.col("supply_score") == _SUPPLY_PEAK_SCORE)
            & (pl.col("_zone_days") > _AVOID_PEAK_MIN_DAYS)
        )
        .then(pl.lit("AVOID_SUPPLY_PEAK"))
        .when((pl.col("_zone") == "AVOID") & (pl.col("_zone_days") < _AVOID_SHORT_MAX_DAYS))
        .then(pl.lit("AVOID_SHORT"))
        .when(
            (pl.col("_zone") == "AVOID")
            & (pl.col("demand_score") > _DEMAND_STRONG_SCORE)
            & (pl.col("_zone_days") < _AVOID_PEAK_MIN_DAYS)
        )
        .then(pl.lit("AVOID_DEMAND_STRONG"))
        .when(pl.col("_zone") == "AVOID")
        .then(pl.lit("AVOID_UNCLASSIFIED"))
        .otherwise(pl.lit("NEUTRAL"))
    )

    return df.with_columns(
        [
            pl.when(pl.col("_out_of_scope"))
            .then(pl.lit("NEUTRAL"))
            .otherwise(pl.col("_zone"))
            .alias("scissors_zone"),
            pl.when(pl.col("_out_of_scope"))
            .then(pl.lit(-1))
            .otherwise(pl.col("_zone_days"))
            .cast(pl.Int32)
            .alias("scissors_zone_days"),
            diagnosis.alias("scissors_diagnosis"),
            pl.when(pl.col("_out_of_scope") | pl.col("_non_neg"))
            .then(pl.lit(-1))
            .otherwise(pl.col("_turn_days"))
            .cast(pl.Int32)
            .alias("days_since_turn_negative"),
        ]
    ).drop(
        [
            "_out_of_scope",
            "_zone",
            "_zone_change",
            "_zone_id",
            "_zone_days",
            "_non_neg",
            "_turn_grp",
            "_turn_days",
        ]
    )


def empty_industry_l2_panel() -> pl.DataFrame:
    """返回稳定 schema 的空申万二级行业基本面面板。"""
    return pl.DataFrame(schema=INDUSTRY_L2_PANEL_SCHEMA)


def _cs_percentile(col: str) -> pl.Expr:
    """横截面百分位: (rank - 1) / (count - 1) * 100，空值取中性 50。"""
    return (
        (
            (pl.col(col).rank(method="average").over("trade_date") - 1.0)
            / (pl.col(col).count().over("trade_date") - 1.0)
            * 100.0
        )
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def expand_l2_financial(frame: pl.DataFrame) -> pl.DataFrame:
    """把理杏仁 L2 财务嵌套字段展开为营收/净利 TTM 同比与毛利率事实列。

    ``frame`` 需要含 ``reportDate`` / ``symbol`` 与嵌套 ``q`` 结构：
    ``q.ps.toi.ttm_y2y``（营收同比）、``q.ps.np.ttm_y2y``（净利同比）、
    ``q.ps.gp_m.ttm``（毛利率，仅非金融源；银行/证券/保险无此字段 → null）。
    输出列：``eff_date``（发布日）/ ``industry_code`` / 三个事实列。
    """
    if frame.is_empty():
        return pl.DataFrame(
            schema={
                "eff_date": pl.Date,
                "industry_code": pl.Utf8,
                "revenue_growth_ttm": pl.Float64,
                "profit_growth_ttm": pl.Float64,
                "gross_margin_ttm": pl.Float64,
            }
        )
    from stock_analytics.marts.shared.industry_structure.panel_sources import _q_metric_ttm_expr

    q = pl.col("q")
    # gp_m 仅在非金融源存在：从 schema 探测 ps 子结构是否含 gp_m 字段
    q_fields = getattr(frame.schema["q"], "fields", [])  # Struct dtype 才含 fields
    ps_dtype = next((f.dtype for f in q_fields if f.name == "ps"), None)
    ps_fields = getattr(ps_dtype, "fields", []) if ps_dtype is not None else []
    has_gp = any(f.name == "gp_m" for f in ps_fields)
    select_cols = [
        pl.col("reportDate").alias("eff_date"),
        pl.col("symbol").cast(pl.Utf8, strict=False).alias("industry_code"),
        _q_metric_ttm_expr(frame, "toi").alias("revenue_growth_ttm"),
        _q_metric_ttm_expr(frame, "np").alias("profit_growth_ttm"),
    ]
    if has_gp:
        select_cols.append(
            q.struct.field("ps").struct.field("gp_m").struct.field("ttm").alias("gross_margin_ttm")
        )
    else:
        select_cols.append(pl.lit(None, dtype=pl.Float64).alias("gross_margin_ttm"))
    return (
        frame.select(select_cols)
        .drop_nulls(subset=["revenue_growth_ttm", "profit_growth_ttm"])
        .sort(["industry_code", "eff_date"])
    )


def load_l2_financial_frame(cat_lx: Any) -> pl.DataFrame:
    """从理杏仁加载非金融与三大金融行业事实并合并展开（含 TTM 差分重建）。

    ``ttm_y2y`` 源端缺失（2021-2023 报告期）时由累计值 ``t`` 差分重建并标注
    ``official / derived / proxy`` 口径；下游只消费数值列，口径列用于审计。
    """
    from stock_analytics.marts.shared.industry_structure.financial_ttm_rebuild import (
        expand_financial_with_ttm_rebuild,
    )

    expanded: list[pl.DataFrame] = []
    for ds in (
        "sw_2021_l2_fs_non_financial",
        "sw_2021_l2_fs_bank",
        "sw_2021_l2_fs_security",
        "sw_2021_l2_fs_insurance",
    ):
        part = cat_lx.load_dataset(
            ds, columns=["reportDate", "symbol", "reportType", "standardDate", "q"]
        )
        if not part.is_empty():
            expanded.append(expand_financial_with_ttm_rebuild(part))
    return pl.concat(expanded) if expanded else pl.DataFrame()


def build_industry_l2_panel_frame(
    l2_daily: pl.DataFrame,
    l2_financial: pl.DataFrame,
    *,
    l2_capex: pl.DataFrame | None = None,
    direction_map: pl.DataFrame | None = None,
    chemical_market: pl.DataFrame | None = None,
    percentile_cutoff: date | None = None,
) -> pl.DataFrame:
    """合并二级行业行情与 L2 财务黄金表及资本开支事实，输出基本面面板。

    ``l2_daily`` 为 ``industry_l2_daily`` Mart（含 ``trade_date``/``industry_code``/
    ``industry_name``/``parent_l1_code``/``parent_l1_name``/``close``/``amount_yi``/
    ``return_20d``/``return_60d``/``pe_ttm_ew_percentile_5y``/``pb_ew_percentile_5y``）；
    ``l2_financial`` 为 :func:`expand_l2_financial` 展开后的事实帧（``eff_date``/
    ``industry_code``/``revenue_growth_ttm``/``profit_growth_ttm``/``gross_margin_ttm``）。
    ``l2_capex`` 为二级行业资本开支事实长表（``eff_date``/``industry_code``/``cip_yoy``/
    ``fix_assets_yoy``/``cip_to_fa_ratio``/``capex_growth_ttm``/``inventory_scissors``）。
    ``direction_map`` 为二级行业方向分长表（``trade_date``/``industry_code``/
    ``direction_score``，来自 ``global_resonance_l2_map.parquet``），缺失回退中性 50；
    为 None 时方向层保持中性。
    ``percentile_cutoff`` 传入时仅输出该日期及之后行（增量构建语义）。
    """
    if l2_daily.is_empty():
        return empty_industry_l2_panel()

    base = l2_daily.select(
        [
            "trade_date",
            "industry_code",
            "industry_name",
            "parent_l1_code",
            "parent_l1_name",
            "close",
            "amount_yi",
            "return_20d",
            "return_60d",
            "pe_ttm_ew_percentile_5y",
            "pb_ew_percentile_5y",
        ]
    ).sort(["trade_date", "industry_code"])

    # 方向与供需剪刀差层：global_resonance_l2_map（理杏仁码）
    # 附带 leg_type（信号腿供需属性：demand/price/supply/finance）与各通道分值
    if direction_map is not None and not direction_map.is_empty():
        wanted_cols = ["trade_date", "industry_code", "direction_score"]
        for opt in ["leg_type", "demand_score", "supply_score", "price_score", "scissors_score"]:
            if opt in direction_map.columns:
                wanted_cols.append(opt)
        base = base.join(
            direction_map.select(wanted_cols),
            on=["trade_date", "industry_code"],
            how="left",
        ).with_columns(
            pl.col("direction_score").fill_null(_DIRECTION_NEUTRAL).alias("direction_score")
        )
        if "leg_type" not in base.columns:
            base = base.with_columns(pl.lit("demand").alias("leg_type"))
        if "demand_score" not in base.columns:
            base = base.with_columns(pl.col("direction_score").alias("demand_score"))
        else:
            base = base.with_columns(
                pl.col("demand_score").fill_null(_DIRECTION_NEUTRAL).alias("demand_score")
            )
        if "supply_score" not in base.columns:
            base = base.with_columns(pl.lit(50.0, dtype=pl.Float64).alias("supply_score"))
        else:
            base = base.with_columns(pl.col("supply_score").fill_null(50.0).alias("supply_score"))
        if "price_score" not in base.columns:
            base = base.with_columns(pl.lit(None, dtype=pl.Float64).alias("price_score"))
        if "scissors_score" not in base.columns:
            base = base.with_columns(
                (pl.col("demand_score") - pl.col("supply_score")).alias("scissors_score")
            )
        else:
            base = base.with_columns(
                pl.col("scissors_score").fill_null(0.0).alias("scissors_score")
            )
    else:
        base = base.with_columns(
            pl.lit(_DIRECTION_NEUTRAL, dtype=pl.Float64).alias("direction_score"),
            pl.lit("demand", dtype=pl.Utf8).alias("leg_type"),
            pl.lit(_DIRECTION_NEUTRAL, dtype=pl.Float64).alias("demand_score"),
            pl.lit(50.0, dtype=pl.Float64).alias("supply_score"),
            pl.lit(None, dtype=pl.Float64).alias("price_score"),
            pl.lit(0.0, dtype=pl.Float64).alias("scissors_score"),
        )

    # 剪刀差形态诊断（连续区间扫描 + 形态标签 + 转负窗口；仅 270100 有效）
    base = _attach_scissors_morphology(base)

    # 资本开支先导与库存特征 (PIT backward join)
    if l2_capex is not None and not l2_capex.is_empty():
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*Sortedness of columns.*")
            base = base.sort("trade_date").join_asof(
                l2_capex.sort("eff_date"),
                left_on="trade_date",
                right_on="eff_date",
                by="industry_code",
                strategy="backward",
            )
    else:
        base = base.with_columns(
            [
                pl.lit(None, dtype=pl.Float64).alias("cip_yoy"),
                pl.lit(None, dtype=pl.Float64).alias("fix_assets_yoy"),
                pl.lit(None, dtype=pl.Float64).alias("cip_to_fa_ratio"),
                pl.lit(None, dtype=pl.Float64).alias("capex_growth_ttm"),
                pl.lit(None, dtype=pl.Float64).alias("inventory_scissors"),
            ]
        )

    # 化工实体供给指标（chemical_market：NBS 官方产量与期货注册仓单，按月对齐化工行业）
    if chemical_market is not None and not chemical_market.is_empty():
        cm_cols = ["month_start"]
        if "soda_ash_production" in chemical_market.columns:
            cm_cols.append("soda_ash_production")
        for column in ("soda_ash_operating_rate", "pta_operating_rate"):
            if column in chemical_market.columns:
                cm_cols.append(column)
        if "chemical_inventory_days" in chemical_market.columns:
            cm_cols.append("chemical_inventory_days")

        cm = (
            chemical_market.rename({"trade_date": "_cm_date"})
            .with_columns(pl.col("_cm_date").dt.month_start().alias("month_start"))
            .select(cm_cols)
        )
        operating_rate_columns = [
            column
            for column in ("soda_ash_operating_rate", "pta_operating_rate")
            if column in cm.columns
        ]
        if operating_rate_columns:
            cm = cm.with_columns(
                pl.coalesce([pl.col(column) for column in operating_rate_columns]).alias(
                    "chem_operating_rate"
                )
            )
        else:
            cm = cm.with_columns(pl.lit(None, dtype=pl.Float64).alias("chem_operating_rate"))

        if "chemical_inventory_days" in cm.columns:
            cm = cm.rename({"chemical_inventory_days": "chem_inventory_days"})
        else:
            cm = cm.with_columns(pl.lit(None, dtype=pl.Float64).alias("chem_inventory_days"))

        base = (
            base.with_columns(pl.col("trade_date").dt.month_start().alias("month_start"))
            .join(cm, on="month_start", how="left")
            .drop("month_start")
        )
        # 仅化工行业保留开工率/库存，其他行业置空；月频数据按行业前向填充
        base = base.sort(["industry_code", "trade_date"]).with_columns(
            pl.when(pl.col("industry_code").is_in(["220200", "220400", "220800"]))
            .then(pl.col("chem_operating_rate"))
            .otherwise(None)
            .alias("chem_operating_rate"),
            pl.when(pl.col("industry_code").is_in(["220200", "220400", "220800"]))
            .then(pl.col("chem_inventory_days"))
            .otherwise(None)
            .alias("chem_inventory_days"),
        )
        base = base.with_columns(
            pl.col("chem_operating_rate")
            .fill_null(strategy="forward")
            .alias("chem_operating_rate"),
            pl.col("chem_inventory_days")
            .fill_null(strategy="forward")
            .alias("chem_inventory_days"),
        )
        # 非化工行业强制置空（避免 forward fill 跨行业串值）；化工行业 2018 前（数据起始前）保持 null
        base = base.with_columns(
            pl.when(pl.col("industry_code").is_in(["220200", "220400", "220800"]))
            .then(pl.col("chem_operating_rate"))
            .otherwise(None)
            .alias("chem_operating_rate"),
            pl.when(pl.col("industry_code").is_in(["220200", "220400", "220800"]))
            .then(pl.col("chem_inventory_days"))
            .otherwise(None)
            .alias("chem_inventory_days"),
        )
    else:
        base = base.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("chem_operating_rate"),
            pl.lit(None, dtype=pl.Float64).alias("chem_inventory_days"),
        )

    if l2_financial.is_empty():
        # 无财务数据：供需/议价权中性，仅输出行情/动量/拥挤度/资本开支 + 供需象限
        out = base.with_columns(
            [
                pl.lit(None, dtype=pl.Float64).alias("revenue_growth_ttm"),
                pl.lit(None, dtype=pl.Float64).alias("profit_growth_ttm"),
                pl.lit(None, dtype=pl.Float64).alias("gross_margin_ttm"),
                pl.lit(_DIRECTION_NEUTRAL, dtype=pl.Float64).alias("supply_demand_score"),
                pl.lit(_BARGAINING_NEUTRAL, dtype=pl.Float64).alias("bargaining_score"),
                _cs_percentile("amount_yi").alias("crowding_score"),
                _demand_state_expr().alias("d_state"),
                _supply_state_expr().alias("s_state"),
            ]
        ).with_columns(_quadrant_expr().alias("quadrant"))
        return out.select(list(INDUSTRY_L2_PANEL_SCHEMA))

    # 报告期滞后：每日取「已发布的最新报告期」（交易日 >= 发布日，按行业分组）
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*Sortedness of columns.*")
        joined = base.sort("trade_date").join_asof(
            l2_financial.sort("eff_date"),
            left_on="trade_date",
            right_on="eff_date",
            by="industry_code",
            strategy="backward",
        )

    # 0. 中间列：营收/净利增速（空值视为 0）、量价齐升门、毛利率扩张代理
    rev = pl.col("revenue_growth_ttm").fill_null(0.0)
    prof = pl.col("profit_growth_ttm").fill_null(0.0)
    base2 = joined.with_columns(
        [
            rev.alias("_rev"),
            prof.alias("_prof"),
            (rev + prof).alias("_rev_plus_prof"),
            (prof - rev).alias("_margin_expand"),
            ((rev > 0.0) & (prof > 0.0)).alias("_quality"),
        ]
    )

    # 1. 财报滞后验证 · 量价齐升（营收 + 净利双正）才是真需求驱动
    supply_demand = (
        pl.when(pl.col("_quality"))
        .then(_cs_percentile("_rev_plus_prof"))
        .when(pl.col("_prof") > 0.0)  # 供给收缩（营收负、净利正）：假繁荣，惩罚
        .then(pl.lit(_SUPPLY_CONTRACT_PENALTY))
        .otherwise(pl.lit(_DOUBLE_NEGATIVE_PENALTY))  # 双负
    )
    # 2. 议价权：量价齐升门内的毛利率扩张（净利增速 > 营收增速）
    bargaining = (
        pl.when(pl.col("_quality"))
        .then(_cs_percentile("_margin_expand"))
        .otherwise(pl.lit(_BARGAINING_NEUTRAL))
    )

    result = base2.with_columns(
        [
            supply_demand.clip(0.0, 100.0).alias("supply_demand_score"),
            bargaining.clip(0.0, 100.0).alias("bargaining_score"),
            _cs_percentile("amount_yi").alias("crowding_score"),
            _demand_state_expr().alias("d_state"),
            _supply_state_expr().alias("s_state"),
        ]
    ).with_columns(_quadrant_expr().alias("quadrant"))
    result = result.drop(["_rev", "_prof", "_rev_plus_prof", "_margin_expand", "_quality"])

    result = result.select(list(INDUSTRY_L2_PANEL_SCHEMA)).sort(["trade_date", "industry_code"])
    if percentile_cutoff is not None:
        result = result.filter(pl.col("trade_date") >= percentile_cutoff)
    return result


__all__ = [
    "INDUSTRY_L2_PANEL_MART_NAME",
    "build_industry_l2_panel_frame",
    "empty_industry_l2_panel",
    "expand_l2_financial",
    "load_l2_financial_frame",
]
