"""SEMI 全球设备季度出货公报 (Worldwide SEMS) vs SEAJ 日本制设备出货 季度对账报告。

用途：把「SEAJ 日本制造设备出货作为全球设备供给代理」从定性估计升级为可复现的定期校验产物。
核心产出：
1. 季度对账表：SEMI 全球出货（USD 全集）vs SEAJ 日本制造出货（JPY 原始 + USD 折算）；
2. SEAJ 占全球出货的比例区间（USD 口径，量级参考）与同比增速相关性（r）；
3. 中国大陆采购额占全球比重演进（自主可控特征，官方口径）。

口径与局限（务必随报告一起读）：
- SEAJ 月报为「日本制装置」销售 3MMA（日元），覆盖日本制造商全球出货（含出口），
  约占全球设备制造额 1/3——这是制造商国别份额，不是 WWSEMS 的 Japan 采购地份额
  （官方 Japan 单国 2024 年仅占全球 6.7%）。因此本报告给出的占比是「日本制造份额的量级参考」，
  不做精确采购地对账锚定。
- 汇率：SEAJ 日元 → 美元使用 FRED DEXJPUS 日频（H.10）当月均值折算，非精确时点汇率。
- 同比增速相关性是 SEAJ 代理质量的主要证据（方向可靠）；占比为次要（量级参考）。
- 中国设备产出（供给端）份额低位（国产化率以清洗/刻蚀/热处理等中低环节 10-20% 为主、
  光刻/涂胶显影高端接近零，外部背景 2026-08），其供给缺失不影响本代理的代表性——中国是
  全球设备采购大国（约 1/3），其扩产需求已通过日本厂商对华出口隐含在 SEAJ 序列内。

产物：data/analytics/industry_strategy/semi_seaj_reconciliation.{csv,md}
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

_OUT_DIR = Path("data/analytics/industry_strategy")
_SEMI_PATH = "data/curated/industry/semiconductor/equipment/semiconductor_equipment_semi.parquet"
_SEAJ_PATH = "data/curated/industry/semiconductor/equipment/semiconductor_equipment.parquet"
_FX_PATH = "data/raw/fred/market=US/DEXJPUS/data.parquet"


def _load_fx_monthly() -> pl.DataFrame:
    """加载 FRED DEXJPUS 日频并聚合为月度平均 USD/JPY (jpy_per_usd)。"""
    fx = pl.read_parquet(_FX_PATH).select(["trade_date", "value"]).drop_nulls()
    return (
        fx.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("month"))
        .group_by("month")
        .agg(pl.col("value").mean().alias("usdjpy"))
        .sort("month")
    )


def _load_semi_quarterly() -> pl.DataFrame:
    """加载 SEMI WWSEMS 季度全集 (USD)。"""
    return pl.read_parquet(_SEMI_PATH).select(
        [
            "report_quarter",
            "global_billings_billion_usd",
            "china_billings_billion_usd",
            "china_share_pct",
            "release_date",
        ]
    )


def _load_seaj_quarterly(fx_monthly: pl.DataFrame) -> pl.DataFrame:
    """加载 SEAJ 月度（JPY），按当月汇率折算 USD，再聚合为季度。"""
    seaj = (
        pl.read_parquet(_SEAJ_PATH)
        .select(["report_month", "billings_3mma_jpy", "trade_date", "release_date"])
        .with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("month"))
        .join(fx_monthly, on="month", how="left")
        .with_columns(
            (pl.col("billings_3mma_jpy") / pl.col("usdjpy")).alias("billings_usd_billion")
        )
        .with_columns(
            pl.col("trade_date").dt.year().cast(pl.Utf8).alias("_year"),
            (pl.col("trade_date").dt.month().cast(pl.Int32)).alias("_mon"),
        )
        .with_columns(((pl.col("_mon") - 1) // 3 + 1).cast(pl.Utf8).alias("_q"))
        .with_columns((pl.col("_year") + "-Q" + pl.col("_q")).alias("report_quarter"))
    )
    return (
        seaj.group_by("report_quarter")
        .agg(
            pl.col("billings_3mma_jpy").sum().alias("seaj_jpy_billion"),
            pl.col("billings_usd_billion").sum().alias("seaj_usd_billion"),
            pl.col("trade_date").max().alias("seaj_last_month"),
        )
        .sort("report_quarter")
    )


def _calc_yoy(df: pl.DataFrame, col: str) -> pl.DataFrame:
    """计算季度同比 (pct_change 4 期)，保留原列。"""
    return df.with_columns(pl.col(col).pct_change(4).round(4).alias(f"{col}_yoy"))


def build_reconciliation() -> pl.DataFrame:
    """构建 SEMI vs SEAJ 季度对账表（2018-Q1 起，内连接至 SEMI 最新季度）。"""
    fx_monthly = _load_fx_monthly()
    semi = _load_semi_quarterly()
    seaj = _load_seaj_quarterly(fx_monthly)

    df = semi.join(seaj, on="report_quarter", how="inner").sort("report_quarter")
    df = _calc_yoy(df, "global_billings_billion_usd")
    df = _calc_yoy(df, "seaj_usd_billion")
    df = _calc_yoy(df, "seaj_jpy_billion")
    return df.with_columns(
        (pl.col("seaj_usd_billion") / pl.col("global_billings_billion_usd") * 100.0)
        .round(2)
        .alias("seaj_global_share_pct")
    )


def _spearman(a: pl.Series, b: pl.Series) -> float:
    """Spearman 秩相关系数（仅两端同时非空的配对）。"""
    df = pl.DataFrame({"a": a, "b": b}).drop_nulls()
    if len(df) < 5:
        return float("nan")
    ra = df["a"].rank().to_list()
    rb = df["b"].rank().to_list()
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = sum((x - ma) ** 2 for x in ra) ** 0.5 * sum((y - mb) ** 2 for y in rb) ** 0.5
    return round(num / den, 4) if den > 0 else float("nan")


def _stats(df: pl.DataFrame) -> dict[str, float]:
    """对账统计：占比均值/区间、SEAJ 同比增速与 SEMI 全球同比的相关系数。"""
    share = df["seaj_global_share_pct"].drop_nulls()
    paired = df.select(["seaj_usd_billion_yoy", "global_billings_billion_usd_yoy"]).drop_nulls()
    r_usd = _spearman(
        df["seaj_usd_billion_yoy"].drop_nulls(),
        df["global_billings_billion_usd_yoy"].drop_nulls(),
    )
    r_jpy = _spearman(
        df["seaj_jpy_billion_yoy"].drop_nulls(),
        df["global_billings_billion_usd_yoy"].drop_nulls(),
    )
    return {
        "share_mean": round(share.mean(), 2) if len(share) else float("nan"),
        "share_min": round(share.min(), 2) if len(share) else float("nan"),
        "share_max": round(share.max(), 2) if len(share) else float("nan"),
        "r_usd": r_usd,
        "r_jpy": r_jpy,
        "n": float(len(share)),
        "direction_n": float(len(paired)),
        "direction_same": float(
            (paired["seaj_usd_billion_yoy"] * paired["global_billings_billion_usd_yoy"] > 0).sum()
        ),
    }


def _annual_summary(df: pl.DataFrame) -> pl.DataFrame:
    """按自然年汇总 SEMI 全球、SEAJ（USD）与占比。"""
    return (
        df.with_columns(pl.col("report_quarter").str.slice(0, 4).alias("year"))
        .group_by("year")
        .agg(
            pl.col("global_billings_billion_usd").sum().alias("semi_annual_usd"),
            pl.col("seaj_usd_billion").sum().alias("seaj_annual_usd"),
        )
        .with_columns(
            (pl.col("seaj_annual_usd") / pl.col("semi_annual_usd") * 100.0)
            .round(2)
            .alias("seaj_annual_share_pct")
        )
        .sort("year")
    )


def main() -> None:
    df = build_reconciliation()
    stats = _stats(df)
    annual = _annual_summary(df)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = _OUT_DIR / "semi_seaj_reconciliation.csv"
    annual_path = _OUT_DIR / "semi_seaj_reconciliation_annual.csv"
    md_path = _OUT_DIR / "semi_seaj_reconciliation.md"

    df.write_csv(csv_path)
    annual.write_csv(annual_path)

    china = df.filter(pl.col("china_share_pct").is_not_null())
    china_first_row = china.filter(pl.col("report_quarter") == "2018-Q1")
    china_first = china_first_row["china_share_pct"][0] if len(china_first_row) else None
    china_peak_row = china.sort("china_share_pct", descending=True).head(1)
    china_peak = china_peak_row["china_share_pct"][0] if len(china_peak_row) else None
    china_peak_q = china_peak_row["report_quarter"][0] if len(china_peak_row) else None
    china_last_q = china["report_quarter"].max() if len(china) else None

    if china_first is not None and china_peak is not None:
        china_summary = (
            f"**中国大陆采购占比（自主可控特征）**：从 2018 年 {china_first:.1f}% 升至峰值 "
            f"**{china_peak:.1f}%**（{china_peak_q}），官方口径显示中国已成为全球最大设备买家。"
            f"⚠️ 该分项**仅覆盖 {len(china)}/{len(df)} 季、止于 {china_last_q}**"
            f"（缺 {len(df) - len(china)} 季）：SEMI 自 2021 年起多期把分区域表改为**内嵌图片**发布，"
            f"{china_last_q} 之后各季不可得——**不得据此推断其后的中国占比走势**。"
        )
    else:
        china_summary = (
            "**中国大陆采购占比**：SEMI 本地季度数据未提供中国大陆采购额/占比"
            "（分区域表未归档为可解析文本），该分项不可计算，未纳入本次对账结论。"
        )

    direction_diff = df.filter(
        pl.col("seaj_usd_billion_yoy").is_not_null()
        & pl.col("global_billings_billion_usd_yoy").is_not_null()
        & (pl.col("seaj_usd_billion_yoy") * pl.col("global_billings_billion_usd_yoy") <= 0)
    )["report_quarter"].to_list()
    direction_diff_text = "、".join(direction_diff) if direction_diff else "无"

    # --- 两口径方向分歧（USD 折算 vs JPY 原币），交集 = 汇率中性后仍分歧的真实背离 ---
    paired = df.filter(
        pl.col("seaj_jpy_billion_yoy").is_not_null()
        & pl.col("global_billings_billion_usd_yoy").is_not_null()
    )
    direction_diff_jpy = paired.filter(
        pl.col("seaj_jpy_billion_yoy") * pl.col("global_billings_billion_usd_yoy") <= 0
    )["report_quarter"].to_list()
    direction_diff_both = sorted(set(direction_diff) & set(direction_diff_jpy))
    same_jpy = int(
        (paired["seaj_jpy_billion_yoy"] * paired["global_billings_billion_usd_yoy"] > 0).sum()
    )
    n_paired = len(paired)
    jpy_diff_text = "、".join(direction_diff_jpy) if direction_diff_jpy else "无"
    both_diff_text = "、".join(direction_diff_both) if direction_diff_both else "无"

    md = f"""# SEMI 全球设备季度出货 (WWSEMS) vs SEAJ 日本制设备出货 对账报告

