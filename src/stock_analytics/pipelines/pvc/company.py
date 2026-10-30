"""聚氯乙烯 (PVC) 核心上市公司画像、财务与估值反向时钟模块。

消费本地 Curated 黄金事实表（TuShare daily_basic / stock_daily_bar / income / balancesheet），
对齐 PVC 产业链上市公司（中泰化学、新疆天业、三友化工、氯碱化工）的会计盈利与估值反向时钟。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_analytics.marts.shared.rolling_percentile import add_rolling_percentiles
from stock_data.catalog import DataCatalog

logger = logging.getLogger(__name__)

DEFAULT_COMPANIES_PATH = Path("config/industry/chemicals/pvc/companies.yaml")

PVC_COMPANIES_FALLBACK: list[dict[str, Any]] = [
    {
        "symbol": "002092.SZ",
        "name": "中泰化学",
        "process_type": "carbide_process",
        "annual_capacity_w_tons": 183.0,
        "cost_tier": "carbide_giant_alpha",
        "pvc_revenue_share_approx": 0.45,
    },
    {
        "symbol": "600075.SH",
        "name": "新疆天业",
        "process_type": "carbide_process",
        "annual_capacity_w_tons": 140.0,
        "cost_tier": "carbide_state_leader",
        "pvc_revenue_share_approx": 0.52,
    },
    {
        "symbol": "600409.SH",
        "name": "三友化工",
        "process_type": "carbide_process",
        "annual_capacity_w_tons": 53.0,
        "cost_tier": "integrated_cyclical",
        "pvc_revenue_share_approx": 0.18,
    },
    {
        "symbol": "600618.SH",
        "name": "氯碱化工",
        "process_type": "ethylene_process",
        "annual_capacity_w_tons": 72.0,
        "cost_tier": "ethylene_process_leader",
        "pvc_revenue_share_approx": 0.40,
    },
]


def load_pvc_companies_config(config_path: Path | str | None = None) -> list[dict[str, Any]]:
    """加载 PVC 上市公司元数据配置。"""
    p = Path(config_path or DEFAULT_COMPANIES_PATH)
    if not p.exists():
        return PVC_COMPANIES_FALLBACK
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        companies = data.get("companies", [])
        return companies if companies else PVC_COMPANIES_FALLBACK
    except Exception as exc:
        logger.warning("读取 PVC 公司配置异常: %s，回退默认配置", exc)
        return PVC_COMPANIES_FALLBACK


def classify_pvc_valuation_regime(
    pb: float | None,
    pb_pct_10y: float | None,
    pe_ttm: float | None,
    net_profit: float | None,
) -> str:
    """基于估值反向时钟判定 PVC 周期股所处的估值阶段。"""
    if pb is None:
        return "unknown"

    is_low_pb = (pb_pct_10y is not None and pb_pct_10y <= 15.0) or (pb < 0.90)
    is_impaired_or_loss = (
        (pe_ttm is None) or (pe_ttm > 30.0) or (net_profit is not None and net_profit <= 0)
    )
    if is_low_pb and is_impaired_or_loss:
        return "deep_value_trough"

    is_low_pe = pe_ttm is not None and 0 < pe_ttm < 10.0
    is_high_pb = (pb_pct_10y is not None and pb_pct_10y >= 70.0) or (pb >= 2.0)
    if is_low_pe and is_high_pb:
        return "pe_trap_peak"

    is_mid_pb = pb_pct_10y is not None and 15.0 < pb_pct_10y < 70.0
    is_normal_pe = pe_ttm is not None and 10.0 <= pe_ttm <= 25.0
    if is_mid_pb and is_normal_pe and (net_profit is None or net_profit > 0):
        return "fair_expansion"

    return "neutral"


def build_pvc_financial_panel(
    catalog: DataCatalog,
    companies: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    """提取 PVC 上市公司最新季度财报数据。"""
    cfg_list = companies or load_pvc_companies_config()
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
        return pl.DataFrame()

    meta_df = pl.DataFrame(
        [
            {
                "symbol": c["symbol"],
                "company_name": c.get("name", c["symbol"]),
                "process_type": c.get("process_type", "unknown"),
                "cost_tier": c.get("cost_tier", "unknown"),
                "pvc_revenue_share_approx": float(c.get("pvc_revenue_share_approx", 0.0)),
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
    return joined.sort(["symbol", "end_date"])


def build_pvc_company_panel(
    catalog: DataCatalog,
    companies: list[dict[str, Any]] | None = None,
    as_of_date: date | None = None,
) -> pl.DataFrame:
    """提取 PVC 上市公司行情与估值时钟面板。"""
    cfg_list = companies or load_pvc_companies_config()
    symbols = [c["symbol"] for c in cfg_list]

    daily_basic = catalog.load_dataset(
        "daily_basic",
        symbols=symbols,
        columns=[
            "symbol",
            "trade_date",
            "close",
            "turnover_rate",
            "total_mv",
            "circ_mv",
            "pb",
            "pe_ttm",
        ],
    )

    if daily_basic.is_empty():
        return pl.DataFrame()

    # 计算 5Y 与 10Y 滚动分位
    panel = add_rolling_percentiles(
        daily_basic,
        key="symbol",
        date_column="trade_date",
        value_columns=["pb", "pe_ttm"],
    )

    # 关联最新财报
    fin_df = build_pvc_financial_panel(catalog, cfg_list)
    latest_fin = (
        fin_df.sort(["symbol", "end_date"]).group_by("symbol").last()
        if not fin_df.is_empty()
        else pl.DataFrame()
    )

    meta_dict = {c["symbol"]: c for c in cfg_list}

    # 截取基准日快照
    target_date = as_of_date or daily_basic["trade_date"].max()
    sub_panel = panel.filter(pl.col("trade_date") <= target_date)
    latest_snapshot = sub_panel.sort(["symbol", "trade_date"]).group_by("symbol").last()

    records: list[dict[str, Any]] = []
    for row in latest_snapshot.iter_rows(named=True):
        sym = row["symbol"]
        meta = meta_dict.get(sym, {})
        fin_row = (
            latest_fin.filter(pl.col("symbol") == sym).row(0, named=True)
            if not latest_fin.is_empty()
            and not latest_fin.filter(pl.col("symbol") == sym).is_empty()
            else {}
        )

        pb = row.get("pb")
        pb_pct_10y = row.get("pb_percentile_10y")
        pe_ttm = row.get("pe_ttm")
        net_profit = fin_row.get("net_profit_attr_p")

        regime = classify_pvc_valuation_regime(
            pb=pb,
            pb_pct_10y=pb_pct_10y,
            pe_ttm=pe_ttm,
            net_profit=net_profit,
        )

        records.append(
            {
                "trade_date": row["trade_date"],
                "symbol": sym,
                "company_name": meta.get("name", sym),
                "process_type": meta.get("process_type", "unknown"),
                "cost_tier": meta.get("cost_tier", "unknown"),
                "annual_capacity_w_tons": meta.get("annual_capacity_w_tons", 0.0),
                "pvc_revenue_share_approx": meta.get("pvc_revenue_share_approx", 0.0),
                "close": row.get("close"),
                "total_mv": row.get("total_mv"),
                "circ_mv": row.get("circ_mv"),
                "turnover_rate": row.get("turnover_rate"),
                "pb": pb,
                "pe_ttm": pe_ttm,
                "pb_percentile_5y": row.get("pb_percentile_5y"),
                "pb_percentile_10y": pb_pct_10y,
                "valuation_regime": regime,
                "fin_report_date": fin_row.get("end_date"),
                "total_revenue": fin_row.get("total_revenue"),
                "net_profit_attr_p": net_profit,
                "assets_impair_loss": fin_row.get("assets_impair_loss"),
                "inventories": fin_row.get("inventories"),
            }
        )

    return pl.DataFrame(records).sort("pb_percentile_10y")
