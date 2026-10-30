"""PTA 与聚酯化纤大炼化上市公司盈利与估值反向时钟领域 Mart (pta_company_panel)。

基于本地 Curated 黄金事实表（TuShare daily_basic / stock_daily_bar / income / balancesheet），
打通聚酯/PTA 产业链因果链第 5 环（企业会计盈利与减值放大器）与第 6 环（二级市场定价与估值反向时钟）。

Point-in-Time (PIT) 约束：
- 财务指标严格按公告日 (ann_date) 无前视合并至日频交易序列；
- 估值分位数（PB / PE-TTM 5Y & 10Y）采用滚动历史窗口计算；
- 状态机自动识别大宗周期股反向时钟阶段 (deep_value_trough / pe_trap_peak / fair_expansion / neutral)。
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_analytics.marts.shared.rolling_percentile import (
    WINDOW_5Y_DAYS,
    WINDOW_10Y_DAYS,
    add_rolling_percentiles,
)
from stock_data.catalog import DataCatalog

logger = logging.getLogger(__name__)

PTA_COMPANY_PANEL_MART_NAME = "pta_company_panel"
PTA_COMPANY_FINANCIALS_MART_NAME = "pta_company_financials"
PTA_COMPANY_PANEL_FILE = f"{PTA_COMPANY_PANEL_MART_NAME}.parquet"
PTA_COMPANY_FINANCIALS_FILE = f"{PTA_COMPANY_FINANCIALS_MART_NAME}.parquet"

DEFAULT_CONFIG_PATH = Path("config/industry/chemicals/pta/companies.yaml")

DEFAULT_PTA_COMPANIES: list[dict[str, Any]] = [
    {
        "symbol": "600346.SH",
        "name": "恒力石化",
        "process_type": "invista_p8_plus",
        "location": "辽宁大连 / 广东惠州",
        "annual_capacity_w_tons": 1660.0,
        "cost_tier": "lowest_alpha",
        "pta_revenue_share_approx": 0.25,
    },
    {
        "symbol": "002493.SZ",
        "name": "荣盛石化",
        "process_type": "bp_and_invista",
        "location": "浙江舟山 / 浙江宁波",
        "annual_capacity_w_tons": 1900.0,
        "cost_tier": "mega_refinery_alpha",
        "pta_revenue_share_approx": 0.18,
    },
    {
        "symbol": "601233.SH",
        "name": "桐昆股份",
        "process_type": "integrated_filament",
        "location": "浙江嘉兴 / 江苏如东",
        "annual_capacity_w_tons": 1020.0,
        "cost_tier": "filament_synergy_beta",
        "pta_revenue_share_approx": 0.30,
    },
    {
        "symbol": "603225.SH",
        "name": "新凤鸣",
        "process_type": "integrated_filament",
        "location": "浙江嘉兴 / 浙江平湖",
        "annual_capacity_w_tons": 500.0,
        "cost_tier": "high_beta_elastic",
        "pta_revenue_share_approx": 0.28,
    },
    {
        "symbol": "000703.SZ",
        "name": "恒逸石化",
        "process_type": "integrated_filament",
        "location": "浙江杭州 / 海南洋浦 / 文莱",
        "annual_capacity_w_tons": 1900.0,
        "cost_tier": "brunei_overseas_beta",
        "pta_revenue_share_approx": 0.22,
    },
]

PTA_COMPANY_PANEL_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "symbol": pl.Utf8,
    "company_name": pl.Utf8,
    "process_type": pl.Utf8,
    "cost_tier": pl.Utf8,
    "annual_capacity_w_tons": pl.Float64,
    "pta_revenue_share_approx": pl.Float64,
    "close": pl.Float64,
    "total_mv": pl.Float64,
    "circ_mv": pl.Float64,
    "turnover_rate": pl.Float64,
    "pb": pl.Float64,
    "pe_ttm": pl.Float64,
    "pb_percentile_5y": pl.Float64,
    "pb_percentile_10y": pl.Float64,
    "pe_ttm_percentile_5y": pl.Float64,
    "pe_ttm_percentile_10y": pl.Float64,
    "valuation_regime": pl.Utf8,
    "fin_report_date": pl.Date,
    "fin_ann_date": pl.Date,
    "total_revenue": pl.Float64,
    "net_profit_attr_p": pl.Float64,
    "assets_impair_loss": pl.Float64,
    "inventories": pl.Float64,
    "total_equity": pl.Float64,
}

PTA_COMPANY_FINANCIALS_SCHEMA: dict[str, Any] = {
    "symbol": pl.Utf8,
    "company_name": pl.Utf8,
    "process_type": pl.Utf8,
    "cost_tier": pl.Utf8,
    "end_date": pl.Date,
    "ann_date": pl.Date,
    "total_revenue": pl.Float64,
    "net_profit_attr_p": pl.Float64,
    "assets_impair_loss": pl.Float64,
    "inventories": pl.Float64,
    "total_equity": pl.Float64,
    "pta_revenue_share_approx": pl.Float64,
}


def load_pta_company_configs(
    config_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """加载 PTA 上市公司元数据配置。"""
    p = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    if not p.exists():
        legacy_path = Path("config/industry/chemicals/pta_companies.yaml")
        if legacy_path.exists():
            p = legacy_path
        else:
            return DEFAULT_PTA_COMPANIES
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        companies = data.get("companies", [])
        return companies if companies else DEFAULT_PTA_COMPANIES
    except Exception as exc:
        logger.warning(f"无法读取 PTA 公司配置文件 {p}，回退默认配置: {exc}")
        return DEFAULT_PTA_COMPANIES


def classify_valuation_regime(
    pb: float | None,
    pb_pct_10y: float | None,
    pe_ttm: float | None,
    net_profit: float | None,
) -> str:
    """判定大宗周期股估值反向时钟状态。"""
    if pb is None:
        return "neutral"

    is_low_pb = (pb_pct_10y is not None and pb_pct_10y <= 15.0) or (pb < 1.0)
    is_earnings_depressed = (
        (pe_ttm is None)
        or (pe_ttm <= 0)
        or (pe_ttm > 30.0)
        or (net_profit is not None and net_profit <= 0)
    )
    if is_low_pb and is_earnings_depressed:
        return "deep_value_trough"

    is_low_pe = pe_ttm is not None and 0 < pe_ttm <= 10.0
    is_high_pb = (pb_pct_10y is not None and pb_pct_10y >= 75.0) or (pb >= 2.5)
    if is_low_pe and is_high_pb:
        return "pe_trap_peak"

    is_mid_pb = pb_pct_10y is not None and 15.0 < pb_pct_10y < 75.0
    is_normal_pe = pe_ttm is not None and 10.0 < pe_ttm <= 30.0
    if is_mid_pb and is_normal_pe and (net_profit is None or net_profit > 0):
        return "fair_expansion"

    return "neutral"


def empty_pta_company_panel() -> pl.DataFrame:
    """返回符合 Schema 定义的空公司面板 DataFrame。"""
    return pl.DataFrame(schema=PTA_COMPANY_PANEL_SCHEMA)


def empty_pta_company_financials() -> pl.DataFrame:
    """返回符合 Schema 定义的空财务面板 DataFrame。"""
    return pl.DataFrame(schema=PTA_COMPANY_FINANCIALS_SCHEMA)


def build_pta_financial_panel(
    catalog: DataCatalog,
    companies: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    """提取 PTA 上市公司的季度财报与资产减值损失黄金表。"""
    cfg_list = companies or load_pta_company_configs()
    symbols = [c["symbol"] for c in cfg_list]

    inc_df = catalog.load_dataset(
        "income",
        symbols=symbols,
        columns=[
            "symbol",
            "end_date",
            "ann_date",
            "total_revenue",
            "n_income_attr_p",
            "assets_impair_loss",
        ],
    )
    bs_df = catalog.load_dataset(
        "balancesheet",
        symbols=symbols,
        columns=[
            "symbol",
            "end_date",
            "ann_date",
            "inventories",
            "total_hldr_eqy_exc_min_int",
        ],
    )
    if inc_df.is_empty():
        return empty_pta_company_financials()

    meta_df = pl.DataFrame(
        [
            {
                "symbol": c["symbol"],
                "company_name": c.get("name", c["symbol"]),
                "process_type": c.get("process_type", "unknown"),
                "cost_tier": c.get("cost_tier", "unknown"),
                "pta_revenue_share_approx": float(c.get("pta_revenue_share_approx", 0.0)),
            }
            for c in cfg_list
        ]
    )

    joined = (
        inc_df.rename({"n_income_attr_p": "net_profit_attr_p"})
        .join(
            bs_df.rename({"total_hldr_eqy_exc_min_int": "total_equity"}),
            on=["symbol", "end_date"],
            how="left",
        )
        .join(meta_df, on="symbol", how="left")
    )

    cols = list(PTA_COMPANY_FINANCIALS_SCHEMA.keys())
    available = [c for c in cols if c in joined.columns]
    return joined.select(available).sort(["symbol", "end_date"])


def build_pta_company_panel(
    catalog: DataCatalog,
    companies: list[dict[str, Any]] | None = None,
    config_path: Path | str | None = None,
) -> pl.DataFrame:
    """构建 PTA 上市公司日频行情、估值反向时钟与财务指标面板。"""
    cfg_list = companies or load_pta_company_configs(config_path)
    symbols = [c["symbol"] for c in cfg_list]

    # 1. 提取日频行情
    daily_basic = catalog.load_dataset(
        "daily_basic",
        symbols=symbols,
        columns=[
            "symbol",
            "trade_date",
            "close",
            "total_mv",
            "circ_mv",
            "turnover_rate",
            "pb",
            "pe_ttm",
        ],
    )
    if daily_basic.is_empty():
        return empty_pta_company_panel()

    # 2. 滚动 5Y / 10Y PB 与 PE-TTM 分位数
    daily_with_pct = add_rolling_percentiles(
        daily_basic,
        key="symbol",
        date_column="trade_date",
        value_columns=["pb", "pe_ttm"],
        window_5y=WINDOW_5Y_DAYS,
        window_10y=WINDOW_10Y_DAYS,
    )

    # 3. 加载季频财报并按公告日 PIT 合并
    fin_df = build_pta_financial_panel(catalog, cfg_list)
    fin_pit = (
        fin_df.filter(pl.col("ann_date").is_not_null())
        .select(
            [
                "symbol",
                pl.col("end_date").alias("fin_report_date"),
                pl.col("ann_date").alias("fin_ann_date"),
                "total_revenue",
                "net_profit_attr_p",
                "assets_impair_loss",
                "inventories",
                "total_equity",
            ]
        )
        .sort("fin_ann_date")
    )

    daily_sorted = daily_with_pct.sort("trade_date")
    if not fin_pit.is_empty():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            joined = daily_sorted.join_asof(
                fin_pit,
                left_on="trade_date",
                right_on="fin_ann_date",
                by="symbol",
                strategy="backward",
            )
    else:
        joined = daily_sorted.with_columns(
            [
                pl.lit(None).cast(pl.Date).alias("fin_report_date"),
                pl.lit(None).cast(pl.Date).alias("fin_ann_date"),
                pl.lit(None).cast(pl.Float64).alias("total_revenue"),
                pl.lit(None).cast(pl.Float64).alias("net_profit_attr_p"),
                pl.lit(None).cast(pl.Float64).alias("assets_impair_loss"),
                pl.lit(None).cast(pl.Float64).alias("inventories"),
                pl.lit(None).cast(pl.Float64).alias("total_equity"),
            ]
        )

    # 4. 挂载公司元数据
    meta_df = pl.DataFrame(
        [
            {
                "symbol": c["symbol"],
                "company_name": c.get("name", c["symbol"]),
                "process_type": c.get("process_type", "unknown"),
                "cost_tier": c.get("cost_tier", "unknown"),
                "annual_capacity_w_tons": float(c.get("annual_capacity_w_tons", 0.0)),
                "pta_revenue_share_approx": float(c.get("pta_revenue_share_approx", 0.0)),
            }
            for c in cfg_list
        ]
    )
    panel = joined.join(meta_df, on="symbol", how="left")

    # 5. 估值状态机判定
    regimes = [
        classify_valuation_regime(
            pb=r["pb"],
            pb_pct_10y=r["pb_percentile_10y"],
            pe_ttm=r["pe_ttm"],
            net_profit=r["net_profit_attr_p"],
        )
        for r in panel.iter_rows(named=True)
    ]
    panel = panel.with_columns(pl.Series("valuation_regime", regimes))

    cols = list(PTA_COMPANY_PANEL_SCHEMA.keys())
    available = [c for c in cols if c in panel.columns]
    return panel.select(available).sort(["trade_date", "symbol"])
