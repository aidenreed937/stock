"""海关出口数量的单位归一化与量价分离工具。

背景（2026-09 核查发现）：
1. 42/106 产品跨 HS/数据源混用计量单位（``units`` vs ``台`` vs ``个`` vs ``kg`` vs
   ``千克`` vs ``辆`` vs ``艘`` vs ``块`` vs ``sqm``），直接对 ``export_volume``
   求和会得到无意义的混合单位数量。
2. 部分行业出口金额被价格主导（乘用车/医疗器械/半导体/电池/化学制药/炼化等
   量价相关 <0.5），金额 yoy 不是纯"量"信号。

本模块提供：
- :func:`normalize_quantity_unit`：单位同义归一（kg↔千克 等），供数量聚合前调用；
- :func:`flag_volume_aggregable`：产品级"数量可加总"标注（真混用/未知单位 → 不可加总）；
- :func:`industry_volume_price_corr`：行业级 金额yoy × 数量yoy 相关性（量价分离度），
  用于判定哪些行业的金额信号被价格污染。
"""

from __future__ import annotations

import math

import polars as pl

#: 同义单位归一映射（target → canonical）
UNIT_CANONICAL = {
    "千克": "kg",
    "公斤": "kg",
    "千克(kg)": "kg",
    "台": "units",
    "个": "units",
    "辆": "units",
    "艘": "units",
    "块": "units",
    "件": "units",
    "套": "units",
    "只": "units",
    "台/套": "units",
    # UN Comtrade 计量单位代码（HS 计量单位，Comtrade 段主体，2026-09 补充）：
    # "u"=units（件/台/个/辆/艘，与 GACC 中文单位逐码对照一致，见 10 文档 §8）；
    # "l"=升（石油类按公升申报，2710 系）；"m²"=平方米；"条"=服装件数单位（GACC 报"条"）。
    "u": "units",
    "l": "l",
    "m²": "sqm",
    "条": "units",
    "立方米": "cbm",
    "米": "m",
    "平方米": "sqm",
    "平方千米": "sqkm",
    "吨": "ton",
    "千瓦": "kw",
}

#: 已知单位全集 = 可归一别名 ∪ 规范单位本身（规范形式无需映射即为已知）
KNOWN_UNITS = set(UNIT_CANONICAL) | set(UNIT_CANONICAL.values())

#: 已知真混用的产品（同产品不同 HS 使用不同物理单位，数量不可加总）
MIXED_UNIT_PRODUCTS = {
    "semiconductor_equipment",  # units vs kg
    "pcb",  # kg vs 块
    "auto_glass",  # sqm vs 千克
    "robot_vacuum",  # units vs 台 vs -
    "hydrogen_electrolyzer",  # units vs 台
    "shipbuilding",  # units vs 艘
    "wind_parts",  # kg vs 千克（可归一）
    "anode_material",  # kg vs 千克（可归一）
}


def normalize_quantity_unit(frame: pl.DataFrame) -> pl.DataFrame:
    """把 ``quantity_unit`` 归一为规范单位（``kg``/``units``/``sqm``/``ton`` 等）。

    同义单位（千克→kg、台/个/辆→units）归一后可安全加总；仍混用不同物理单位的
    产品（见 :data:`MIXED_UNIT_PRODUCTS`）数量加总仍无意义，由调用方按产品过滤。
    返回新帧（新增 ``quantity_unit_norm`` 列，不改原列）。
    """
    return frame.with_columns(
        pl.when(pl.col("quantity_unit").is_in(list(UNIT_CANONICAL.keys())))
        .then(pl.col("quantity_unit").replace_strict(UNIT_CANONICAL, default=None))
        .otherwise(pl.col("quantity_unit"))
        .alias("quantity_unit_norm"),
        pl.col("quantity_unit").is_in(KNOWN_UNITS).alias("unit_known"),
    )


