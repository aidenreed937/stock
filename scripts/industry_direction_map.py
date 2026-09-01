"""生成全球共振方向层映射表 global_resonance_map.parquet。

方向层口径（实证见 data/analytics/industry_strategy/industry_direction_layer.md）：
- direction_score = 全球产业景气代理的滚动分位合成（0-100）；
- 实证结论（AI 腿）：direction 与科技行业未来 60 日收益显著负相关 → 语义为「风险信号/防守」，
  在因子面板中作防守门（高位 × 非量价齐升 → 减分），不用于进攻加分。

映射腿：
- AI 算力腿：电子/通信/计算机 ← SOX（费半，日频三口径滚动分位合成）；
- 新能源腿：电力设备/有色 ← 光伏装机 + 新能源车销量（月频 YoY 滚动分位合成）。

输出：data/curated/mart/global_resonance_map.parquet
列：trade_date, industry_code, direction_score
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_data.catalog.service import DataCatalog

# 方向映射：申万行业 ← 全球景气代理腿（行业专属信号，不合成后复用）
# - AI 算力：电子/通信/计算机 ← SOX（费半）
# - 新能源-电力设备：光伏装机 ← 制造端（光伏设备/电池/电网设备）
# - 新能源-汽车：新能源车销量 ← 整车需求端
# 有色金属仅"能源金属"子板块相关，需能源金属价格信号，当前无对应数据故不映射。
_AI_INDUSTRIES = ["801080.SI", "801770.SI", "801750.SI"]  # 电子/通信/计算机
_OUTPUT = Path("data/curated/mart/global_resonance_map.parquet")


def _rolling_pct(series: pl.Series, window: int = 756) -> pl.Series:
    """滚动历史分位 (0-100)：每个时点在过去 window 天内的分位。"""
    s = series.fill_nan(0.0).fill_null(0.0)
    return (
        s.to_frame("v")
        .select(
            pl.col("v").rolling_map(
                lambda x: float((x <= x[-1]).mean()) * 100.0 if len(x) > 0 else 50.0,
                window_size=window,
                min_samples=1,
            )
        )["v"]
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def build_semi_lead_direction() -> pl.DataFrame:
    """半导体领先腿：台积电月营收 (3MMA YoY) → 滚动分位 → 日频方向得分。

    数据源：data/curated/industry/semiconductor_lead.parquet（台积电月度营收，
    半导体景气**领先指标**——晶圆代工订单先行于下游销售）。
    月频腿 release_date 生效（次月 10 日披露），无前视。
    """
    cat = DataCatalog(data_source="industry")
    try:
        lead = cat.load_dataset("semiconductor_lead")
    except Exception:
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})
    if lead.is_empty():
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})

    col = (
        "tsmc_revenue_3mma_usd"
        if "tsmc_revenue_3mma_usd" in lead.columns
        else "tsmc_revenue_usd_million"
    )
    monthly = _monthly_pct(lead, col)
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    return (
        gm.join(monthly, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("pct").fill_null(strategy="forward").alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def build_semi_sales_direction() -> pl.DataFrame:
    """全球半导体销售额腿 (SIA 全球销售额 YoY) → 滚动分位 → 日频方向得分。

    数据源：data/curated/industry/semiconductor_sales.parquet（SIA 全球半导体销售额，
    半导体景气**同步确认**指标——下游真实销售兑现，与 SOX 市价、台积电订单领先互补）。
    月频腿 release_date 生效（次月末披露），无前视。
    """
    cat = DataCatalog(data_source="industry")
    try:
        sales = cat.load_dataset("semiconductor_sales")
    except Exception:
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})
    if sales.is_empty():
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})

    monthly = _monthly_pct(sales, "global_sales_usd")
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    return (
        gm.join(monthly, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("pct").fill_null(strategy="forward").alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def build_sox_direction() -> pl.DataFrame:
    """AI 算力腿：SOX 相对 200 日均线偏离 / 20 日动量 / 60 日变化 的滚动分位合成（日频）。"""
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date", "sox_close"])
        .drop_nulls()
        .sort("trade_date")
    )
    sox = gm.with_columns(
        pl.col("sox_close").rolling_mean(window_size=200).alias("ma200"),
        pl.col("sox_close").log().diff(20).alias("mom20"),
        pl.col("sox_close").log().diff(60).alias("chg60"),
    ).with_columns(((pl.col("sox_close") / pl.col("ma200") - 1.0) * 100.0).alias("ma_bias"))
    return (
        sox.with_columns(
            _rolling_pct(sox["ma_bias"].cast(pl.Float64)).alias("d1"),
            _rolling_pct(sox["mom20"].cast(pl.Float64)).alias("d2"),
            _rolling_pct(sox["chg60"].cast(pl.Float64)).alias("d3"),
        )
        .select(["trade_date", "d1", "d2", "d3"])
        .with_columns(pl.mean_horizontal(["d1", "d2", "d3"]).alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def _compose_customs_leg(
    product_keys: list[str],
    gm: pl.DataFrame,
    fallback: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """海关品类出口腿公共合成：多品类 3MMA YoY 滚动分位取均值 → 日频前向填充。

    ``product_keys`` 为 customs_trade 中要合成的品类；``gm`` 为交易日历；
    数据缺失/空帧时返回 ``fallback``（默认空帧，调用方据此回退中性 50）。
    """
    if fallback is None:
        fallback = pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})
    cat = DataCatalog(data_source="industry")
    try:
        customs = cat.load_dataset("customs_trade", dedup=False)
    except Exception:
        return fallback
    if customs.is_empty() or "product_key" not in customs.columns:
        return fallback

    sub = (
        customs.filter(pl.col("product_key").is_in(product_keys))
        .group_by(["product_key", "trade_date"])
        .agg(
            pl.col("export_value_3mma").max().alias("export_value_3mma"),
            pl.col("release_date").max().alias("release_date"),
        )
        .sort(["product_key", "trade_date"])
    )
    if sub.is_empty():
        return fallback

    scores: list[pl.DataFrame] = []
    for product in sorted(sub["product_key"].unique().to_list()):
        p_sub = sub.filter(pl.col("product_key") == product)
        monthly = _monthly_pct(p_sub, "export_value_3mma")
        daily = (
            gm.join(monthly, on="trade_date", how="left")
            .sort("trade_date")
            .with_columns(pl.col("pct").fill_null(strategy="forward").alias(f"{product}_score"))
            .select(["trade_date", f"{product}_score"])
            .drop_nulls()
        )
        scores.append(daily)
    if not scores:
        return fallback

    merged = scores[0]
    for s in scores[1:]:
        merged = merged.join(s, on="trade_date", how="full", coalesce=True)
    score_cols = [c for c in merged.columns if c.endswith("_score")]
    merged = merged.with_columns(
        [pl.col(c).fill_null(strategy="forward").fill_null(50.0) for c in score_cols]
    )
    return (
        merged.with_columns(pl.mean_horizontal(score_cols).alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def _monthly_pct(df: pl.DataFrame, value_col: str, window_months: int = 36) -> pl.DataFrame:
    """月频序列 → YoY → 滚动分位（月频，trade_date 对齐）。

    生效日语义（消除前视）：数据源含 release_date 时按**发布日**生效（月末数据在
    发布日之后才可用，如海关出口滞后约 20 天）；无 release_date 时回退 trade_date。
    """
    eff_col = "release_date" if "release_date" in df.columns else "trade_date"
    extra = [eff_col] if eff_col != "trade_date" else []
    out = (
        df.select(["trade_date", *extra, value_col])
        .sort("trade_date")
        .with_columns(pl.col(value_col).pct_change(12).alias("yoy"))
        .drop_nulls()
    )
    pct = _rolling_pct(out["yoy"].cast(pl.Float64), window=window_months)
    return (
        out.with_columns(pct.alias("pct")).select([eff_col, "pct"]).rename({eff_col: "trade_date"})
    )


def _quarterly_pct(df: pl.DataFrame, value_col: str, window_quarters: int = 12) -> pl.DataFrame:
    """季频序列 → YoY → 滚动分位（季频，trade_date 对齐）。

    生效日语义（消除前视）：数据源含 release_date 时按**发布日**生效，否则回退 trade_date。
    """
    eff_col = "release_date" if "release_date" in df.columns else "trade_date"
    extra = [eff_col] if eff_col != "trade_date" else []
    if "yoy_growth" in df.columns and df["yoy_growth"].is_not_null().any():
        out = (
            df.select(["trade_date", *extra, "yoy_growth"])
            .rename({"yoy_growth": "yoy"})
            .drop_nulls()
            .sort("trade_date")
        )
    else:
        out = (
            df.select(["trade_date", *extra, value_col])
            .sort("trade_date")
            .with_columns(pl.col(value_col).pct_change(4).alias("yoy"))
            .drop_nulls()
        )
    pct = _rolling_pct(out["yoy"].cast(pl.Float64), window=window_quarters)
    return (
        out.with_columns(pct.alias("pct")).select([eff_col, "pct"]).rename({eff_col: "trade_date"})
    )


def build_new_energy_direction() -> dict[str, pl.DataFrame]:
    """新能源腿：行业专属信号（月频 → 日频前向填充）。

    - 电力设备 ← 光伏装机 YoY 分位（制造端：光伏设备/电池/电网设备）
    - 汽车 ← 新能源车销量 YoY 分位（整车需求端）
    制造端信号不再合成后映射多个行业，按行业归属拆分。
    """
    cat = DataCatalog(data_source="industry")
    solar = cat.load_dataset("solar_capacity")
    nev = cat.load_dataset("nev_monthly_sales")

    solar_col = (
        "monthly_new_capacity_3mma"
        if "monthly_new_capacity_3mma" in solar.columns
        else "monthly_new_capacity_gw"
    )
    signals = {
        "801730.SI": _monthly_pct(solar, solar_col),  # 电力设备 ← 光伏装机
        "801880.SI": _monthly_pct(nev, "wholesale_volume_ten_thousand"),  # 汽车 ← 新能源车销量
    }

    # 月频 → 日频：对齐到交易日（前向填充）
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    result: dict[str, pl.DataFrame] = {}
    for code, monthly in signals.items():
        daily = (
            gm.join(monthly, on="trade_date", how="left")
            .sort("trade_date")
            .with_columns(pl.col("pct").fill_null(strategy="forward").alias("direction_score"))
            .select(["trade_date", "direction_score"])
            .drop_nulls()
        )
        result[code] = daily
    return result


def build_metals_direction() -> dict[str, pl.DataFrame]:
    """有色大宗腿：铜/碳酸锂价格动量与偏离度（日频）。

    - 有色金属 / 工业金属 ← 铜价偏离度 + 动量分位
    - 能源金属 ← 碳酸锂动量分位
    """
    cat = DataCatalog(data_source="industry")
    try:
        metals = cat.load_dataset("non_ferrous_metals")
    except Exception:
        return {}
    if metals.is_empty():
        return {}

    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    result: dict[str, pl.DataFrame] = {}

    if "copper_ma200_bias" in metals.columns and "copper_mom20" in metals.columns:
        cu_sub = metals.filter(pl.col("shfe_copper_price").is_not_null())
        if len(cu_sub) > 0:
            d1 = _rolling_pct(cu_sub["copper_ma200_bias"].cast(pl.Float64))
            d2 = _rolling_pct(cu_sub["copper_mom20"].cast(pl.Float64))
            cu_scored = cu_sub.with_columns(((d1 + d2) / 2.0).alias("direction_score")).select(
                ["trade_date", "direction_score"]
            )
            daily_cu = (
                gm.join(cu_scored, on="trade_date", how="left")
                .sort("trade_date")
                .with_columns(pl.col("direction_score").fill_null(strategy="forward"))
                .drop_nulls()
            )
            result["801050.SI"] = daily_cu  # 申万一级: 有色金属
            result["metals"] = daily_cu

    if "lithium_mom20" in metals.columns:
        li_sub = metals.filter(pl.col("lithium_carbonate_price").is_not_null())
        if len(li_sub) > 0:
            d_li = _rolling_pct(li_sub["lithium_mom20"].cast(pl.Float64))
            li_scored = li_sub.with_columns(d_li.alias("direction_score")).select(
                ["trade_date", "direction_score"]
            )
            daily_li = (
                gm.join(li_scored, on="trade_date", how="left")
                .sort("trade_date")
                .with_columns(pl.col("direction_score").fill_null(strategy="forward"))
                .drop_nulls()
            )
            result["lithium"] = daily_li

    return result


def build_gold_direction() -> pl.DataFrame:
    """贵金属/黄金腿：COMEX 黄金期货日频 200MA 偏离度 / 20 日动量 / 60 日变化的滚动分位合成。"""
    try:
        gm = (
            pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
            .select(["trade_date", "gold_price"])
            .drop_nulls()
            .sort("trade_date")
        )
    except Exception:
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})
    if gm.is_empty():
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})

    gold = gm.with_columns(
        pl.col("gold_price").rolling_mean(window_size=200).alias("ma200"),
        pl.col("gold_price").log().diff(20).alias("mom20"),
        pl.col("gold_price").log().diff(60).alias("chg60"),
    ).with_columns(((pl.col("gold_price") / pl.col("ma200") - 1.0) * 100.0).alias("ma_bias"))
    return (
        gold.with_columns(
            _rolling_pct(gold["ma_bias"].cast(pl.Float64)).alias("d1"),
            _rolling_pct(gold["mom20"].cast(pl.Float64)).alias("d2"),
            _rolling_pct(gold["chg60"].cast(pl.Float64)).alias("d3"),
        )
        .select(["trade_date", "d1", "d2", "d3"])
        .with_columns(pl.mean_horizontal(["d1", "d2", "d3"]).alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def build_transformer_direction() -> pl.DataFrame:
    """海关变压器月度出口金额 (3MMA) → 滚动分位数 → 日频方向得分。"""
    cat = DataCatalog(data_source="industry")
    try:
        customs = cat.load_dataset("customs_trade", dedup=False)
        if not customs.is_empty() and "product_key" in customs.columns:
            transformer = (
                customs.filter(pl.col("product_key") == "transformer")
                .group_by(["report_month", "trade_date"])
                .agg(
                    pl.col("export_value_3mma").sum().alias("export_value_3mma"),
                    pl.col("export_value_usd").sum().alias("export_value_usd"),
                )
                .sort("trade_date")
            )
        else:
            transformer = cat.load_dataset("transformer_export")
    except Exception:
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})
    if transformer.is_empty():
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})

    col = (
        "export_value_3mma"
        if "export_value_3mma" in transformer.columns
        else (
            "export_value_usd"
            if "export_value_usd" in transformer.columns
            else "export_value_million_usd"
        )
    )
    monthly = _monthly_pct(transformer, col)
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    return (
        gm.join(monthly, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("pct").fill_null(strategy="forward").alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def build_pharma_bd_direction() -> pl.DataFrame:
    """中国创新药海外 License-out (BD) 首付款 (3MMA) → 滚动分位数 → 日频方向得分。

    数据源：data/curated/industry/pharma_license_out.parquet（月度 BD 汇总）。
    前视处理：月度 BD 交易在当月才公告/披露，全月汇总次月才完整可用——把 release_date
    推到**次月**生效（当月数据最早次月可消费），与海关月频腿（次月 20 日）同语义。
    """
    cat = DataCatalog(data_source="industry")
    try:
        pharma = cat.load_dataset("pharma_license_out")
    except Exception:
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})
    if pharma.is_empty():
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})

    # 生效日推到次月（release_date 原为月末，+1 月 → 次月同日；_monthly_pct 用 release_date 生效）
    pharma = pharma.with_columns(pl.col("release_date").dt.offset_by("1mo").alias("release_date"))
    col = "upfront_3mma" if "upfront_3mma" in pharma.columns else "monthly_upfront_million_usd"
    monthly = _monthly_pct(pharma, col)
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    return (
        gm.join(monthly, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("pct").fill_null(strategy="forward").alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def build_consumer_electronics_direction() -> pl.DataFrame:
    """消费电子腿: 全球智能手机 + PC 出货量季频同比 → 滚动分位 → 日频方向得分。

    数据源: data/curated/industry/consumer_electronics.parquet (IDC/Canalys 季度出货,
    AI 终端需求全球代理)。季频 release_date 生效, 无前视; 双腿合成对齐 optical 口径。
    """
    cat = DataCatalog(data_source="industry")
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    try:
        ce = cat.load_dataset("consumer_electronics")
    except Exception:
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})
    if ce.is_empty():
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})

    legs: list[pl.DataFrame] = []
    for col in ("global_smartphone_shipments_million", "global_pc_shipments_million"):
        if col not in ce.columns:
            continue
        quarterly = _quarterly_pct(ce, col)
        daily = (
            gm.join(quarterly, on="trade_date", how="left")
            .sort("trade_date")
            .with_columns(pl.col("pct").fill_null(strategy="forward").alias(f"{col}_score"))
            .select(["trade_date", f"{col}_score"])
            .drop_nulls()
        )
        legs.append(daily)
    if not legs:
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})

    merged = legs[0]
    for s in legs[1:]:
        merged = merged.join(s, on="trade_date", how="full", coalesce=True)
    score_cols = [c for c in merged.columns if c.endswith("_score")]
    return (
        merged.with_columns(pl.mean_horizontal(score_cols).alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def build_optical_direction() -> pl.DataFrame:
    """海关光模块出口金额 (3MMA) + 北美云厂商 CapEx 同比 → 复合日频方向得分。"""
    cat = DataCatalog(data_source="industry")
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    optical_daily = None
    try:
        customs = cat.load_dataset("customs_trade", dedup=False)
        if not customs.is_empty() and "product_key" in customs.columns:
            optical = customs.filter(pl.col("product_key") == "optical_module")
        else:
            optical = cat.load_dataset("optical_module_export")
        if not optical.is_empty():
            col = (
                "export_value_3mma"
                if "export_value_3mma" in optical.columns
                else (
                    "export_value_usd"
                    if "export_value_usd" in optical.columns
                    else "export_value_million_usd"
                )
            )
            opt_monthly = _monthly_pct(optical, col)
            optical_daily = (
                gm.join(opt_monthly, on="trade_date", how="left")
                .sort("trade_date")
                .with_columns(pl.col("pct").fill_null(strategy="forward").alias("opt_score"))
                .select(["trade_date", "opt_score"])
            )
    except Exception:
        optical_daily = None

    capex_daily = None
    try:
        capex = cat.load_dataset("cloud_capex_quarterly")
        if not capex.is_empty():
            col_c = "total_capex_billion_usd"
            capex_quarterly = _quarterly_pct(capex, col_c)
            capex_daily = (
                gm.join(capex_quarterly, on="trade_date", how="left")
                .sort("trade_date")
                .with_columns(pl.col("pct").fill_null(strategy="forward").alias("capex_score"))
                .select(["trade_date", "capex_score"])
            )
    except Exception:
        capex_daily = None

    if optical_daily is not None and capex_daily is not None:
        merged = optical_daily.join(capex_daily, on="trade_date", how="full", coalesce=True).sort(
            "trade_date"
        )
        merged = (
            merged.with_columns(
                pl.col("opt_score").fill_null(strategy="forward").fill_null(50.0),
                pl.col("capex_score").fill_null(strategy="forward").fill_null(50.0),
            )
            .with_columns(
                ((pl.col("opt_score") + pl.col("capex_score")) / 2.0).alias("direction_score")
            )
            .select(["trade_date", "direction_score"])
            .drop_nulls()
        )
        return merged
    if optical_daily is not None:
        return optical_daily.rename({"opt_score": "direction_score"}).drop_nulls()
    if capex_daily is not None:
        return capex_daily.rename({"capex_score": "direction_score"}).drop_nulls()
    return build_sox_direction()


def build_chemicals_direction() -> pl.DataFrame:
    """化工品出口腿：钛白粉 + 聚合 MDI 出口金额 3MMA YoY → 滚动分位 → 日频方向得分。

    数据源：data/curated/industry/customs_trade.parquet（UN Comtrade + GACC 双源，
    product_key ∈ {tio2, mdi}，品类级 3MMA/YoY 已按多税号聚合，跨 HS 版本连续）。
    合成：各品种 3MMA 同比滚动分位取均值（对齐 optical 双腿合成）。数据缺失时返回空帧
    （对应行业方向分回退中性 50，不阻塞其他行业）。
    """
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    return _compose_customs_leg(["tio2", "mdi"], gm)


def build_medical_device_direction() -> pl.DataFrame:
    """医疗设备出口腿：医疗设备出口金额 3MMA YoY → 滚动分位 → 日频方向得分。

    数据源：data/curated/industry/customs_trade.parquet（UN Comtrade + GACC 双源，
    product_key ∈ {medical_device}，品类级 3MMA/YoY 已按多税号聚合）。
    合成：各品类 3MMA 同比滚动分位取均值（对齐 chemicals 双腿合成）。数据缺失时返回空帧
    （对应行业方向分回退中性 50，不阻塞其他行业）。
    """
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    return _compose_customs_leg(["medical_device"], gm)


def build_pharma_export_direction() -> pl.DataFrame:
    """药品出口腿：化学药制剂 + 疫苗出口金额 3MMA YoY → 滚动分位 → 日频方向得分。

    数据源：data/curated/industry/customs_trade.parquet（UN Comtrade + GACC 双源，
    product_key ∈ {pharma_chemicals, pharma_vaccines}，HS30 章药品出口外需代理）。
    合成：各品类 3MMA 同比滚动分位取均值（对齐 chemicals 双腿合成）。数据缺失时返回空帧
    （对应行业方向分回退中性 50，不阻塞其他行业）。
    """
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    return _compose_customs_leg(["pharma_chemicals", "pharma_vaccines"], gm)


def build_machinery_direction() -> pl.DataFrame:
    """工程机械月度产销 (3MMA) → 滚动分位数 → 日频方向得分。"""
    cat = DataCatalog(data_source="industry")
    try:
        mach = cat.load_dataset("construction_machinery")
    except Exception:
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})
    if mach.is_empty():
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})

    col = (
        "excavator_total_3mma"
        if "excavator_total_3mma" in mach.columns
        else "excavator_total_units"
    )
    monthly = _monthly_pct(mach, col)
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    return (
        gm.join(monthly, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("pct").fill_null(strategy="forward").alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def build_shipping_direction() -> pl.DataFrame:
    """全球海运与油运运价指数 (BDI/BDTI 相对 MA200 偏离度) → 滚动分位数 → 日频方向得分。"""
    cat = DataCatalog(data_source="industry")
    try:
        ship = cat.load_dataset("shipping_indices")
    except Exception:
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})
    if ship.is_empty():
        return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})

    ship = ship.sort("trade_date")
    if "bdi_ma200_bias" in ship.columns and ship["bdi_ma200_bias"].is_not_null().any():
        d1 = _rolling_pct(ship["bdi_ma200_bias"].cast(pl.Float64))
    else:
        d1 = _rolling_pct(ship["bdi_index"].cast(pl.Float64))

    if "bdti_ma200_bias" in ship.columns and ship["bdti_ma200_bias"].is_not_null().any():
        d2 = _rolling_pct(ship["bdti_ma200_bias"].cast(pl.Float64))
    else:
        d2 = d1

    return (
        ship.with_columns(
            d1.alias("d1"),
            d2.alias("d2"),
        )
        .with_columns(pl.mean_horizontal(["d1", "d2"]).alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def build_global_resonance_map() -> pl.DataFrame:
    """各腿方向分 × 申万行业 → global_resonance_map 长表。"""
    sox_dir = build_sox_direction()
    ne_dir = build_new_energy_direction()
    metals_dir = build_metals_direction()
    transformer_dir = build_transformer_direction()
    pharma_dir = build_pharma_bd_direction()
    optical_dir = build_optical_direction()
    mach_dir = build_machinery_direction()
    ship_dir = build_shipping_direction()
    gold_dir = build_gold_direction()

    rows = []
    # 电子 (801080.SI) / 计算机 (801750.SI) 沿用 SOX 全球算力芯片方向
    for code in ["801080.SI", "801750.SI"]:
        rows.append(sox_dir.with_columns(pl.lit(code).alias("industry_code")))
    for code, daily in ne_dir.items():
        rows.append(daily.with_columns(pl.lit(code).alias("industry_code")))
    if "801050.SI" in metals_dir:
        rows.append(
            metals_dir["801050.SI"].with_columns(pl.lit("801050.SI").alias("industry_code"))
        )
    if not gold_dir.is_empty():
        rows.append(gold_dir.with_columns(pl.lit("801053.SI").alias("industry_code")))  # 贵金属
    if not transformer_dir.is_empty():
        rows.append(transformer_dir.with_columns(pl.lit("801732.SI").alias("industry_code")))
    if not pharma_dir.is_empty():
        rows.append(pharma_dir.with_columns(pl.lit("801150.SI").alias("industry_code")))  # 医药生物
        rows.append(pharma_dir.with_columns(pl.lit("801151.SI").alias("industry_code")))  # 化学制药
        rows.append(pharma_dir.with_columns(pl.lit("801153.SI").alias("industry_code")))  # 生物制品
    if not optical_dir.is_empty():
        rows.append(optical_dir.with_columns(pl.lit("801770.SI").alias("industry_code")))  # 通信
        rows.append(
            optical_dir.with_columns(pl.lit("801771.SI").alias("industry_code"))
        )  # 通信设备
    if not mach_dir.is_empty():
        rows.append(mach_dir.with_columns(pl.lit("801720.SI").alias("industry_code")))  # 机械设备
        rows.append(mach_dir.with_columns(pl.lit("801721.SI").alias("industry_code")))  # 工程机械
    if not ship_dir.is_empty():
        rows.append(ship_dir.with_columns(pl.lit("801170.SI").alias("industry_code")))  # 交通运输
        rows.append(ship_dir.with_columns(pl.lit("801171.SI").alias("industry_code")))  # 航运港口

    return pl.concat(rows).select(["trade_date", "industry_code", "direction_score"])


def build_global_resonance_l2_map() -> pl.DataFrame:
    """二级行业方向分：_THEME_L2_CODE × _THEME_SIGNAL → global_resonance_l2_map 长表。

    与一级 ``global_resonance_map``（申万官方 801xxx.SI 码）并行，输出**理杏仁 6 位码**
    口径（对齐 ``industry_l2_daily`` / ``industry_l2_panel_daily``），支持二级行业与
    主题 ETF 穿透。信号腿缺失（如 machinery/shipping 数据未落盘）自动跳过，不阻塞
    其他行业；输出列：``trade_date`` / ``industry_code`` / ``direction_score`` /
    ``leg_type``（信号腿供需属性：demand/supply/price/finance，来自
    ``_SIGNAL_LEG_SUPPLY_DEMAND``，供供需象限因子与数据审计消费）。
    """
    signals = build_theme_signals()
    rows: list[pl.DataFrame] = []
    skipped: list[str] = []
    for theme, code in sorted(_THEME_L2_CODE.items()):
        signal_key = _THEME_SIGNAL.get(theme, "")
        if not signal_key or signal_key not in signals:
            skipped.append(f"{theme}({code})")
            continue
        rows.append(
            signals[signal_key].with_columns(
                pl.lit(code).alias("industry_code"),
                pl.lit(_SIGNAL_LEG_SUPPLY_DEMAND.get(signal_key, "demand")).alias("leg_type"),
            )
        )
    print(f"无方向信号的二级行业（跳过）: {skipped or '无'}")
    if not rows:
        return pl.DataFrame(
            schema={
                "trade_date": pl.Date,
                "industry_code": pl.Utf8,
                "direction_score": pl.Float64,
                "leg_type": pl.Utf8,
            }
        )
    return pl.concat(rows).select(["trade_date", "industry_code", "direction_score", "leg_type"])


# 主题 → 方向信号（sw_level2 二级行业归属 → 全球景气代理）
_THEME_SIGNAL: dict[str, str] = {
    "半导体": "semi",  # SOX + 全球半导体销售额
    "通信设备": "optical",  # 海关光模块出口 + 北美云厂商 CapEx
    "通信": "optical",
    "光模块": "optical",
    "计算机设备": "semi",
    "计算机": "semi",  # watchlist sw_level2 标签（512720.SH 计算机 ETF）
    "光伏设备": "solar",  # 光伏装机
    "新能源": "solar",
    "电池": "nev",  # 新能源车销量
    "汽车": "nev",
    "有色": "metals",  # 有色大宗/铜价信号
    "有色金属": "metals",
    "工业金属": "metals",
    "贵金属": "gold",  # COMEX 黄金期货日频分位
    "黄金": "gold",
    "能源金属": "lithium",
    "电网设备": "transformer",  # 海关变压器出口
    "电网": "transformer",
    "医药生物": "pharma_bd",  # 创新药出海 BD
    "创新药": "pharma_bd",
    "化学制药": "pharma_bd",  # 创新药出海 License-out BD 首付款（台账已采集）
    "生物制品": "pharma_bd",
    "工程机械": "machinery",  # CCMA 挖机产销与小松工时
    "机械设备": "machinery",
    "机械": "machinery",
    "航运港口": "shipping",  # BDI / BDTI 海运与油运运价
    "航运": "shipping",
    "交通运输": "shipping",
    "交运": "shipping",
    "化工": "chemicals",  # 海关化工品出口（钛白粉 + 聚合 MDI）
    "基础化工": "chemicals",
    "化学原料": "chemicals",
    "化学制品": "chemicals",
    "化学纤维": "chemicals",
    "农化制品": "chemicals",
    "塑料": "chemicals",
    "医疗服务": "medical_device",  # 海关医疗设备出口（CXO/医疗服务全球需求代理）
    "医疗器械": "medical_device",
    "医疗": "medical_device",
    "消费电子": "consumer_electronics",  # 全球手机/PC 出货（AI 终端需求）
}


# 主题名（sw_level2）→ 理杏仁申万二级行业 6 位码（industry_l2_daily / industry_l2_panel_daily 口径）
# 规范主题名才映射独立行业码；别名（通信/新能源/有色/医药生物等）不重复映射。
_THEME_L2_CODE: dict[str, str] = {
    "半导体": "270100",
    "通信设备": "730200",
    "计算机设备": "710100",
    "光伏设备": "630500",
    "电池": "630700",
    "汽车": "280500",  # 乘用车（整车需求端）
    "电网设备": "630800",
    "工业金属": "240300",
    "贵金属": "240400",
    "化学制药": "370100",
    "生物制品": "370300",
    "工程机械": "640600",
    "航运港口": "421100",
    "化学原料": "220200",
    "化学制品": "220300",
    "化学纤维": "220400",
    "农化制品": "220800",
    "塑料": "220500",
    "医疗服务": "370600",
    "消费电子": "270500",
}

# 信号腿供需属性注册表（结构化元数据，替代散在注释中的语义）：
#   demand  = 全球需求景气代理（订单/销量/装机/出口等外需方向）
#   supply  = 供给/产能扩张信号（capex 等，供象限因子供给态消费）
#   price   = 全球价格/运价（供需平衡的价格反映）
#   finance = A 股财务口径（量价齐升/议价权，供需结果的财务确认）
_SIGNAL_LEG_SUPPLY_DEMAND: dict[str, str] = {
    "semi": "demand",  # SOX/全球半导体销售额（全球算力需求）
    "optical": "demand",  # 光模块出口 + 北美云厂 Capex（采购需求）
    "solar": "demand",  # 光伏装机（装机端需求，非产能）
    "nev": "demand",  # 新能源车销量（终端需求）
    "metals": "price",  # 铜价（全球工业需求 + 金融属性）
    "lithium": "price",  # 碳酸锂价格
    "gold": "price",  # COMEX 黄金期货（避险需求 + 金融属性）
    "transformer": "demand",  # 海关变压器出口（海外电网采购）
    "pharma_bd": "demand",  # 创新药出海 BD（跨国药企采购）
    "machinery": "demand",  # 挖机产销/小松工时（基建矿山活动）
    "shipping": "price",  # BDI/BDTI 运价（贸易活跃度价格反映）
    "chemicals": "demand",  # 海关化工品出口（海外化工需求）
    "medical_device": "demand",  # 海关医疗设备出口（海外采购）
    "pharma_export": "demand",  # HS30 章药品出口（化学药制剂/疫苗，海外采购）
    "consumer_electronics": "demand",  # 全球手机/PC 出货量（终端需求）
}


def build_theme_signals() -> dict[str, pl.DataFrame]:
    """主题方向信号（日频）：semi / optical / solar / nev / metals / lithium / transformer / pharma_bd / machinery / shipping / gold / chemicals / medical_device。"""
    semi = build_sox_direction()  # trade_date, direction_score
    semi_lead = build_semi_lead_direction()  # 台积电月营收（半导体领先腿）
    semi_sales = build_semi_sales_direction()  # SIA 全球销售额（半导体同步腿）
    # 合成：SOX（日频）+ 台积电（月频领先）+ SIA 全球销售额（月频同步）→ 市价/订单/销售三确认
    legs = [("lead", semi_lead), ("sales", semi_sales)]
    if any(not leg.is_empty() for _, leg in legs):
        merged = semi
        for name, leg in legs:
            if leg.is_empty():
                continue
            merged = merged.join(
                leg.rename({"direction_score": name}), on="trade_date", how="left"
            )
        fill_cols = [name for name, leg in legs if not leg.is_empty()]
        merged = (
            merged.sort("trade_date")
            .with_columns([pl.col(c).fill_null(strategy="forward") for c in fill_cols])
            .drop_nulls(subset=fill_cols)
            .with_columns(
                pl.mean_horizontal(["direction_score", *fill_cols]).alias("direction_score")
            )
            .select(["trade_date", "direction_score"])
            .drop_nulls()
        )
        semi = merged
    optical = build_optical_direction()
    machinery = build_machinery_direction()
    shipping = build_shipping_direction()
    gold = build_gold_direction()
    chemicals = build_chemicals_direction()
    medical_device = build_medical_device_direction()
    pharma_export = build_pharma_export_direction()
    consumer_electronics = build_consumer_electronics_direction()
    cat = DataCatalog(data_source="industry")
    solar = cat.load_dataset("solar_capacity")
    nev = cat.load_dataset("nev_monthly_sales")
    solar_col = (
        "monthly_new_capacity_3mma"
        if "monthly_new_capacity_3mma" in solar.columns
        else "monthly_new_capacity_gw"
    )
    solar_monthly = _monthly_pct(solar, solar_col)
    nev_monthly = _monthly_pct(nev, "wholesale_volume_ten_thousand")

    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    out: dict[str, pl.DataFrame] = {
        "semi": semi,
        "optical": optical,
        "machinery": machinery,
        "shipping": shipping,
    }
    if not gold.is_empty():
        out["gold"] = gold
    for key, monthly in [("solar", solar_monthly), ("nev", nev_monthly)]:
        daily = (
            gm.join(monthly, on="trade_date", how="left")
            .sort("trade_date")
            .with_columns(pl.col("pct").fill_null(strategy="forward").alias("direction_score"))
            .select(["trade_date", "direction_score"])
            .drop_nulls()
        )
        out[key] = daily

    metals_dir = build_metals_direction()
    if "metals" in metals_dir:
        out["metals"] = metals_dir["metals"]
    if "lithium" in metals_dir:
        out["lithium"] = metals_dir["lithium"]

    transformer_dir = build_transformer_direction()
    if not transformer_dir.is_empty():
        out["transformer"] = transformer_dir

    pharma_dir = build_pharma_bd_direction()
    if not pharma_dir.is_empty():
        out["pharma_bd"] = pharma_dir

    if not chemicals.is_empty():
        out["chemicals"] = chemicals

    if not medical_device.is_empty():
        out["medical_device"] = medical_device

    if not pharma_export.is_empty():
        out["pharma_export"] = pharma_export

    if not consumer_electronics.is_empty():
        out["consumer_electronics"] = consumer_electronics

    return out


def _avg_amount_by_etf(etf_codes: list[str]) -> dict[str, float]:
    """近 60 日日均成交额（元）作为 ETF 规模/流动性代理。"""
    from stock_data.catalog import DataCatalog

    try:
        fund = DataCatalog(data_source="tushare").load_dataset(
            "fund_daily", symbols=etf_codes, columns=["symbol", "trade_date", "amount"]
        )
        if fund.is_empty():
            return {}
        return {
            str(r["symbol"]): float(r["amount"])
            for r in fund.sort("trade_date")
            .group_by("symbol")
            .tail(60)
            .group_by("symbol")
            .agg(pl.col("amount").mean())
            .to_dicts()
        }
    except Exception:
        return {}


def load_theme_etfs() -> dict[str, str]:
    """从 watchlist 读取标记了 sw_level2 的 ETF（etf_symbol → 二级行业归属）。

    同一二级行业多只 ETF 时，优先选 base_date 早（历史长）、规模大（日均成交额）的代表。
    """
    from pathlib import Path as _Path

    import yaml

    cfg = yaml.safe_load(_Path("config/universe/watchlist.yaml").read_text(encoding="utf-8"))
    funds = cfg["universe"]["a_shares"]["funds"]
    tagged = [
        (str(f["code"]), str(f["sw_level2"]), str(f.get("base_date", "9999-99-99")))
        for f in funds
        if isinstance(f, dict) and f.get("sw_level2")
    ]
    if not tagged:
        return {}

    scale = _avg_amount_by_etf([t[0] for t in tagged])
    groups: dict[str, list[tuple[str, str]]] = {}
    for code, theme, base_date in tagged:
        groups.setdefault(theme, []).append((code, base_date))

    result: dict[str, str] = {}
    for theme, items in sorted(groups.items()):
        items.sort(key=lambda x: (x[1], -scale.get(x[0], 0.0)))
        result[items[0][0]] = theme
    return result


def build_theme_etf_direction() -> pl.DataFrame:
    """ETF 级方向分：信号 → 主题 → 观察池内方向层主题 ETF。

    输出列：trade_date, etf_symbol, theme（sw_level2）, direction_score。
    """
    theme_etfs = load_theme_etfs()
    signals = build_theme_signals()
    rows: list[pl.DataFrame] = []
    skipped: list[str] = []
    for etf, theme in sorted(theme_etfs.items()):
        signal_key = _THEME_SIGNAL.get(theme, "")
        if not signal_key or signal_key not in signals:
            skipped.append(f"{etf}({theme})")
            continue
        rows.append(
            signals[signal_key].with_columns(
                pl.lit(etf).alias("etf_symbol"),
                pl.lit(theme).alias("theme"),
            )
        )
    print(f"无方向信号的主题 ETF（跳过）: {skipped or '无'}")
    return pl.concat(rows).select(["trade_date", "etf_symbol", "theme", "direction_score"])


def build_and_save_theme_etf_direction() -> pl.DataFrame:
    """构建并保存 ETF 级方向分到 data/curated/mart/theme_etf_direction.parquet。"""
    df = build_theme_etf_direction()
    out = Path("data/curated/mart/theme_etf_direction.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out)
    print(f"theme_etf_direction 已生成: {out}")
    print(f"行数: {len(df)}, ETF: {sorted(df['etf_symbol'].unique().to_list())}")
    print(f"日期: {df['trade_date'].min()} ~ {df['trade_date'].max()}")
    return df


def main() -> None:
    map_df = build_global_resonance_map()
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    map_df.write_parquet(_OUTPUT)
    print(f"global_resonance_map 已生成: {_OUTPUT}")
    print(f"行数: {len(map_df)}, 行业: {sorted(map_df['industry_code'].unique().to_list())}")
    print(f"日期: {map_df['trade_date'].min()} ~ {map_df['trade_date'].max()}")
    for code in sorted(map_df["industry_code"].unique().to_list()):
        sub = map_df.filter(pl.col("industry_code") == code)
        print(
            f"  {code}: {len(sub)} 行, direction "
            f"min={sub['direction_score'].min():.1f} max={sub['direction_score'].max():.1f} "
            f"mean={sub['direction_score'].mean():.1f}"
        )
    build_and_save_theme_etf_direction()

    # 二级行业方向分（理杏仁 6 位码口径，供 industry_l2_panel_daily 消费）
    l2_map = build_global_resonance_l2_map()
    l2_out = Path("data/curated/mart/global_resonance_l2_map.parquet")
    l2_out.parent.mkdir(parents=True, exist_ok=True)
    l2_map.write_parquet(l2_out)
    print(f"\nglobal_resonance_l2_map 已生成: {l2_out}")
    print(f"行数: {len(l2_map)}, 行业: {sorted(l2_map['industry_code'].unique().to_list())}")
    print(f"日期: {l2_map['trade_date'].min()} ~ {l2_map['trade_date'].max()}")
    for code in sorted(l2_map["industry_code"].unique().to_list()):
        sub = l2_map.filter(pl.col("industry_code") == code)
        print(
            f"  {code}: {len(sub)} 行, direction "
            f"min={sub['direction_score'].min():.1f} max={sub['direction_score'].max():.1f} "
            f"mean={sub['direction_score'].mean():.1f}"
        )


if __name__ == "__main__":
    main()