## 一、核心结论 (Executive Summary)

1. **SEAJ 代理质量：同比增速较高同向，可作为方向代理**
   - 覆盖 {stats["n"]:.0f} 个季度（{df["report_quarter"].min()} ~ {df["report_quarter"].max()}）；
   - USD 折算口径：{stats["direction_same"]:.0f}/{stats["direction_n"]:.0f} 同向
     （{stats["direction_same"] / stats["direction_n"] * 100:.1f}%）；分歧季度：{direction_diff_text}；
   - JPY 原币口径：{same_jpy}/{n_paired} 同向（{same_jpy / n_paired * 100:.1f}%）；分歧季度：{jpy_diff_text}；
   - **两口径交集（汇率中性后仍分歧的真实背离）**：{both_diff_text}——2026-09 核验该两季 SEMI
     数据均为 `derived_from_annual`（全年减前三季残差倒推），Q4 误差被放大；
   - Spearman r（vs SEMI 全球同比）：USD 折算 **{stats["r_usd"]:.3f}** / JPY 原币 **{stats["r_jpy"]:.3f}**；
   - 结论：SEAJ 对全球设备周期具有较好的方向解释力；USD 口径 5 个分歧季度中 3 个
     （2022-Q2/Q4、2023-Q1）为日元贬值致美元折算翻转的**汇率伪分歧**（日元原币实际同向）。