def flag_volume_aggregable(
    frame: pl.DataFrame,
    *,
    product_col: str = "product_key",
    unit_col: str = "quantity_unit_norm",
    volume_col: str = "export_volume",
) -> pl.DataFrame:
    """产品级"数量可加总"标注（需先经 :func:`normalize_quantity_unit`）。

    判定：产品在其**有量行**（``volume_col > 0``，0 量占位如 N/A/mixed 不计）中，
    归一去重后恰好 1 个单位且单位已知（``unit_known`` 全真）→
    ``volume_aggregable=True``，数量可跨 HS 安全加总；
    真混用（归一后仍多物理单位，如半导体设备 units vs kg）或含未知单位
    （如 ``-``）→ ``False``，下游对 ``export_volume`` 求和前必须过滤或置空，
    否则得到无意义的混合单位数量。

    返回新帧（新增 ``volume_aggregable`` 布尔列，不改原列）。
    """
    prod = (
        frame.filter(pl.col(volume_col).is_not_null() & (pl.col(volume_col) > 0))
        .group_by(product_col)
        .agg(
            pl.col(unit_col).unique().alias("__units"),
            pl.col("unit_known").all().alias("__unit_known_all"),
        )
        .with_columns(pl.col("__units").list.len().alias("__n_units"))
        .with_columns(
            ((pl.col("__n_units") == 1) & pl.col("__unit_known_all")).alias("volume_aggregable")
        )
        .select(product_col, "volume_aggregable")
    )
    # 丢弃已存在的标注列，避免 join 产生 *_right 冲突列（可重复调用）
    return frame.drop("volume_aggregable", strict=False).join(prod, on=product_col, how="left")


def industry_volume_price_corr(
    monthly: pl.DataFrame,
    *,
    value_col: str = "export_value_usd",
    volume_col: str = "export_volume",
    min_samples: int = 18,
) -> pl.DataFrame:
    """行业级 金额yoy × 数量yoy 相关性（量价分离度）。

    ``monthly`` 需为 (industry_code, trade_date, value, volume) 的月度聚合帧
    （数量需先经 :func:`normalize_quantity_unit` + 单位过滤）。

    输出：每行业 ``corr_value_volume``（Pearson 相关）。
    - ``corr < 0.5`` → ``price_dominated=True``：金额被价格主导，金额 yoy 不是纯量信号（价格污染⚠）；
    - ``corr`` 为 null（数量缺失/为 0 导致 3MMA yoy 除零，或数量全置空）→
      ``volume_signal_ok=False``：数量信号不可用，不能用于量价判定。
    """
    out = []
    for code in monthly["industry_code"].unique().to_list():
        s = monthly.filter(pl.col("industry_code") == code).sort("trade_date")
        s = (
            s.with_columns(
                pl.col(value_col).rolling_mean(window_size=3, min_samples=3).alias("m_v"),
                pl.col(value_col)
                .rolling_mean(window_size=3, min_samples=3)
                .shift(12)
                .alias("m_vl"),
                pl.col(volume_col).rolling_mean(window_size=3, min_samples=3).alias("m_q"),
                pl.col(volume_col)
                .rolling_mean(window_size=3, min_samples=3)
                .shift(12)
                .alias("m_ql"),
            )
            .with_columns(
                ((pl.col("m_v") / pl.col("m_vl") - 1) * 100).alias("v_yoy"),
                ((pl.col("m_q") / pl.col("m_ql") - 1) * 100).alias("q_yoy"),
            )
            .drop_nulls(["v_yoy", "q_yoy"])
            .filter(
                # 数量为 0 时 3MMA yoy 除零产生 ±inf，会使 corr 退化为 NaN
                pl.col("v_yoy").is_finite() & pl.col("q_yoy").is_finite()
            )
        )
        if s.height < min_samples:
            continue
        c = s.select(pl.corr("v_yoy", "q_yoy")).to_series()[0]
        ok = c is not None and not math.isnan(c)
        out.append(
            {
                "industry_code": code,
                "corr_value_volume": round(c, 3) if ok else None,
                "n_samples": s.height,
                "price_dominated": bool(ok and c < 0.5),
                "volume_signal_ok": ok,
            }
        )
    return pl.DataFrame(out).sort("corr_value_volume")
