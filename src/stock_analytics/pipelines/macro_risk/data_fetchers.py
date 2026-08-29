"""系统性风险管线：原始因子数据提取器与注册表。

本模块仅负责“如何获取数据”（Data I/O），坚守架构纯洁性。
不包含任何因子的业务计算逻辑（如计算周期、滚动分位、反转、权重分配等）。
所有的因子业务参数均应在 `config/analytics/macro_risk.yaml` 中配置。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import polars as pl

from stock_analytics.features import FeatureStore
from stock_analytics.metrics.context import MetricContext
from stock_analytics.metrics.engine import MetricEngine
from stock_data.catalog import DataCatalog


@dataclass
class FetchContext:
    """数据提取上下文。

    作为中介者（Mediator），将所有可能用到的底层数据源连接提供给各个提取器。
    """

    cat: DataCatalog  # 默认数据目录（主要连接本地 Lixinger 等数据）
    cat_yf: DataCatalog  # 海外数据目录（专门连接 yfinance 获取全球宏观）
    fs: FeatureStore  # 特征存储（用于读取各种清洗好的 Mart 宽表）
    md: pl.DataFrame  # market_daily 缓存（全市场每日聚合宽表，由于复用率极高，在此做预加载缓存）
    metric_engine: MetricEngine = field(default_factory=MetricEngine)  # 标准指标调度引擎

    @property
    def metric_context(self) -> MetricContext:
        """动态生成标准指标计算的上下文环境。

        统一回溯至 2010 年，以保证最长 10 年滚动窗口（约2500个交易日）有充足的冷启动数据。
        """
        return MetricContext(start_date=date(2010, 1, 1), catalog=self.cat)


def _shift_to_next_trading_day(
    frame: pl.DataFrame,
    cal: pl.DataFrame,
    shift_cols: list[str],
    date_col: str = "trade_date",
) -> pl.DataFrame:
    """把 ``shift_cols`` 列的值整体平移至下一交易日（消除 T+1 发布时滞前视）。

    适用于 T 日收盘后才公布的日终数据（如两融、ETF 份额变动）：
    将 T-1 日的值打戳到 T 日，使 T 日收盘仅可使用 T-1 日及以前的信息。
    ``cal`` 为升序、无重复的交易日历（含 ``date_col``）。
    """
    cal_idx = cal.select(date_col).sort(date_col).with_row_index("_idx")
    return (
        frame.drop_nulls(subset=shift_cols)
        .join(cal_idx, on=date_col, how="left")
        .with_columns((pl.col("_idx") + 1).alias("_next_idx"))
        .drop("_idx")
        .join(
            cal_idx.select(["_idx", date_col]).rename(
                {"_idx": "_next_idx", date_col: "_shifted_date"}
            ),
            on="_next_idx",
            how="left",
        )
        .drop("_next_idx")
        .with_columns(pl.col("_shifted_date").alias(date_col))
        .select([date_col, *shift_cols])
        .drop_nulls(subset=[date_col])
        .sort(date_col)
    )


# ============================================================================
# 提取器注册表 (Registry Pattern)
# ============================================================================

# 全局字典，映射 因子簇名称 -> 提取函数
FETCHER_REGISTRY: dict[str, Callable[[FetchContext], pl.DataFrame]] = {}


def register_fetcher(
    name: str,
) -> Callable[[Callable[[FetchContext], pl.DataFrame]], Callable[[FetchContext], pl.DataFrame]]:
    """装饰器：将一个提取函数注册到全局提取器表中。

    Args:
        name: 配置文件中 `series` 字段对应的标识符（如 "valuation", "vix"）。
    """

    def decorator(
        func: Callable[[FetchContext], pl.DataFrame],
    ) -> Callable[[FetchContext], pl.DataFrame]:
        FETCHER_REGISTRY[name] = func
        return func

    return decorator


# ============================================================================
# 具体数据提取器 (Concrete Fetchers)
# 职责：返回包含 `trade_date` 及其对应因子列的 Polars DataFrame。
# ============================================================================


@register_fetcher("valuation")
def fetch_valuation(ctx: FetchContext) -> pl.DataFrame:
    """获取估值类指标：ERP（股权风险溢价）与 PB（市净率）。

    使用标准指标引擎实时计算，彻底与底层的基本面表和国债表解耦。
    由于底层 index_fundamental 包含多个指数，这里显式过滤 "000985" (中证全指) 作为全市场基准。
    """
    # 召唤指标引擎计算 ERP
    results = ctx.metric_engine.compute(["equity_risk_premium"], context=ctx.metric_context)
    erp_frame = (
        results[0].frame.filter(pl.col("symbol") == "000985").rename({"equity_risk_premium": "erp"})
    )

    # 获取 PB 原始值。通过标准的 load_metric_dataset 接口从 index_fundamental 加载
    from stock_analytics.metrics.datasets.loaders import load_metric_dataset

    pb_raw = (
        load_metric_dataset(
            ctx.metric_context, "index_fundamental", columns=["trade_date", "symbol", "pb.mcw"]
        )
        .filter(pl.col("symbol") == "000985")
        .rename({"pb.mcw": "pb"})
    )

    # 拼接 ERP 和 PB 并返回
    return erp_frame.select(["trade_date", "erp"]).join(
        pb_raw.select(["trade_date", "pb"]), on="trade_date", how="left"
    )


@register_fetcher("vix")
def fetch_vix(ctx: FetchContext) -> pl.DataFrame:
    """获取外部宏观情绪指标：VIX（恐慌指数）。

    由于 VIX 是美股时间线，指标引擎内部已封装了加一天的时区平移对齐逻辑。
    """
    # 切换到 YFinance 的 Catalog 上下文
    yf_ctx = MetricContext(start_date=date(2010, 1, 1), catalog=ctx.cat_yf)

    # 通过指标引擎直接获取对齐好的 vix 序列
    results = ctx.metric_engine.compute(["vix"], context=yf_ctx)
    return results[0].frame.select(["trade_date", "vix"])


@register_fetcher("leverage")
def fetch_leverage(ctx: FetchContext) -> pl.DataFrame:
    """获取杠杆类情绪数据：融资余额占比 (margin_pen) 与 融资买入额占比 (margin_buy_ratio)。

    两融数据为 T+1 早间公布（T 日收盘尚不可得），为消除发布时滞前视，
    将原始值按 market_daily 交易日历整体平移至下一交易日（T 日仅可用 T-1 日两融值）。
    """
    lev = ctx.md.select(
        [
            "trade_date",
            pl.col("margin_penetration").alias("margin_pen"),
            "margin_buy_ratio",
        ]
    )
    if ctx.md.is_empty() or "trade_date" not in ctx.md.columns:
        return lev
    return _shift_to_next_trading_day(lev, ctx.md, shift_cols=["margin_pen", "margin_buy_ratio"])


@register_fetcher("main_flow")
def fetch_main_flow(ctx: FetchContext) -> pl.DataFrame:
    """获取主力资金流多维数据：现货主力、国家队宽基ETF、散户博弈分歧与综合主力流向。

    ETF 资金流由日终份额变动（Δ份额 × 收盘价）计算，T+1 早间才公布：
    对 ``etf_flow_ratio`` 按交易日历平移至下一交易日，消除发布时滞前视。
    复合列 ``composite_flow``（含 1.2×ETF 净流入分量）与 ``divergence_score``
    （含龙虎榜/两融成分）为混合口径，经 1250 日滚动分位与维度均值平滑后
    时滞影响有限，暂不平移。
    """
    try:
        cg = ctx.fs.get_domain_mart("capital_game_daily")
    except Exception:
        cg = pl.DataFrame()

    if not cg.is_empty() and "trade_date" in cg.columns:
        cols_needed = [
            "trade_date",
            "main_order_net_inflow",
            "broad_etf_net_inflow",
            "total_turnover",
            "divergence_score",
        ]
        if all(c in cg.columns for c in cols_needed):
            frame = cg.select(
                pl.col("trade_date").cast(pl.Date),
                pl.when(pl.col("total_turnover") > 0)
                .then(
                    (pl.col("main_order_net_inflow") + 1.2 * pl.col("broad_etf_net_inflow"))
                    / pl.col("total_turnover")
                )
                .otherwise(None)
                .alias("composite_flow"),
                pl.col("main_order_flow_ratio").alias("main_ratio"),
                pl.col("broad_etf_flow_ratio").alias("etf_flow_ratio"),
                pl.col("divergence_score").alias("divergence_score"),
            ).sort("trade_date")
            # 交易日历不可用时跳过平移（保留原始时序），仅在有完整日历时执行 PIT 修复
            if ctx.md.is_empty() or "trade_date" not in ctx.md.columns:
                return frame
            etf_shifted = _shift_to_next_trading_day(
                frame.select(["trade_date", "etf_flow_ratio"]),
                ctx.md.select("trade_date"),
                shift_cols=["etf_flow_ratio"],
            )
            return frame.drop("etf_flow_ratio").join(etf_shifted, on="trade_date", how="left")

    # Fallback to market_daily
    return ctx.md.select(
        pl.col("trade_date").cast(pl.Date),
        pl.col("main_net_inflow_ratio").alias("main_ratio"),
        pl.col("main_net_inflow_ratio").alias("composite_flow"),
        pl.lit(0.0).alias("etf_flow_ratio"),
        pl.lit(0.0).alias("divergence_score"),
    ).sort("trade_date")


@register_fetcher("breadth")
def fetch_breadth(ctx: FetchContext) -> pl.DataFrame:
    """获取市场广度数据：涨跌家数比 (adv_dec) 与 60日新高占比 (newhigh60_ratio)。"""
    return ctx.md.select(
        [
            "trade_date",
            pl.col("adv_dec_ratio").alias("adv_dec"),
            pl.col("new_high_60d_ratio").alias("newhigh60_ratio"),
        ]
    ).sort("trade_date")


@register_fetcher("pcr")
def fetch_pcr(ctx: FetchContext) -> pl.DataFrame:
    """获取期权情绪数据：认沽认购成交比 (pcr)。"""
    return ctx.md.select(["trade_date", pl.col("option_put_call_volume_ratio").alias("pcr")]).sort(
        "trade_date"
    )


@register_fetcher("iv")
def fetch_iv(ctx: FetchContext) -> pl.DataFrame:
    """获取期权隐含波动率：IV。

    读取 settlement_iv_proxy_daily 数据集，将各主力合约的 IV 中位数再次在时间切片上做截面均值聚合。
    """
    return (
        ctx.fs.get_domain_mart("settlement_iv_proxy_daily")
        .select(["trade_date", "settlement_iv_proxy_median"])
        .group_by("trade_date")
        .agg(pl.col("settlement_iv_proxy_median").mean().alias("iv"))
        .sort("trade_date")
    )


@register_fetcher("crowdedness")
def fetch_crowdedness(ctx: FetchContext) -> pl.DataFrame:
    """获取全市场拥挤度类指标：全市场每日换手率 (market_turnover_rate)。"""
    return ctx.md.select(["trade_date", "market_turnover_rate"]).drop_nulls()


@register_fetcher("fund_issuance")
def fetch_fund_issuance(ctx: FetchContext) -> pl.DataFrame:
    """获取公募基金新发规模与 5 年滚动历史分位。

    用于刻画场外散户增量流动性与情绪过热/冰点。
    """
    try:
        fi = ctx.fs.get_domain_mart("fund_issuance_monthly")
    except Exception:
        fi = pl.DataFrame()

    if fi.is_empty():
        try:
            from stock_analytics.marts.fund_issuance import build_fund_issuance_frame

            cat_ts = DataCatalog(runtime=ctx.cat.runtime, data_source="tushare")
            fb = cat_ts.load_dataset("fund_basic")
            fi = build_fund_issuance_frame(fb)
        except Exception:
            fi = pl.DataFrame()

    if fi.is_empty() or "month" not in fi.columns:
        return ctx.md.select(["trade_date"]).with_columns(
            pl.lit(None, dtype=pl.Float64).alias("fund_issue_pct5y")
        )

    cal = ctx.md.select(["trade_date"]).with_columns(
        pl.col("trade_date").cast(pl.Date).dt.to_string("%Y-%m").alias("month")
    )
    return (
        cal.join(
            fi.select(["month", pl.col("equity_issue_pct5y").alias("fund_issue_pct5y")]),
            on="month",
            how="left",
        )
        .select(["trade_date", "fund_issue_pct5y"])
        .sort("trade_date")
    )


@register_fetcher("convertible_bond")
def fetch_convertible_bond(ctx: FetchContext) -> pl.DataFrame:
    """获取全市场可转债价格中位数。"""
    try:
        cb = ctx.fs.get_domain_mart("convertible_bond_daily")
    except Exception:
        cb = pl.DataFrame()

    if not cb.is_empty() and "trade_date" in cb.columns and "cb_price_median" in cb.columns:
        return cb.select(
            [
                pl.col("trade_date").cast(pl.Date),
                pl.col("cb_price_median").cast(pl.Float64, strict=False),
            ]
        ).sort("trade_date")
    return ctx.md.select(["trade_date"]).with_columns(
        pl.lit(None, dtype=pl.Float64).alias("cb_price_median")
    )


@register_fetcher("global_macro")
def fetch_global_macro(ctx: FetchContext) -> pl.DataFrame:
    """获取全球宏观指标：美债 10Y-2Y 利差与铜金比。"""
    try:
        gm = ctx.fs.get_domain_mart("global_macro_daily")
    except Exception:
        gm = pl.DataFrame()

    if not gm.is_empty() and "trade_date" in gm.columns:
        cols = [pl.col("trade_date").cast(pl.Date)]
        if "us_yield_curve_10y_2y" in gm.columns:
            cols.append(pl.col("us_yield_curve_10y_2y").cast(pl.Float64, strict=False))
        else:
            cols.append(pl.lit(None, dtype=pl.Float64).alias("us_yield_curve_10y_2y"))

        if "copper_gold_ratio" in gm.columns:
            cols.append(pl.col("copper_gold_ratio").cast(pl.Float64, strict=False))
        else:
            cols.append(pl.lit(None, dtype=pl.Float64).alias("copper_gold_ratio"))

        return gm.select(cols).sort("trade_date")

    return ctx.md.select(["trade_date"]).with_columns(
        pl.lit(None, dtype=pl.Float64).alias("us_yield_curve_10y_2y"),
        pl.lit(None, dtype=pl.Float64).alias("copper_gold_ratio"),
    )


# 底部导入：触发 corporate_fetchers 模块注册 corporate 提取器到 FETCHER_REGISTRY
from stock_analytics.pipelines.macro_risk.corporate_fetchers import (  # noqa: E402, F401
    fetch_corporate,
)
