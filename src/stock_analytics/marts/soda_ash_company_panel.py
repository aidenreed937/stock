"""纯碱上市公司盈利与估值反向时钟领域 Mart (soda_ash_company_panel)。

基于本地 Curated 黄金事实表（TuShare daily_basic / stock_daily_bar / income / balancesheet / fina_mainbz），
打通纯碱产业链因果链第 5 环（企业会计盈利与存货跌价放大器）与第 6 环（资本市场定价与估值反向时钟）。

Point-in-Time (PIT) 约束：
- 财务指标（归母净利、资产减值损失、存货等）严格按公告日 (ann_date) 无前视合并至日频交易序列；
- 估值分位数（PB / PE-TTM 5Y & 10Y）采用滚动历史窗口计算；
- 状态机自动识别大宗周期股反向时钟阶段 (deep_value_trough / pe_trap_peak / fair_expansion / neutral)。
"""

from __future__ import annotations

import logging
from datetime import date
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

SODA_ASH_COMPANY_PANEL_MART_NAME = "soda_ash_company_panel"
SODA_ASH_COMPANY_FINANCIALS_MART_NAME = "soda_ash_company_financials"
SODA_ASH_COMPANY_PANEL_FILE = f"{SODA_ASH_COMPANY_PANEL_MART_NAME}.parquet"
SODA_ASH_COMPANY_FINANCIALS_FILE = f"{SODA_ASH_COMPANY_FINANCIALS_MART_NAME}.parquet"
SODA_ASH_COMPANY_PANEL_LATEST_CSV = f"{SODA_ASH_COMPANY_PANEL_MART_NAME}_latest.csv"

DEFAULT_CONFIG_PATH = Path("config/industry/chemicals/soda_ash/companies.yaml")

_GENERIC_AGGREGATE_ITEMS = frozenset(
    {
        "产品",
        "主营业务",
        "主营业务收入",
        "营业收入",
        "其他",
        "其他业务",
        "其他主营业务",
        "合计",
        "合计特别调整",
        "分部抵消",
        "分部间抵销",
    }
)

SODA_ASH_COMPANY_PANEL_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "symbol": pl.Utf8,
    "company_name": pl.Utf8,
    "process_type": pl.Utf8,
    "cost_tier": pl.Utf8,
    "annual_capacity_w_tons": pl.Float64,
    "equity_ratio": pl.Float64,
    "internal_conversion_ratio": pl.Float64,
    "effective_tax_rate": pl.Float64,
    "soda_revenue_share": pl.Float64,
    "soda_revenue_share_approx": pl.Float64,
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

SODA_ASH_COMPANY_FINANCIALS_SCHEMA: dict[str, Any] = {
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
    "soda_revenue_share": pl.Float64,
    "soda_revenue_share_approx": pl.Float64,
}


