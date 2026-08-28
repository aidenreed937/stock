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

    直接从预加载的 market_daily 宽表中投影所需列。
    """
    return ctx.md.select(
        ["trade_date", pl.col("margin_penetration").alias("margin_pen"), "margin_buy_ratio"]
    ).sort("trade_date")


@register_fetcher("main_flow")
def fetch_main_flow(ctx: FetchContext) -> pl.DataFrame:
    """获取主力资金流多维数据：现货主力、国家队宽基ETF、散户博弈分歧与综合主力流向。"""
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
            return cg.select(
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


@register_fetcher("unlock")
def fetch_unlock(ctx: FetchContext) -> pl.DataFrame:
    """获取微观流动性冲击数据：解禁压力比例 (unlock_ratio)。

    逻辑：用未来20天的滚动解禁总额，除以全市场当下的流通总市值，度量抽血压力。
    """
    # 提取每日原始解禁金额
    un = ctx.fs.get_domain_mart("unlock_pressure_daily").select(["trade_date", "unlock_amount"])
    # 提取全市场当日流通市值
    db = ctx.md.select(["trade_date", pl.col("market_circ_mv").alias("circ_mv")])

    return (
        un.join(db, on="trade_date", how="left")
        # 滚动累加计算未来20天解禁总金额（注：原始表中的 unlock_amount 本就是按日对齐好的预期解禁额）
        .with_columns(
            pl.col("unlock_amount").rolling_sum(window_size=20).alias("unlock_amount_20d")
        )
        # 除以当日总流通市值得到比例
        .with_columns((pl.col("unlock_amount_20d") / pl.col("circ_mv")).alias("unlock_ratio"))
        .select(["trade_date", "unlock_ratio"])
        .sort("trade_date")
    )


@register_fetcher("crowdedness")
def fetch_crowdedness(ctx: FetchContext) -> pl.DataFrame:
    """获取全市场拥挤度类指标。

    使用全市场每日换手率 (market_turnover_rate) 作为核心拥挤度代理。
    换手率极高意味着买盘耗尽、交易过度拥挤。
    """
    return ctx.md.select(["trade_date", "market_turnover_rate"]).drop_nulls()
