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
    return (
        series.to_frame("v")
        .select(
            pl.col("v").rolling_map(
                lambda x: float((x <= x[-1]).mean()) * 100.0, window_size=window
            )
        )["v"]
        .fill_nan(50.0)
        .fill_null(50.0)
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


def _monthly_pct(df: pl.DataFrame, value_col: str, window_months: int = 36) -> pl.DataFrame:
    """月频序列 → YoY → 滚动分位（月频，trade_date 对齐）。"""
    out = (
        df.select(["trade_date", value_col])
        .sort("trade_date")
        .with_columns(pl.col(value_col).pct_change(12).alias("yoy"))
        .drop_nulls()
    )
    pct = _rolling_pct(out["yoy"].cast(pl.Float64), window=window_months)
    return out.with_columns(pct.alias("pct")).select(["trade_date", "pct"])


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


def build_global_resonance_map() -> pl.DataFrame:
    """各腿方向分 × 申万行业 → global_resonance_map 长表。"""
    sox_dir = build_sox_direction()
    ne_dir = build_new_energy_direction()

    rows = []
    for code in _AI_INDUSTRIES:
        rows.append(sox_dir.with_columns(pl.lit(code).alias("industry_code")))
    for code, daily in ne_dir.items():
        rows.append(daily.with_columns(pl.lit(code).alias("industry_code")))
    return pl.concat(rows).select(["trade_date", "industry_code", "direction_score"])


# 主题 → 方向信号（sw_level2 二级行业归属 → 全球景气代理）
_THEME_SIGNAL: dict[str, str] = {
    "半导体": "semi",  # SOX + 全球半导体销售额
    "通信设备": "semi",
    "计算机设备": "semi",
    "光伏设备": "solar",  # 光伏装机
    "新能源": "solar",
    "电池": "nev",  # 新能源车销量
    "汽车": "nev",
    "有色": "",  # 待能源金属价格信号
}


def build_theme_signals() -> dict[str, pl.DataFrame]:
    """主题方向信号（日频）：semi / solar / nev。"""
    semi = build_sox_direction()  # trade_date, direction_score
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
    out: dict[str, pl.DataFrame] = {"semi": semi}
    for key, monthly in [("solar", solar_monthly), ("nev", nev_monthly)]:
        daily = (
            gm.join(monthly, on="trade_date", how="left")
            .sort("trade_date")
            .with_columns(pl.col("pct").fill_null(strategy="forward").alias("direction_score"))
            .select(["trade_date", "direction_score"])
            .drop_nulls()
        )
        out[key] = daily
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


if __name__ == "__main__":
    main()