def load_soda_ash_company_configs(
    config_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """加载纯碱上市公司元数据配置。唯一信任源为 YAML 配置文件。"""
    p = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"纯碱上市公司配置文件不存在: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    companies = data.get("companies", [])
    if not isinstance(companies, list) or not companies:
        raise ValueError(f"纯碱公司配置文件为空或缺少有效 companies 列表: {p}")
    return companies


def build_company_timeline_frame(
    companies: list[dict[str, Any]],
) -> pl.DataFrame:
    """展开并构建纯碱上市公司历史有效时间轴 DataFrame。

    优先读取各公司配置中的 timeline 列表；
    若未配置 timeline，则以顶层属性作为基准单条记录（effective_date 默认为 2016-01-01）。
    """
    records: list[dict[str, Any]] = []
    earliest_trading_epoch = date(2000, 1, 1)

    for c in companies:
        sym = c["symbol"]
        timeline = c.get("timeline")
        if isinstance(timeline, list) and len(timeline) > 0:
            parsed_items = []
            for item in timeline:
                eff_raw = item.get("effective_date")
                if isinstance(eff_raw, date):
                    eff_dt = eff_raw
                elif isinstance(eff_raw, str):
                    eff_dt = date.fromisoformat(eff_raw)
                else:
                    eff_dt = earliest_trading_epoch
                parsed_items.append((eff_dt, item))

            parsed_items.sort(key=lambda x: x[0])

            # 若最早生效节点晚于 2000-01-01，以首个节点数据回溯至 2000-01-01，防止历史交易日（如 2010~2015）出现空缺
            if parsed_items and parsed_items[0][0] > earliest_trading_epoch:
                first_item = parsed_items[0][1]
                records.append(
                    {
                        "symbol": sym,
                        "effective_date": earliest_trading_epoch,
                        "annual_capacity_w_tons": float(
                            first_item.get(
                                "annual_capacity_w_tons",
                                c.get("annual_capacity_w_tons", 0.0),
                            )
                        ),
                        "equity_ratio": float(
                            first_item.get("equity_ratio", c.get("equity_ratio", 1.0))
                        ),
                        "internal_conversion_ratio": float(
                            first_item.get(
                                "internal_conversion_ratio",
                                c.get("internal_conversion_ratio", 0.0),
                            )
                        ),
                        "effective_tax_rate": float(
                            first_item.get(
                                "effective_tax_rate",
                                c.get("effective_tax_rate", 0.15),
                            )
                        ),
                        "cost_tier": str(
                            first_item.get("cost_tier") or c.get("cost_tier", "unknown")
                        ),
                        "timeline_event": "历史基准回溯",
                    }
                )

            for eff_dt, item in parsed_items:
                records.append(
                    {
                        "symbol": sym,
                        "effective_date": eff_dt,
                        "annual_capacity_w_tons": float(
                            item.get(
                                "annual_capacity_w_tons",
                                c.get("annual_capacity_w_tons", 0.0),
                            )
                        ),
                        "equity_ratio": float(item.get("equity_ratio", c.get("equity_ratio", 1.0))),
                        "internal_conversion_ratio": float(
                            item.get(
                                "internal_conversion_ratio",
                                c.get("internal_conversion_ratio", 0.0),
                            )
                        ),
                        "effective_tax_rate": float(
                            item.get(
                                "effective_tax_rate",
                                c.get("effective_tax_rate", 0.15),
                            )
                        ),
                        "cost_tier": str(item.get("cost_tier") or c.get("cost_tier", "unknown")),
                        "timeline_event": str(item.get("event") or ""),
                    }
                )
        else:
            records.append(
                {
                    "symbol": sym,
                    "effective_date": earliest_trading_epoch,
                    "annual_capacity_w_tons": float(c.get("annual_capacity_w_tons", 0.0)),
                    "equity_ratio": float(c.get("equity_ratio", 1.0)),
                    "internal_conversion_ratio": float(c.get("internal_conversion_ratio", 0.0)),
                    "effective_tax_rate": float(c.get("effective_tax_rate", 0.15)),
                    "cost_tier": str(c.get("cost_tier", "unknown")),
                    "timeline_event": "基准初始配置",
                }
            )

    if not records:
        return pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "effective_date": pl.Date,
                "annual_capacity_w_tons": pl.Float64,
                "equity_ratio": pl.Float64,
                "internal_conversion_ratio": pl.Float64,
                "effective_tax_rate": pl.Float64,
                "cost_tier": pl.Utf8,
                "timeline_event": pl.Utf8,
            }
        )

    return (
        pl.DataFrame(records)
        .with_columns(pl.col("effective_date").cast(pl.Date))
        .sort(["symbol", "effective_date"])
    )


def classify_valuation_regime(
    pb: float | None,
    pb_pct_10y: float | None,
    pe_ttm: float | None,
    net_profit: float | None,
) -> str:
    """基于估值反向时钟判定大宗周期股的估值状态。

    - deep_value_trough: PB 10Y 分位 <= 15% (或 PB < 1.0 破净)，且盈利受损 (PE 为空、亏损或 PE > 30)。
      典型左侧周期底部，高赔率区间；
    - pe_trap_peak: PE_TTM < 10.0 (个位数估值陷阱)，且 PB 10Y 分位 >= 75.0 (或 PB >= 2.5)。
      典型右侧景气大顶，超额利润诱导低 PE 假象；
    - fair_expansion: PB 处于 15%~75% 中位且 PE 处于 10~30 正常区间，企业持续盈利。
      戴维斯双击或合理估值修复期；
    - neutral: 其他中性状态。
    """
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


def empty_soda_ash_company_panel() -> pl.DataFrame:
    """返回符合 Schema 定义的空公司面板 DataFrame。"""
    return pl.DataFrame(schema=SODA_ASH_COMPANY_PANEL_SCHEMA)