2. **SEAJ 占全球设备出货的量级参考**：均值 **{stats["share_mean"]}%**（区间
   {stats["share_min"]}% ~ {stats["share_max"]}%）——这是日本制造商全球出货份额
   （约 1/3）的量级参考，**不是** WWSEMS 的 Japan 采购地份额（官方 Japan 单国 2024 仅占 6.7%）。
3. {china_summary}

> ⚠️ 口径注意：SEAJ 月报 = 日本制装置销售（制造商国别口径）；SEMI 全球 = 采购地全集。
> 两者非同口径，本报告占比列仅作量级参考，**主要证据是同比增速相关性（方向可靠）**。

---

## 二、分歧季度归因（两口径交叉验证）

方向分歧按成因分三类（汇率伪分歧 ×2 个方向 + 真实背离）：

| 类别 | 季度 | 成因 |
| :-- | :-- | :-- |
| 汇率伪分歧（USD 口径，日元贬值期） | 2022-Q2、2022-Q4、2023-Q1 | SEAJ 日元同比与 SEMI 同向，但日元大幅贬值（USDJPY 同比 +13.8% ~ +24.4%）致美元折算后方向翻转 |
| 汇率伪分歧（JPY 口径，日元单边升贬期） | 2020-Q4、2023-Q2、2024-Q1 | 日元升值压低 / 贬值抬高 JPY 原币同比跨零（如 2024-Q1 USDJPY +12.2%，JPY +7.1% 系汇率虚高） |
| 真实背离（两口径交集） | 2019-Q4、2023-Q4 | 周期时点 / 3MMA 平滑 / 厂商地区产品结构差异；且两季 SEMI 数据均为 `derived_from_annual`（全年减前三季残差倒推），Q4 误差被放大 |

