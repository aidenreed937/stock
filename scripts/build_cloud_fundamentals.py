#!/usr/bin/env python3
"""构建云厂商基本面健康度（FCF 与 ROI）Curated 黄金表。

输入：
- data/curated/industry/cloud_capex_quarterly.parquet（SEC 10-Q/10-K CapEx 主干）
- data/raw/industry/cloud/sec_edgar/*.json.gz（SEC CompanyFacts 官方 RAW）
- data/curated/yfinance/market=US/{cashflow,financials}/data.parquet（缺口回退）

输出：
- data/curated/industry/cloud_fundamentals_quarterly.parquet
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.cloud import CloudCapexCollector
from stock_data.fetcher.industry.cloud.parser import (
    OPERATING_CASH_FLOW_XBRL_CONCEPTS,
    REVENUE_XBRL_CONCEPTS,
    extract_sec_quarterly_metric_with_filing_dates,
)

CLOUD_CAPEX_PATH = Path("data/curated/industry/cloud_capex_quarterly.parquet")
SEC_RAW_ROOT = Path("data/raw/industry")
YF_CF_PATH = Path("data/curated/yfinance/market=US/cashflow/data.parquet")
YF_FN_PATH = Path("data/curated/yfinance/market=US/financials/data.parquet")
OUTPUT_PATH = Path("data/curated/industry/cloud_fundamentals_quarterly.parquet")

TARGET_SYMBOLS = ["MSFT", "GOOGL", "META", "AMZN"]
CAPEX_COLUMNS = {
    "MSFT": "msft_capex_billion_usd",
    "GOOGL": "goog_capex_billion_usd",
    "META": "meta_capex_billion_usd",
    "AMZN": "amzn_capex_billion_usd",
}


def _load_yfinance_fallback() -> dict[tuple[str, date], dict[str, float]]:
    """加载 yfinance 字段级回退值，不将缺失字段填成零。"""
    if not YF_CF_PATH.exists() or not YF_FN_PATH.exists():
        return {}

    cf = pl.read_parquet(YF_CF_PATH).filter(pl.col("symbol").is_in(TARGET_SYMBOLS))
    fn = pl.read_parquet(YF_FN_PATH).filter(pl.col("symbol").is_in(TARGET_SYMBOLS))
    if cf.is_empty() or fn.is_empty():
        return {}

    joined = cf.join(fn, on=["symbol", "as_of_date"], how="inner")
    result: dict[tuple[str, date], dict[str, float]] = {}
    for row in joined.select(
        ["symbol", "as_of_date", "operating_cash_flow", "total_revenue"]
    ).to_dicts():
        as_of = row["as_of_date"]
        if hasattr(as_of, "date"):
            as_of = as_of.date()
        result[(row["symbol"], as_of)] = {
            key: float(row[key])
            for key in ("operating_cash_flow", "total_revenue")
            if row[key] is not None
        }
    return result


def _load_sec_fundamentals(capex_df: pl.DataFrame) -> list[dict[str, object]]:
    """从本地 SEC CompanyFacts 快照构建逐公司、逐季度基本面事实。"""
    collector = CloudCapexCollector(raw_dir=SEC_RAW_ROOT)
    yfinance_fallback = _load_yfinance_fallback()
    capex_rows = {
        row["report_quarter"]: row
        for row in capex_df.select(
            ["report_quarter", "trade_date", *CAPEX_COLUMNS.values()]
        ).to_dicts()
    }
    rows: list[dict[str, object]] = []

    for ticker in TARGET_SYMBOLS:
        facts = collector.load_company_facts_snapshot(ticker)
        revenue = extract_sec_quarterly_metric_with_filing_dates(
            facts, ticker, REVENUE_XBRL_CONCEPTS, positive_only=True
        )
        operating_cash_flow = extract_sec_quarterly_metric_with_filing_dates(
            facts, ticker, OPERATING_CASH_FLOW_XBRL_CONCEPTS
        )

        for quarter, capex_row in capex_rows.items():
            trade_date = capex_row["trade_date"]
            sec_revenue = revenue.get(quarter)
            sec_ocf = operating_cash_flow.get(quarter)
            fallback = yfinance_fallback.get((ticker, trade_date), {})

            revenue_value = (
                sec_revenue[0] if sec_revenue is not None else fallback.get("total_revenue")
            )
            ocf_value = sec_ocf[0] if sec_ocf is not None else fallback.get("operating_cash_flow")
            capex_value = capex_row[CAPEX_COLUMNS[ticker]]
            if revenue_value is None or ocf_value is None or capex_value is None:
                continue

            sec_complete = sec_revenue is not None and sec_ocf is not None
            rows.append(
                {
                    "symbol": ticker,
                    "report_quarter": quarter,
                    "trade_date": trade_date,
                    "revenue_billion_usd": float(revenue_value)
                    if sec_revenue is not None
                    else float(revenue_value) / 1e9,
                    "operating_cash_flow_billion_usd": float(ocf_value)
                    if sec_ocf is not None
                    else float(ocf_value) / 1e9,
                    "capex_billion_usd": float(capex_value),
                    "financials_source": "SEC_CompanyFacts"
                    if sec_complete
                    else "yfinance_fallback",
                }
            )
    return rows


def _aggregate_financials(rows: list[dict[str, object]]) -> pl.DataFrame:
    """按报告期汇总同一公司集合的收入、现金流和资本开支。"""
    if not rows:
        return pl.DataFrame()

    frame = pl.DataFrame(rows)
    aggregates: list[dict[str, object]] = []
    for trade_date in frame["trade_date"].unique().sort().to_list():
        subset = frame.filter(pl.col("trade_date") == trade_date)
        sources = sorted(set(subset["financials_source"].to_list()))
        ocf = subset["operating_cash_flow_billion_usd"].sum()
        capex = subset["capex_billion_usd"].sum()
        aggregates.append(
            {
                "trade_date": trade_date,
                "total_ocf_billion_usd": ocf,
                "total_fcf_billion_usd": ocf - capex,
                "total_revenue_billion_usd": subset["revenue_billion_usd"].sum(),
                "financial_capex_billion_usd": capex,
                "num_companies": subset["symbol"].n_unique(),
                "financials_source": "+".join(sources),
            }
        )
    return pl.DataFrame(aggregates)


def build_cloud_fundamentals() -> pl.DataFrame:
    if not CLOUD_CAPEX_PATH.exists():
        raise FileNotFoundError(f"缺少输入数据源: {CLOUD_CAPEX_PATH}")

    capex_df = pl.read_parquet(CLOUD_CAPEX_PATH).sort("report_quarter")
    financials = _aggregate_financials(_load_sec_fundamentals(capex_df))

    if financials.is_empty():
        joined = capex_df.with_columns(
            [
                pl.lit(None, dtype=pl.Float64).alias(column)
                for column in (
                    "total_ocf_billion_usd",
                    "total_fcf_billion_usd",
                    "total_revenue_billion_usd",
                    "financial_capex_billion_usd",
                )
            ]
            + [
                pl.lit(None, dtype=pl.UInt32).alias("num_companies"),
                pl.lit(None, dtype=pl.String).alias("financials_source"),
            ]
        )
    else:
        joined = capex_df.join(financials, on="trade_date", how="left")

    # 派生无量纲指标：所有分母均来自同一批有完整基本面数据的公司。
    out = (
        joined.sort("report_quarter")
        .with_columns(
            [
                pl.when(
                    (pl.col("total_ocf_billion_usd").is_not_null())
                    & (pl.col("total_ocf_billion_usd").abs() > 1e-6)
                )
                .then(pl.col("total_fcf_billion_usd") / pl.col("total_ocf_billion_usd"))
                .otherwise(None)
                .alias("fcf_conversion_rate"),
                pl.when(
                    (pl.col("financial_capex_billion_usd").is_not_null())
                    & (pl.col("total_revenue_billion_usd") > 0.0)
                )
                .then(pl.col("financial_capex_billion_usd") / pl.col("total_revenue_billion_usd"))
                .otherwise(None)
                .alias("capex_intensity"),
            ]
        )
        .with_columns(
            [
                (
                    pl.col("total_revenue_billion_usd")
                    - pl.col("total_revenue_billion_usd").shift(4)
                ).alias("delta_revenue_yoy"),
                (
                    pl.col("financial_capex_billion_usd")
                    - pl.col("financial_capex_billion_usd").shift(4)
                ).alias("delta_capex_yoy"),
            ]
        )
        .with_columns(
            pl.when(
                (pl.col("delta_capex_yoy").is_not_null())
                & (pl.col("delta_capex_yoy").abs() > 1e-3)
                & (pl.col("delta_revenue_yoy").is_not_null())
            )
            .then(pl.col("delta_revenue_yoy") / pl.col("delta_capex_yoy"))
            .otherwise(None)
            .alias("marginal_roi_proxy")
        )
        .drop(["delta_revenue_yoy", "delta_capex_yoy"])
    )

    now_iso = datetime.now(UTC).isoformat()
    return out.with_columns(
        [
            pl.col("financials_source").fill_null("SEC_CompanyFacts").alias("source"),
            pl.lit("billion_usd").alias("unit"),
            pl.lit(now_iso).alias("collected_at"),
        ]
    )


def main() -> None:
    df = build_cloud_fundamentals()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUTPUT_PATH)
    print(f"成功构建并落盘云厂商基本面黄金表: {OUTPUT_PATH}")
    print(f"总行数: {len(df)}, 最新行:")
    print(
        df.select(
            [
                "report_quarter",
                "trade_date",
                "release_date",
                "total_capex_billion_usd",
                "financial_capex_billion_usd",
                "total_ocf_billion_usd",
                "total_fcf_billion_usd",
                "num_companies",
                "financials_source",
                "fcf_conversion_rate",
                "capex_intensity",
                "marginal_roi_proxy",
            ]
        ).tail(5)
    )


if __name__ == "__main__":
    main()