def empty_soda_ash_company_financials() -> pl.DataFrame:
    """返回符合 Schema 定义的空财务面板 DataFrame。"""
    return pl.DataFrame(schema=SODA_ASH_COMPANY_FINANCIALS_SCHEMA)


def build_soda_ash_financial_panel(
    catalog: DataCatalog,
    companies: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    """提取纯碱上市公司的季度财报与资产减值损失黄金表，动态计算纯碱主营业务收入占比。"""
    cfg_list = companies or load_soda_ash_company_configs()
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
        return empty_soda_ash_company_financials()

    # 动态加载主营业务构成黄金表 (fina_mainbz)，零降级计算真实纯碱业务暴露度
    try:
        mbz_df = catalog.load_dataset(
            "fina_mainbz",
            symbols=symbols,
            columns=[
                "symbol",
                "end_date",
                "bz_item",
                "bz_sales",
                "bz_code",
            ],
        )
    except Exception:
        mbz_df = pl.DataFrame()

    keyword_map = {
        c["symbol"]: c.get("soda_product_keywords")
        or (["纯碱", "联碱"] if c["symbol"] == "000707.SZ" else ["纯碱"])
        for c in cfg_list
    }

    if not mbz_df.is_empty() and "bz_item" in mbz_df.columns and "bz_sales" in mbz_df.columns:
        has_bz_code = "bz_code" in mbz_df.columns

        def _is_soda_product(sym: str, item: str | None, code: str | None) -> bool:
            if has_bz_code and code is not None and code != "P":
                return False
            if not item or item in _GENERIC_AGGREGATE_ITEMS:
                return False
            kws = keyword_map.get(sym, ["纯碱"])
            return any(k in item for k in kws)

        struct_cols = ["symbol", "bz_item"]
        if has_bz_code:
            struct_cols.append("bz_code")

        soda_matched = mbz_df.filter(
            pl.struct(struct_cols).map_elements(
                lambda s: _is_soda_product(
                    s["symbol"], s["bz_item"], s.get("bz_code") if has_bz_code else None
                ),
                return_dtype=pl.Boolean,
            )
        )
        if not soda_matched.is_empty():
            soda_rev = soda_matched.group_by(["symbol", "end_date"]).agg(
                pl.col("bz_sales").sum().alias("soda_revenue")
            )
        else:
            soda_rev = pl.DataFrame(
                schema={"symbol": pl.Utf8, "end_date": pl.Date, "soda_revenue": pl.Float64}
            )
    else:
        soda_rev = pl.DataFrame(
            schema={"symbol": pl.Utf8, "end_date": pl.Date, "soda_revenue": pl.Float64}
        )

    inc_with_soda = inc_df.join(soda_rev, on=["symbol", "end_date"], how="left")
    inc_with_soda = (
        inc_with_soda.with_columns(
            pl.when(pl.col("soda_revenue").is_not_null() & (pl.col("total_revenue") > 0))
            .then(pl.col("soda_revenue") / pl.col("total_revenue"))
            .otherwise(None)
            .alias("soda_revenue_share_raw")
        )
        .sort(["symbol", "end_date"])
        .with_columns(
            pl.col("soda_revenue_share_raw")
            .forward_fill()
            .over("symbol")
            .alias("soda_revenue_share_dyn")
        )
    )

    meta_df = pl.DataFrame(
        [
            {
                "symbol": c["symbol"],
                "company_name": c.get("name", c["symbol"]),
                "process_type": c.get("process_type", "unknown"),
                "cost_tier": c.get("cost_tier", "unknown"),
                "soda_revenue_share_fallback": float(c.get("soda_revenue_share_approx", 0.0)),
            }
            for c in cfg_list
        ]
    )

    joined = (
        inc_with_soda.rename({"n_income_attr_p": "net_profit_attr_p"})
        .join(
            bs_df.rename({"total_hldr_eqy_exc_min_int": "total_equity"}),
            on=["symbol", "end_date"],
            how="left",
        )
        .join(meta_df, on="symbol", how="left")
        .with_columns(
            pl.coalesce(
                [pl.col("soda_revenue_share_dyn"), pl.col("soda_revenue_share_fallback")]
            ).alias("soda_revenue_share")
        )
        .with_columns(pl.col("soda_revenue_share").alias("soda_revenue_share_approx"))
    )

    cols = list(SODA_ASH_COMPANY_FINANCIALS_SCHEMA.keys())
    available = [c for c in cols if c in joined.columns]
    return joined.select(available).sort(["symbol", "end_date"])


def build_soda_ash_company_panel(
    catalog: DataCatalog,
    companies: list[dict[str, Any]] | None = None,
    config_path: Path | str | None = None,
) -> pl.DataFrame:
    """构建纯碱上市公司日频行情、估值分位与 PIT 财报对账面板。"""
    cfg_list = companies or load_soda_ash_company_configs(config_path)
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
        return empty_soda_ash_company_panel()

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
    fin_df = build_soda_ash_financial_panel(catalog, cfg_list)
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
                "soda_revenue_share",
                "soda_revenue_share_approx",
            ]
        )
        .sort("fin_ann_date")
    )

    # 4. join_asof PIT 连接
    daily_sorted = daily_with_pct.sort("trade_date")
    if not fin_pit.is_empty():
        import warnings

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
                pl.lit(None).cast(pl.Float64).alias("soda_revenue_share"),
                pl.lit(None).cast(pl.Float64).alias("soda_revenue_share_approx"),
            ]
        )

    # 5. 公司静态属性与历史时间轴 (PIT) 映射
    static_meta_df = pl.DataFrame(
        [
            {
                "symbol": c["symbol"],
                "company_name": c.get("name", c["symbol"]),
                "process_type": c.get("process_type", "unknown"),
                "config_revenue_share_fallback": float(c.get("soda_revenue_share_approx", 0.0)),
                "default_capacity_fallback": float(c.get("annual_capacity_w_tons", 0.0)),
                "default_equity_fallback": float(c.get("equity_ratio", 1.0)),
                "default_conversion_fallback": float(c.get("internal_conversion_ratio", 0.0)),
                "default_tax_fallback": float(c.get("effective_tax_rate", 0.15)),
                "default_cost_tier_fallback": str(c.get("cost_tier", "unknown")),
            }
            for c in cfg_list
        ]
    )
    panel_with_static = joined.join(static_meta_df, on="symbol", how="left")

    timeline_df = build_company_timeline_frame(cfg_list)
    panel_sorted = panel_with_static.sort("trade_date")
    timeline_sorted = timeline_df.sort("effective_date")

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        panel = panel_sorted.join_asof(
            timeline_sorted,
            left_on="trade_date",
            right_on="effective_date",
            by="symbol",
            strategy="backward",
        )

    panel = panel.with_columns(
        [
            pl.coalesce(
                [pl.col("annual_capacity_w_tons"), pl.col("default_capacity_fallback")]
            ).alias("annual_capacity_w_tons"),
            pl.coalesce([pl.col("equity_ratio"), pl.col("default_equity_fallback")]).alias(
                "equity_ratio"
            ),
            pl.coalesce(
                [pl.col("internal_conversion_ratio"), pl.col("default_conversion_fallback")]
            ).alias("internal_conversion_ratio"),
            pl.coalesce([pl.col("effective_tax_rate"), pl.col("default_tax_fallback")]).alias(
                "effective_tax_rate"
            ),
            pl.coalesce([pl.col("cost_tier"), pl.col("default_cost_tier_fallback")]).alias(
                "cost_tier"
            ),
            pl.coalesce(
                [pl.col("soda_revenue_share"), pl.col("config_revenue_share_fallback")]
            ).alias("soda_revenue_share"),
        ]
    ).with_columns(pl.col("soda_revenue_share").alias("soda_revenue_share_approx"))

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
    target_cols = list(SODA_ASH_COMPANY_PANEL_SCHEMA.keys())
    existing_cols = [c for c in target_cols if c in panel.columns]
    return panel.select(existing_cols).sort(["trade_date", "symbol"])


__all__ = [
    "SODA_ASH_COMPANY_FINANCIALS_MART_NAME",
    "SODA_ASH_COMPANY_FINANCIALS_SCHEMA",
    "SODA_ASH_COMPANY_PANEL_FILE",
    "SODA_ASH_COMPANY_PANEL_LATEST_CSV",
    "SODA_ASH_COMPANY_PANEL_MART_NAME",
    "SODA_ASH_COMPANY_PANEL_SCHEMA",
    "build_company_timeline_frame",
    "build_soda_ash_company_panel",
    "build_soda_ash_financial_panel",
    "classify_valuation_regime",
    "empty_soda_ash_company_financials",
    "empty_soda_ash_company_panel",
    "load_soda_ash_company_configs",
]