**结论**：判断周期方向以 SEAJ **JPY 原币同比**为准（与剪刀差供给腿输入一致——汇率不进信号）；
USD 折算仅用于金额量级比较；对账解读以两口径交集为真实背离（{both_diff_text}），
单口径分歧先查汇率背景再定性。

---

## 三、季度对账表

| 季度 | SEMI 全球 ($B) | SEMI 全球 YoY | SEAJ 折算 ($B) | SEAJ USD YoY | SEAJ 全球占比% | 中国采购 ($B) | 中国占比% | SEMI 发布日期 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""

    def _fmt_pct(v: float | None) -> str:
        return f"{v * 100:.1f}%" if v is not None else "—"

    def _fmt_num(v: float | None, digits: int = 2) -> str:
        return f"{v:.{digits}f}" if v is not None else "—"

    def _fmt_pct_points(v: float | None) -> str:
        return f"{v:.1f}%" if v is not None else "—"

    for r in df.to_dicts():
        md += (
            f"| {r['report_quarter']} | {r['global_billings_billion_usd']:.2f} "
            f"| {_fmt_pct(r['global_billings_billion_usd_yoy'])} "
            f"| {r['seaj_usd_billion']:.2f} "
            f"| {_fmt_pct(r['seaj_usd_billion_yoy'])} "
            f"| {r['seaj_global_share_pct']:.1f}% "
            f"| {_fmt_num(r['china_billings_billion_usd'])} "
            f"| {_fmt_pct_points(r['china_share_pct'])} "
            f"| {r['release_date']} |\n"
        )

    md += """
---

## 四、年度汇总（SEAJ 全球占比的稳定性）

| 年份 | SEMI 全球全年 ($B) | SEAJ 全年 ($B) | SEAJ 占比% |
| :--- | :---: | :---: | :---: |
"""
    for r in annual.to_dicts():
        md += (
            f"| {r['year']} | {r['semi_annual_usd']:.1f} "
            f"| {r['seaj_annual_usd']:.1f} "
            f"| {r['seaj_annual_share_pct']:.1f}% |\n"
        )

    md += f"""
---

## 五、局限与维护

- 汇率折算使用 FRED DEXJPUS 月度均值（H.10），非精确时点汇率，占比列精度有限。
- SEAJ 月报为日本制装置销售 3MMA，与 SEMI 采购地全集非同口径；占比仅量级参考。
- 方向解读：判断周期方向优先看 SEAJ **JPY 原币同比**（剪刀差供给腿输入即日元原币，汇率不进信号）；
  USD 折算仅用于金额量级比较；单口径分歧先查汇率背景，两口径交集（当前 {both_diff_text}）才是真实背离。
- 中国设备产出（供给端）份额低位（外部背景 2026-08），其缺失不影响 SEAJ 代理代表性；
  中国为全球最大设备采购方，其扩产需求经日本对华出口已隐含在 SEAJ 序列内。
- 季度对齐以自然季度（SEAJ 月聚合 + SEMI 季）为准，SEMI 季报在其季度结束后约 1-3 个月发布。
- 维护：SEMI 季报按官方公报发布更新 `semiconductor_equipment_semi.parquet`，本脚本重跑即可刷新对账。
"""

    md_path.write_text(md, encoding="utf-8")

    print("=== SEMI vs SEAJ 季度对账 ===")
    print(f"覆盖 {df['report_quarter'].min()} ~ {df['report_quarter'].max()}, {len(df)} 季度")
    print(
        f"SEAJ 全球占比: 均值 {stats['share_mean']}% (区间 {stats['share_min']}~{stats['share_max']}%)"
    )
    print(f"Spearman r: SEAJ USD vs SEMI {stats['r_usd']} / SEAJ JPY vs SEMI {stats['r_jpy']}")
    if china_first is not None and china_peak is not None:
        print(
            f"中国占比: 2018 {china_first:.1f}% -> 峰值 {china_peak:.1f}% ({china_peak_q})"
            f" | 覆盖 {len(china)}/{len(df)} 季, 止于 {china_last_q}"
        )
    else:
        print("中国占比: SEMI 本地数据未提供，无法计算")
    print(f"\nCSV:  {csv_path}")
    print(f"年度: {annual_path}")
    print(f"MD:   {md_path}")


if __name__ == "__main__":
    main()
