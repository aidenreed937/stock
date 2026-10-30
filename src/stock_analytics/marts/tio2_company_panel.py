"""钛白粉上市公司盈利与估值反向时钟领域 Mart (tio2_company_panel)。

基于本地 Curated 黄金事实表（TuShare daily_basic / income / balancesheet），
打通钛白粉因果链第 5 环（企业会计盈利与资产减值）与第 6 环（二级市场定价与估值反向时钟）。

Point-in-Time (PIT) 约束：
- 财务指标（归母净利、资产减值损失、存货等）严格按公告日 (ann_date) 无前视合并至日频交易序列；
- 估值分位数（PB / PE-TTM 5Y & 10Y）采用滚动历史窗口计算；
- 状态机自动识别大宗/寡头周期股反向时钟阶段 (deep_value_trough / pe_trap_peak / fair_expansion / neutral)。
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

TIO2_COMPANY_PANEL_MART_NAME = "tio2_company_panel"
TIO2_COMPANY_FINANCIALS_MART_NAME = "tio2_company_financials"
TIO2_COMPANY_PANEL_FILE = f"{TIO2_COMPANY_PANEL_MART_NAME}.parquet"
TIO2_COMPANY_FINANCIALS_FILE = f"{TIO2_COMPANY_FINANCIALS_MART_NAME}.parquet"
TIO2_COMPANY_PANEL_LATEST_CSV = f"{TIO2_COMPANY_PANEL_MART_NAME}_latest.csv"

DEFAULT_CONFIG_PATH = Path("config/industry/chemicals/tio2/companies.yaml")

DEFAULT_TIO2_COMPANIES: list[dict[str, Any]] = [
    {
        "symbol": "002601.SZ",
        "name": "龙佰集团",
        "process_type": "chloride_and_sulfate",
        "cost_tier": "lowest_alpha",
        "role": "integrated_oligopoly_leader",
        "annual_capacity_w_tons": 151.0,
        "tio2_revenue_share_approx": 0.54,
    },
    {
        "symbol": "002145.SZ",
        "name": "钛能化学",
        "process_type": "sulfate_process",
        "cost_tier": "beta_elastic",
        "role": "beta_elastic",
        "annual_capacity_w_tons": 55.0,
        "tio2_revenue_share_approx": 0.70,
    },
    {
        "symbol": "600727.SH",
        "name": "鲁北化工",
        "process_type": "chloride_and_sulfate",
        "cost_tier": "integrated_circular_alpha",
        "role": "scale_challenger",
        "annual_capacity_w_tons": 26.0,
        "tio2_revenue_share_approx": 0.62,
    },
    {
        "symbol": "002136.SZ",
        "name": "安纳达",
        "process_type": "sulfate_process",
        "cost_tier": "marginal_producer",
        "role": "marginal_producer",
        "annual_capacity_w_tons": 12.0,
        "tio2_revenue_share_approx": 0.85,
    },
    {
        "symbol": "000545.SZ",
        "name": "金浦钛业",
        "process_type": "sulfate_process",
        "cost_tier": "marginal_producer",
        "role": "marginal_producer",
        "annual_capacity_w_tons": 16.0,
        "tio2_revenue_share_approx": 0.90,
    },
]

TIO2_COMPANY_PANEL_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "symbol": pl.Utf8,
    "company_name": pl.Utf8,
    "process_type": pl.Utf8,
    "cost_tier": pl.Utf8,
    "role": pl.Utf8,
    "annual_capacity_w_tons": pl.Float64,
    "tio2_revenue_share_approx": pl.Float64,
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

TIO2_COMPANY_FINANCIALS_SCHEMA: dict[str, Any] = {
    "symbol": pl.Utf8,
    "company_name": pl.Utf8,
    "process_type": pl.Utf8,
    "cost_tier": pl.Utf8,
    "role": pl.Utf8,
    "end_date": pl.Date,
    "ann_date": pl.Date,
    "total_revenue": pl.Float64,
    "net_profit_attr_p": pl.Float64,
    "assets_impair_loss": pl.Float64,
    "inventories": pl.Float64,
    "total_equity": pl.Float64,
    "tio2_revenue_share_approx": pl.Float64,
}


def load_tio2_company_configs(
    config_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """加载钛白粉上市公司元数据配置。"""
    p = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    if not p.exists():
        return DEFAULT_TIO2_COMPANIES
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        companies = data.get("companies", [])
        return companies if companies else DEFAULT_TIO2_COMPANIES
    except Exception as exc:
        logger.warning(f"无法读取钛白粉公司配置文件 {p}，回退默认配置: {exc}")
        return DEFAULT_TIO2_COMPANIES


def classify_valuation_regime(
    pb: float | None,
    pb_pct_10y: float | None,
    pe_ttm: float | None,
    net_profit: float | None,
) -> str:
    """基于估值反向时钟判定周期股的估值状态。

    - deep_value_trough: PB 10Y 分位 <= 20% (或 PB < 1.0 破净)，且盈利受损 (PE 为空、亏损或 PE > 30)。
      典型左侧周期底部，高赔率区间；
    - pe_trap_peak: PE_TTM < 12.0 (个位数/低市盈率估值陷阱)，且 PB 10Y 分位 >= 75.0 (或 PB >= 2.5)。
      典型右侧景气大顶，超额利润诱导低 PE 假象；
    - fair_expansion: PB 处于 20%~75% 中位且 PE 处于 12~30 正常区间，企业持续盈利。
      戴维斯双击或合理估值修复期；
    - neutral: 其他中性状态。
    """
    if pb is None:
        return "neutral"

    is_low_pb = (pb_pct_10y is not None and pb_pct_10y <= 20.0) or (pb < 1.0)
    is_earnings_depressed = (
        (pe_ttm is None)
        or (pe_ttm <= 0)
        or (pe_ttm > 30.0)
        or (net_profit is not None and net_profit <= 0)
    )
    if is_low_pb and is_earnings_depressed:
        return "deep_value_trough"

    is_low_pe = pe_ttm is not None and 0 < pe_ttm <= 12.0
    is_high_pb = (pb_pct_10y is not None and pb_pct_10y >= 75.0) or (pb >= 2.5)
    if is_low_pe and is_high_pb:
        return "pe_trap_peak"

    is_mid_pb = pb_pct_10y is not None and 20.0 < pb_pct_10y < 75.0
    is_normal_pe = pe_ttm is not None and 12.0 < pe_ttm <= 30.0
    if is_mid_pb and is_normal_pe and (net_profit is None or net_profit > 0):
        return "fair_expansion"

    return "neutral"


def empty_tio2_company_panel() -> pl.DataFrame:
    """返回符合 Schema 定义的空公司面板 DataFrame。"""
    return pl.DataFrame(schema=TIO2_COMPANY_PANEL_SCHEMA)


def empty_tio2_company_financials() -> pl.DataFrame:
    """返回符合 Schema 定义的空财务面板 DataFrame。"""
    return pl.DataFrame(schema=TIO2_COMPANY_FINANCIALS_SCHEMA)


def build_tio2_financial_panel(
    catalog: DataCatalog,
    companies: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    """提取钛白粉上市公司的季度财报与资产减值损失黄金表。"""
    cfg_list = companies or load_tio2_company_configs()
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
            "inventories",
            "total_hldr_eqy_exc_min_int",
        ],
    )

    if inc_df.is_empty():
        return empty_tio2_company_financials()

    meta_df = pl.DataFrame(
        [
            {
                "symbol": c["symbol"],
                "company_name": c.get("name", c["symbol"]),
                "process_type": c.get("process_type", "unknown"),
                "cost_tier": c.get("cost_tier", "unknown"),
                "role": c.get("role", "unknown"),
                "tio2_revenue_share_approx": float(c.get("tio2_revenue_share_approx", 0.0)),
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

    cols = list(TIO2_COMPANY_FINANCIALS_SCHEMA.keys())
    available = [c for c in cols if c in joined.columns]
    return joined.select(available).sort(["symbol", "end_date"])


def build_tio2_company_panel(
    catalog: DataCatalog,
    companies: list[dict[str, Any]] | None = None,
    config_path: Path | str | None = None,
) -> pl.DataFrame:
    """构建钛白粉上市公司日频行情、估值分位与 PIT 财报对账面板。"""
    cfg_list = companies or load_tio2_company_configs(config_path)
    symbols = [c["symbol"] for c in cfg_list]

    # 1. 加载行情与日频估值
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
        return empty_tio2_company_panel()

    # 2. 滚动 5Y / 10Y PB 与 PE-TTM 分位数
    daily_with_pct = add_rolling_percentiles(
        daily_basic,
        key="symbol",
        date_column="trade_date",
        value_columns=["pb", "pe_ttm"],
        window_5y=WINDOW_5Y_DAYS,
        window_10y=WINDOW_10Y_DAYS,
    )

    # 3. 加载并对齐季频财报（PIT 按公告日 ann_date 合并）
    fin_df = build_tio2_financial_panel(catalog, cfg_list)
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

    # 4. join_asof PIT 连接
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

    # 5. 公司属性元数据映射
    meta_df = pl.DataFrame(
        [
            {
                "symbol": c["symbol"],
                "company_name": c.get("name", c["symbol"]),
                "process_type": c.get("process_type", "unknown"),
                "cost_tier": c.get("cost_tier", "unknown"),
                "role": c.get("role", "unknown"),
                "annual_capacity_w_tons": float(c.get("annual_capacity_w_tons", 0.0)),
                "tio2_revenue_share_approx": float(c.get("tio2_revenue_share_approx", 0.0)),
            }
            for c in cfg_list
        ]
    )
    panel = joined.join(meta_df, on="symbol", how="left")

    # 6. 估值反向时钟状态判定
    regimes = [
        classify_valuation_regime(
            row["pb"],
            row["pb_percentile_10y"],
            row["pe_ttm"],
            row.get("net_profit_attr_p"),
        )
        for row in panel.iter_rows(named=True)
    ]
    panel = panel.with_columns(pl.Series("valuation_regime", regimes))

    # 7. 投影与排序列
    target_cols = list(TIO2_COMPANY_PANEL_SCHEMA.keys())
    existing_cols = [c for c in target_cols if c in panel.columns]
    return panel.select(existing_cols).sort(["trade_date", "symbol"])


__all__ = [
    "DEFAULT_TIO2_COMPANIES",
    "TIO2_COMPANY_FINANCIALS_MART_NAME",
    "TIO2_COMPANY_FINANCIALS_SCHEMA",
    "TIO2_COMPANY_PANEL_FILE",
    "TIO2_COMPANY_PANEL_LATEST_CSV",
    "TIO2_COMPANY_PANEL_MART_NAME",
    "TIO2_COMPANY_PANEL_SCHEMA",
    "build_tio2_company_panel",
    "build_tio2_financial_panel",
    "classify_valuation_regime",
    "empty_tio2_company_financials",
    "empty_tio2_company_panel",
    "load_tio2_company_configs",
]
