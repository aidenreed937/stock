"""SOX（费城半导体指数）与本地半导体垂直产业黄金表相关性研究。

问题：费城半导体指数（SOX）和本地什么半导体产业数据相关？
口径：
- SOX 日频收盘来自 ``data/curated/mart/global_macro_daily.parquet``（^SOX），
  重采样为月频（月末最后交易日）后计算月收益（mom）与 12 个月动量（yoy12）。
- 本地半导体垂直产业黄金表位于 ``data/curated/industry/semiconductor/``，
  本脚本覆盖 5 大产研分类（sales/inventory/equipment/capacity/price）
  中满足最小样本门槛的全部可计算序列；
  ``semiconductor_memory_price``（仅 2 个 trade_date）与
  ``tsmc_cowos_capacity_estimates``（仅 7 期）样本不足，仅披露不参与相关。
- 相关性：Spearman（主）+ Pearson（辅）；同时做 SOX 月收益 vs 指标的
  领先-滞后相关（月频 ±6 月 / 季频 ±3 季）；区间拆分全样本 / 2018+ / 2023+（AI 时代）。
- 本脚本只做描述性相关研究，不构成交易信号；所有数值来自本地 Curated 黄金表
  （Ground Truth First），缺失与口径限制在输出中如实披露。

输出：
- data/analytics/semiconductor/sox_local_correlation/sox_local_corr_summary.csv
- data/analytics/semiconductor/sox_local_correlation/sox_local_corr_lag_matrix.csv
- data/analytics/semiconductor/sox_local_correlation/coverage.csv
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from scipy import stats

DATA_ROOT = Path("data")
SEMI_DIR = DATA_ROOT / "curated" / "industry" / "semiconductor"
GM_PATH = DATA_ROOT / "curated" / "mart" / "global_macro_daily.parquet"
OUT_DIR = DATA_ROOT / "analytics" / "semiconductor" / "sox_local_correlation"

MIN_N_MONTHLY = 24
MIN_N_QUARTERLY = 12
MONTHLY_LAGS = range(-6, 7)
QUARTERLY_LAGS = range(-3, 4)

WINDOWS = [
    ("full", None, None),
    ("since2018", "2018-01", None),
    ("since2023", "2023-01", None),
]

# 被排除的表及原因（样本不足，不参与相关计算）
EXCLUDED_TABLES = [
    ("semiconductor_memory_price", "price", "仅 2 个 trade_date 覆盖式快照，无法做时间序列相关"),
    ("tsmc_cowos_capacity_estimates", "capacity", "仅 7 期智库测算（forecast），样本不足"),
]


@dataclass
class Metric:
    name: str
    label: str
    category: str
    table: str
    freq: str
    frame: pl.DataFrame


def _read(name: str, subdir: str | None = None) -> pl.DataFrame:
    """按规范子路径优先、legacy 根路径兜底读取本地 Curated 表。"""
    if subdir:
        p = SEMI_DIR / subdir / f"{name}.parquet"
        if p.exists():
            return pl.read_parquet(p)
    legacy = DATA_ROOT / "curated" / "industry" / f"{name}.parquet"
    if legacy.exists():
        return pl.read_parquet(legacy)
    raise FileNotFoundError(f"未找到本地 Curated 表: {name}")


def _month_key(series: pl.Series) -> pl.Series:
    """把 report_month（String/Date 均可）规整为 'YYYY-MM'。"""
    return series.cast(pl.Utf8).str.extract(r"(\d{4}-\d{2})", 1)


def _quarter_end_month(value: object) -> str | None:
    """把 report_quarter 规整为季末月 'YYYY-MM'。

    支持三种既有格式：
    - 日历季 `2024Q1` / `2024-Q1` -> 2024-03
    - TEL 财年（3 月末年结）`FY2027-Q1` -> 2026-06（FY2026-Q1 实际 period_end=2025-06-30）
    """
    text = str(value)
    m = re.match(r"(?:FY)?(\d{4})[- ]?[Qq](\d)", text)
    if not m:
        return None
    year, qn = int(m.group(1)), int(m.group(2))
    if text.startswith("FY"):
        if qn == 1:
            return f"{year - 1}-06"
        if qn == 2:
            return f"{year - 1}-09"
        if qn == 3:
            return f"{year - 1}-12"
        return f"{year}-03"
    month = {1: "03", 2: "06", 3: "09", 4: "12"}[qn]
    return f"{year}-{month}"


def load_sox() -> tuple[pl.DataFrame, pl.DataFrame]:
    """SOX 日频 → 月频（月末收盘/月收益/12M 动量）与季频（季末月收益）。"""
    gm = (
        pl.read_parquet(GM_PATH).select(["trade_date", "sox_close"]).drop_nulls().sort("trade_date")
    )
    monthly = (
        gm.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("month"))
        .group_by("month")
        .agg(pl.col("sox_close").last().alias("close"))
        .sort("month")
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1) - 1.0).alias("sox_mom"),
            (pl.col("close") / pl.col("close").shift(12) - 1.0).alias("sox_yoy12"),
        )
        .select(["month", "close", "sox_mom", "sox_yoy12"])
    )
    quarterly = (
        monthly.filter(pl.col("month").str.slice(-2).is_in(["03", "06", "09", "12"]))
        .with_columns((pl.col("close") / pl.col("close").shift(1) - 1.0).alias("sox_qret"))
        .select(["month", "sox_qret"])
        .drop_nulls()
    )
    return monthly, quarterly


def _monthly(
    df: pl.DataFrame,
    value_col: str,
    *,
    yoy_period: int | None = None,
) -> pl.DataFrame:
    """月频序列：report_month → 'YYYY-MM'，可选自算 yoy（pct_change(12)）。"""
    out = (
        df.select(
            [
                _month_key(pl.col("report_month")).alias("month"),
                pl.col(value_col).alias("value"),
            ]
        )
        .drop_nulls(["month", "value"])
        .unique(subset=["month"], keep="first")
        .sort("month")
    )
    if yoy_period:
        out = out.with_columns(
            (pl.col("value") / pl.col("value").shift(yoy_period) - 1.0).alias("value")
        ).drop_nulls()
    return out


def _quarterly(
    df: pl.DataFrame,
    value_col: str,
    *,
    yoy_period: int | None = None,
) -> pl.DataFrame:
    """季频序列：report_quarter → 季末月 'YYYY-MM'，可选自算 yoy（pct_change(4)）。"""
    out = (
        df.select(
            [
                pl.col("report_quarter")
                .map_elements(_quarter_end_month, return_dtype=pl.Utf8)
                .alias("month"),
                pl.col(value_col).alias("value"),
            ]
        )
        .drop_nulls(["month", "value"])
        .unique(subset=["month"], keep="first")
        .sort("month")
    )
    if yoy_period:
        out = out.with_columns(
            (pl.col("value") / pl.col("value").shift(yoy_period) - 1.0).alias("value")
        ).drop_nulls()
    return out


def _memory_parity(bench: pl.DataFrame) -> pl.DataFrame:
    """DDR4(61050) / DDR5(6105) 代际比价序列（仅两序列重叠月份）。"""
    ddr4 = (
        bench.filter(pl.col("indicator_id") == 61050)
        .select(
            [
                _month_key(pl.col("report_month")).alias("month"),
                pl.col("price_usd").alias("ddr4"),
            ]
        )
        .drop_nulls()
        .unique(subset=["month"], keep="first")
    )
    ddr5 = (
        bench.filter(pl.col("indicator_id") == 6105)
        .select(
            [
                _month_key(pl.col("report_month")).alias("month"),
                pl.col("price_usd").alias("ddr5"),
            ]
        )
        .drop_nulls()
        .unique(subset=["month"], keep="first")
    )
    return (
        ddr4.join(ddr5, on="month", how="inner")
        .with_columns((pl.col("ddr4") / pl.col("ddr5")).alias("value"))
        .select(["month", "value"])
        .drop_nulls()
        .sort("month")
    )


def _build_metrics() -> list[Metric]:
    metrics: list[Metric] = []

    def add(
        name: str, label: str, category: str, table: str, freq: str, frame: pl.DataFrame | None
    ) -> None:
        if frame is not None and not frame.is_empty():
            metrics.append(Metric(name, label, category, table, freq, frame))

    # ---- sales：SIA/WSTS 全球与中国区销售额 ----
    sales = _read("semiconductor_sales", "sales")
    for col, key, label in [
        ("yoy_growth", "global_yoy", "全球半导体销售额 YoY"),
        ("mom_growth", "global_mom", "全球半导体销售额 MoM"),
        ("china_yoy_growth", "china_yoy", "中国区销售额 YoY"),
        ("americas_yoy_growth", "americas_yoy", "美洲区销售额 YoY"),
        ("europe_yoy_growth", "europe_yoy", "欧洲区销售额 YoY"),
        ("japan_yoy_growth", "japan_yoy", "日本区销售额 YoY"),
        ("asia_pacific_yoy_growth", "apac_yoy", "亚太区销售额 YoY"),
    ]:
        add(f"sales.{key}", label, "sales", "semiconductor_sales", "monthly", _monthly(sales, col))

    # ---- sales：TSMC 台积电月度营收（领先代理） ----
    lead = _read("semiconductor_lead", "sales")
    add(
        "lead.tsmc_yoy",
        "台积电月度营收 YoY",
        "sales",
        "semiconductor_lead",
        "monthly",
        _monthly(lead, "tsmc_revenue_yoy"),
    )
    add(
        "lead.tsmc_mom",
        "台积电月度营收 MoM",
        "sales",
        "semiconductor_lead",
        "monthly",
        _monthly(lead, "tsmc_revenue_mom"),
    )
    add(
        "lead.tsmc_3mma_yoy",
        "台积电月度营收 3MMA YoY（自算）",
        "sales",
        "semiconductor_lead",
        "monthly",
        _monthly(lead, "tsmc_revenue_3mma_usd", yoy_period=12),
    )

    # ---- equipment：SEAJ 日本制设备出货 ----
    eq = _read("semiconductor_equipment", "equipment")
    add(
        "equipment.seaj_yoy",
        "SEAJ 设备出货 3MMA YoY",
        "equipment",
        "semiconductor_equipment",
        "monthly",
        _monthly(eq, "yoy_growth_3mma"),
    )
    add(
        "equipment.seaj_mom",
        "SEAJ 设备出货 3MMA MoM",
        "equipment",
        "semiconductor_equipment",
        "monthly",
        _monthly(eq, "mom_growth_3mma"),
    )

    # ---- capacity：芯片交期（月频，只读方向） ----
    lead_time = _read("chip_lead_time", "capacity")
    add(
        "capacity.lead_time_level",
        "芯片平均交期（周）",
        "capacity",
        "chip_lead_time",
        "monthly",
        _monthly(lead_time, "avg_lead_time_weeks"),
    )
    add(
        "capacity.lead_time_mom",
        "芯片平均交期环比（周）",
        "capacity",
        "chip_lead_time",
        "monthly",
        _monthly(lead_time, "lead_time_mom_weeks"),
    )
    add(
        "capacity.mcu_lead_time_level",
        "MCU 交期（周）",
        "capacity",
        "chip_lead_time",
        "monthly",
        _monthly(lead_time, "mcu_lead_time_weeks"),
    )

    # ---- price：TrendForce 内存月度基准（按 indicator 分区） ----
    bench = _read("semiconductor_memory_benchmark", "price")
    for iid, key, label in [
        (6105, "ddr5", "DDR5 16G 现货价"),
        (61050, "ddr4", "DDR4 16Gb 现货价"),
        (6106, "nand", "NAND 512Gb 现货价"),
    ]:
        sub = bench.filter(pl.col("indicator_id") == iid)
        add(
            f"price.{key}_yoy",
            f"{label} YoY",
            "price",
            "semiconductor_memory_benchmark",
            "monthly",
            _monthly(sub, "price_yoy"),
        )
        add(
            f"price.{key}_mom",
            f"{label} MoM",
            "price",
            "semiconductor_memory_benchmark",
            "monthly",
            _monthly(sub, "price_mom"),
        )
    add(
        "price.ddr4_ddr5_parity",
        "DDR4/DDR5 代际比价（61050/6105）",
        "price",
        "semiconductor_memory_benchmark",
        "monthly",
        _memory_parity(bench),
    )

    # ---- price：台湾存储厂月度营收先导（按 symbol 分区） ----
    tw = _read("semiconductor_memory_taiwan_lead", "price")
    for sym in sorted(tw["symbol"].unique().to_list()):
        sub = tw.filter(pl.col("symbol") == sym)
        add(
            f"price.tw_{sym}_yoy",
            f"台湾存储营收 YoY（{sym}，派生口径）",
            "price",
            "semiconductor_memory_taiwan_lead",
            "monthly",
            _monthly(sub, "revenue_yoy_derived"),
        )
        add(
            f"price.tw_{sym}_mom",
            f"台湾存储营收 MoM（{sym}）",
            "price",
            "semiconductor_memory_taiwan_lead",
            "monthly",
            _monthly(sub, "revenue_mom"),
        )
    tw_agg = (
        tw.select(
            [
                _month_key(pl.col("report_month")).alias("month"),
                pl.col("revenue_yoy_derived").alias("value"),
            ]
        )
        .drop_nulls(["month", "value"])
        .group_by("month")
        .agg(pl.col("value").mean().alias("value"))
        .sort("month")
    )
    add(
        "price.tw_memory_lead_yoy",
        "台湾存储营收 YoY 均值（2408/3260）",
        "price",
        "semiconductor_memory_taiwan_lead",
        "monthly",
        tw_agg,
    )

    # ---- inventory：IDM 加权 DOI（季频，先去重再取季度聚合列） ----
    inv = _read("semiconductor_inventory_days", "inventory")
    for col, key, label in [
        ("idm_weighted_doi_days", "idm_weighted_doi", "IDM 加权库存天数 DOI"),
        ("idm_equal_doi_days", "idm_equal_doi", "IDM 等权库存天数 DOI"),
        ("memory_weighted_doi_days", "memory_weighted_doi", "存储三巨头加权 DOI"),
        ("analog_weighted_doi_days", "analog_weighted_doi", "模拟四巨头加权 DOI"),
    ]:
        add(
            f"inventory.{key}",
            label,
            "inventory",
            "semiconductor_inventory_days",
            "quarterly",
            _quarterly(inv, col),
        )

    # ---- inventory：渠道库存（季频） ----
    channel = _read("semiconductor_channel_inventory", "inventory")
    add(
        "inventory.channel_weighted_doi",
        "渠道（ARW/AVT）加权库存天数 DOI",
        "inventory",
        "semiconductor_channel_inventory",
        "quarterly",
        _quarterly(channel, "channel_weighted_doi_days"),
    )

    # ---- equipment：SEMI 全球/中国设备出货（季频） ----
    semi = _read("semiconductor_equipment_semi", "equipment")
    add(
        "equipment.semi_global_yoy",
        "SEMI 全球设备出货 YoY",
        "equipment",
        "semiconductor_equipment_semi",
        "quarterly",
        _quarterly(semi, "yoy_growth"),
    )
    add(
        "equipment.semi_global_qoq",
        "SEMI 全球设备出货 QoQ",
        "equipment",
        "semiconductor_equipment_semi",
        "quarterly",
        _quarterly(semi, "qoq_growth"),
    )
    add(
        "equipment.semi_china_yoy",
        "SEMI 中国区设备出货 YoY（自算）",
        "equipment",
        "semiconductor_equipment_semi",
        "quarterly",
        _quarterly(semi, "china_billings_billion_usd", yoy_period=4),
    )
    add(
        "equipment.semi_china_share",
        "SEMI 中国区设备出货占比",
        "equipment",
        "semiconductor_equipment_semi",
        "quarterly",
        _quarterly(semi, "china_share_pct"),
    )

    # ---- equipment：设备商 GM（ASML + LRCX/KLAC/AMAT/TEL） ----
    asml = _read("semiconductor_equipment_gm", "equipment")
    add(
        "equipment.asml_gm",
        "ASML 季度毛利率",
        "equipment",
        "semiconductor_equipment_gm",
        "quarterly",
        _quarterly(asml, "gross_margin_pct"),
    )
    add(
        "equipment.asml_net_sales_yoy",
        "ASML 季度净销售额 YoY（自算）",
        "equipment",
        "semiconductor_equipment_gm",
        "quarterly",
        _quarterly(asml, "net_sales_eur_m", yoy_period=4),
    )
    gm_multi = _read("semiconductor_equipment_gm_multi", "equipment")
    for company in ["LRCX", "KLAC", "AMAT", "TEL"]:
        sub = gm_multi.filter(pl.col("company") == company)
        add(
            f"equipment.gm_{company.lower()}",
            f"{company} 季度毛利率",
            "equipment",
            "semiconductor_equipment_gm_multi",
            "quarterly",
            _quarterly(sub, "gross_margin_pct"),
        )

    # ---- capacity：晶圆代工产能利用率（季频） ----
    foundry = _read("foundry_capacity_utilization", "capacity")
    add(
        "capacity.foundry_weighted_util",
        "晶圆代工加权产能利用率",
        "capacity",
        "foundry_capacity_utilization",
        "quarterly",
        _quarterly(foundry, "foundry_weighted_utilization_pct"),
    )
    add(
        "capacity.tsmc_util",
        "台积电产能利用率",
        "capacity",
        "foundry_capacity_utilization",
        "quarterly",
        _quarterly(foundry, "tsmc_utilization_pct"),
    )

    # ---- capacity：台积电先进封装与 HPC 结构（季频） ----
    pkg = _read("tsmc_advanced_packaging_revenue", "capacity")
    for sym in sorted(pkg["symbol"].unique().to_list()):
        sub = pkg.filter(pl.col("symbol") == sym)
        add(
            f"capacity.tsmc_pkg_rev_yoy[{sym}]",
            f"台积电先进封测营收 YoY（{sym}）",
            "capacity",
            "tsmc_advanced_packaging_revenue",
            "quarterly",
            _quarterly(sub, "revenue_yoy"),
        )
        add(
            f"capacity.tsmc_hpc_pct[{sym}]",
            f"台积电 HPC 平台占比（{sym}）",
            "capacity",
            "tsmc_advanced_packaging_revenue",
            "quarterly",
            _quarterly(sub, "hpc_platform_pct"),
        )
        add(
            f"capacity.tsmc_adv_wafer_pct[{sym}]",
            f"台积电先进制程晶圆占比（{sym}）",
            "capacity",
            "tsmc_advanced_packaging_revenue",
            "quarterly",
            _quarterly(sub, "advanced_wafer_pct"),
        )

    # ---- sales：北美四大云厂商 CapEx（季频，AI 时代主导需求） ----
    capex = _read("cloud_capex_quarterly")
    add(
        "sales.cloud_capex_yoy",
        "北美四大云厂商 CapEx YoY",
        "sales",
        "cloud_capex_quarterly",
        "quarterly",
        _quarterly(capex, "yoy_growth"),
    )
    add(
        "sales.cloud_capex_qoq",
        "北美四大云厂商 CapEx QoQ",
        "sales",
        "cloud_capex_quarterly",
        "quarterly",
        _quarterly(capex, "qoq_growth"),
    )

    return metrics


def _corr(x: pl.Series, y: pl.Series, min_n: int) -> dict | None:
    pairs = [
        (float(u), float(v))
        for u, v in zip(x.to_list(), y.to_list())
        if u is not None and v is not None and math.isfinite(float(u)) and math.isfinite(float(v))
    ]
    if len(pairs) < min_n or len({p[0] for p in pairs}) < 2 or len({p[1] for p in pairs}) < 2:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    rho, rp = stats.spearmanr(xs, ys)
    pr, pp = stats.pearsonr(xs, ys)
    return {
        "n": len(pairs),
        "spearman": float(rho),
        "spearman_p": float(rp),
        "pearson": float(pr),
        "pearson_p": float(pp),
    }


def _fmt3(v: float | None) -> str:
    return f"{v:.3f}" if v is not None else ""


def analyze_metric(
    metric: Metric, sox_monthly: pl.DataFrame, sox_quarterly: pl.DataFrame
) -> tuple[list[dict], list[dict]]:
    """对单个指标做多窗口同期 + 领先滞后分析，返回 (summary_rows, lag_matrix_rows)。"""
    freq = metric.freq
    sox = sox_quarterly if freq == "quarterly" else sox_monthly
    base = sox.join(metric.frame, on="month", how="inner").drop_nulls(["value"]).sort("month")
    min_n = MIN_N_QUARTERLY if freq == "quarterly" else MIN_N_MONTHLY
    lag_range = QUARTERLY_LAGS if freq == "quarterly" else MONTHLY_LAGS
    ret_col = "sox_qret" if freq == "quarterly" else "sox_mom"

    summary: list[dict] = []
    lag_matrix: list[dict] = []

    for win_name, start, end in WINDOWS:
        sub = base
        if start is not None:
            sub = sub.filter(pl.col("month") >= start)
        if end is not None:
            sub = sub.filter(pl.col("month") <= end)
        if sub.is_empty():
            continue

        contemp = _corr(sub[ret_col], sub["value"], min_n)
        yoy12 = (
            _corr(sub["sox_yoy12"], sub["value"], min_n)
            if freq == "monthly" and "sox_yoy12" in sub.columns
            else None
        )

        best: dict | None = None
        best_k: int | None = None
        for k in lag_range:
            shifted = sub.with_columns(pl.col("value").shift(k).alias("xshift"))
            c = _corr(sub[ret_col], shifted["xshift"], min_n)
            if c is None:
                continue
            lag_matrix.append(
                {
                    "category": metric.category,
                    "table": metric.table,
                    "metric": metric.name,
                    "window": win_name,
                    "lag": k,
                    "n": c["n"],
                    "spearman": c["spearman"],
                    "pearson": c["pearson"],
                }
            )
            if best is None or abs(c["spearman"]) > abs(best["spearman"]):
                best, best_k = c, k

        summary.append(
            {
                "category": metric.category,
                "table": metric.table,
                "metric": metric.name,
                "label": metric.label,
                "freq": freq,
                "window": win_name,
                "start": sub["month"].min(),
                "end": sub["month"].max(),
                "n": contemp["n"] if contemp else None,
                "contemp_spearman": contemp["spearman"] if contemp else None,
                "contemp_spearman_p": contemp["spearman_p"] if contemp else None,
                "contemp_pearson": contemp["pearson"] if contemp else None,
                "contemp_pearson_p": contemp["pearson_p"] if contemp else None,
                "sox_yoy12_spearman": yoy12["spearman"] if yoy12 else None,
                "best_lag_k": best_k,
                "best_lag_spearman": best["spearman"] if best else None,
                "best_lag_spearman_p": best["spearman_p"] if best else None,
                "best_lag_pearson": best["pearson"] if best else None,
            }
        )
    return summary, lag_matrix


def _coverage_rows(metrics: list[Metric]) -> list[dict]:
    rows = []
    seen: dict[str, dict] = {}
    for m in metrics:
        key = f"{m.table}|{m.freq}"
        if key not in seen:
            seen[key] = {
                "table": m.table,
                "category": m.category,
                "freq": m.freq,
                "n_metrics": 0,
                "start": m.frame["month"].min(),
                "end": m.frame["month"].max(),
                "status": "included",
            }
        seen[key]["n_metrics"] += 1
        seen[key]["start"] = min(seen[key]["start"], m.frame["month"].min())
        seen[key]["end"] = max(seen[key]["end"], m.frame["month"].max())
    for table, category, reason in EXCLUDED_TABLES:
        rows.append(
            {
                "table": table,
                "category": category,
                "freq": "—",
                "n_metrics": 0,
                "start": None,
                "end": None,
                "status": f"excluded: {reason}",
            }
        )
    rows.extend(seen.values())
    return rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sox_monthly, sox_quarterly = load_sox()
    print(
        f"SOX 月频样本: {sox_monthly['month'].min()} ~ {sox_monthly['month'].max()} ({len(sox_monthly)} 月)"
    )
    print(
        f"SOX 季频样本: {sox_quarterly['month'].min()} ~ {sox_quarterly['month'].max()} ({len(sox_quarterly)} 季)"
    )

    metrics = _build_metrics()
    print(f"参与相关分析的指标序列数: {len(metrics)}")

    summary: list[dict] = []
    lag_matrix: list[dict] = []
    for m in metrics:
        s_rows, l_rows = analyze_metric(m, sox_monthly, sox_quarterly)
        summary.extend(s_rows)
        lag_matrix.extend(l_rows)

    summary_df = pl.DataFrame(summary)
    lag_df = pl.DataFrame(lag_matrix)
    coverage_df = pl.DataFrame(_coverage_rows(metrics))

    summary_df.write_csv(OUT_DIR / "sox_local_corr_summary.csv")
    lag_df.write_csv(OUT_DIR / "sox_local_corr_lag_matrix.csv")
    coverage_df.write_csv(OUT_DIR / "coverage.csv")

    # 打印关键结果：全样本同期 Spearman 最强 / 最弱
    full = summary_df.filter(pl.col("window") == "full").drop_nulls(["contemp_spearman"])
    top = full.sort("contemp_spearman", descending=True).head(10)
    bottom = full.sort("contemp_spearman").head(5)
    best_lag = (
        summary_df.filter(pl.col("window") == "full")
        .drop_nulls(["best_lag_spearman"])
        .sort(pl.col("best_lag_spearman").abs(), descending=True)
        .head(10)
    )

    print("\n=== 全样本同期 Spearman 最强 10（SOX 月收益 vs 指标） ===")
    for r in top.iter_rows(named=True):
        print(f"  {r['label']}: rho={_fmt3(r['contemp_spearman'])} (n={r['n']})")
    print("\n=== 全样本同期 Spearman 最弱 5（负相关，逆周期） ===")
    for r in bottom.iter_rows(named=True):
        print(f"  {r['label']}: rho={_fmt3(r['contemp_spearman'])} (n={r['n']})")
    print("\n=== 全样本最佳领先-滞后 Spearman 10（|rho| 最大） ===")
    for r in best_lag.iter_rows(named=True):
        print(
            f"  {r['label']}: lag={r['best_lag_k']} rho={_fmt3(r['best_lag_spearman'])} (n={r['n']})"
        )

    print(f"\n输出目录: {OUT_DIR}")
    print(f"  summary: {OUT_DIR / 'sox_local_corr_summary.csv'} ({len(summary_df)} 行)")
    print(f"  lag_matrix: {OUT_DIR / 'sox_local_corr_lag_matrix.csv'} ({len(lag_df)} 行)")
    print(f"  coverage: {OUT_DIR / 'coverage.csv'} ({len(coverage_df)} 行)")


if __name__ == "__main__":
    main()
