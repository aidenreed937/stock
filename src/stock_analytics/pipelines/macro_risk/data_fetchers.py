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
from stock_analytics.pipelines.macro_risk.fred import (
    load_dff_series,
)
from stock_analytics.primitives import calculate_dff_change_6m
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog


@dataclass
class FetchContext:
    """数据提取上下文。

    作为中介者（Mediator），将所有可能用到的底层数据源连接提供给各个提取器。
    """

    cat: DataCatalog  # 默认数据目录（主要连接本地 Lixinger 等数据）
    cat_yf: DataCatalog  # 海外行情目录；VIX 等宏观序列优先读取 FRED
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

    VIX 主源为 FRED 的 CBOE 收盘序列；指标引擎内部封装了加一天的时区平移对齐逻辑。
    """
    # 保留海外上下文的时间窗口与存储根目录，指标计算器内部优先读取 FRED。
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

    PIT 严格对齐：
    1. ETF 资金流由日终份额变动（Δ份额 × 收盘价）计算，T+1 早间公布；
    2. 复合列 ``composite_flow``（含 ETF 净流入分量）与 ``divergence_score``（含龙虎榜/两融成分）均为混合/次晨披露口径；
    对上述列按交易日历平移至下一交易日，彻底消除发布时滞前视偏差。
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
            shifted = _shift_to_next_trading_day(
                frame.select(
                    ["trade_date", "etf_flow_ratio", "composite_flow", "divergence_score"]
                ),
                ctx.md.select("trade_date"),
                shift_cols=["etf_flow_ratio", "composite_flow", "divergence_score"],
            )
            return frame.drop(["etf_flow_ratio", "composite_flow", "divergence_score"]).join(
                shifted, on="trade_date", how="left"
            )

    # Fallback to market_daily（capital_game_daily Mart 缺失时的降级路径）
    logger.warning(
        "capital_game_daily Mart 缺失，main_flow 降级为 market_daily 主力净流入比；"
        "etf_flow_ratio / divergence_score 置空，避免 0 值经分位反转污染 dim_flow/panic"
    )
    return ctx.md.select(
        pl.col("trade_date").cast(pl.Date),
        pl.col("main_net_inflow_ratio").alias("main_ratio"),
        pl.col("main_net_inflow_ratio").alias("composite_flow"),
        pl.lit(None, dtype=pl.Float64).alias("etf_flow_ratio"),
        pl.lit(None, dtype=pl.Float64).alias("divergence_score"),
    ).sort("trade_date")


@register_fetcher("breadth")
def fetch_breadth(ctx: FetchContext) -> pl.DataFrame:
    """获取市场广度数据：涨跌家数比、60日新高占比与 52 周新低占比。

    ``newlow252_ratio`` 为 market_daily 已物化的 ``new_low_252d_ratio``（252 交易日
    滚动新低股票占比），用于衡量恐慌端出清广度；宏观因子层只注册为独立观测，
    不进入 dim_breadth 与双轨指数（口径见 ``config/analytics/macro_risk.yaml``）。
    """
    return ctx.md.select(
        [
            "trade_date",
            pl.col("adv_dec_ratio").alias("adv_dec"),
            pl.col("new_high_60d_ratio").alias("newhigh60_ratio"),
            pl.col("new_low_252d_ratio").alias("newlow252_ratio"),
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


@register_fetcher("global_macro_monthly")
def fetch_global_macro_monthly(ctx: FetchContext) -> pl.DataFrame:
    """获取按月抽样的铜金比，供月频历史分位计算。"""
    try:
        gm = ctx.fs.get_domain_mart("global_macro_daily")
    except Exception:
        gm = pl.DataFrame()
    if gm.is_empty() or not {"trade_date", "copper_gold_ratio"}.issubset(gm.columns):
        return pl.DataFrame(schema={"trade_date": pl.Date, "copper_gold_ratio": pl.Float64})

    # Mart 中的铜金比已经完成无前视日频 asof；每月只保留最后一个可用观测，
    # 避免把同一个月频铜价重复按交易日计权。
    return (
        gm.select(
            pl.col("trade_date").cast(pl.Date),
            pl.col("copper_gold_ratio").cast(pl.Float64, strict=False),
        )
        .drop_nulls()
        .sort("trade_date")
        .with_columns(pl.col("trade_date").dt.month_start().alias("_month"))
        .group_by("_month", maintain_order=True)
        .agg(
            pl.col("trade_date").last().alias("trade_date"),
            pl.col("copper_gold_ratio").last().alias("copper_gold_ratio"),
        )
        .select(["trade_date", "copper_gold_ratio"])
        .sort("trade_date")
    )


@register_fetcher("fed_rate")
def fetch_fed_rate(ctx: FetchContext) -> pl.DataFrame:
    """美联储有效利率 DFF 六个月变化（加息/降息周期特征，pp 口径）。

    历史研究（基于月频 FEDFUNDS，DFF 换源后尚未复验）显示，加息周期对成长/科技估值有压制
    （scripts/semi_sox_backtest 机制延伸；2026-09 对 270100 全周期 IC -0.30、样本外 -0.345；
    对中证全指全周期 -0.21）。
    但分年 IC 符号跨周期漂移（-0.75 ~ +0.57），与 us_yield_curve 同类，
    故仅注册为独立观测因子，不进入维度与双轨指数（保持 panic/overheat 成分纯净）。
    数据：FRED 日频 DFF，六个日历月前取最近观测计算差值；按 H.15 下一个联储工作日的发布时间
    映射到北京时间可用日期，再 asof 到 A 股日频。
    """
    series = load_dff_series()
    ffr = calculate_dff_change_6m(series.frame)
    if ffr.is_empty():
        return pl.DataFrame(schema={"trade_date": pl.Date, "ffr_chg_6m": pl.Float64})
    try:
        md = ctx.md.select(["trade_date"]).sort("trade_date")
    except Exception:
        return ffr.sort("trade_date")
    return md.join_asof(ffr.sort("trade_date"), on="trade_date", strategy="backward")


@register_fetcher("smart_money")
def fetch_smart_money(ctx: FetchContext) -> pl.DataFrame:
    """获取聪明钱组合信号：产业资本增持 + 大宗折价接盘 + 国家队股东锚点。

    信号由 ``smart_money_daily`` 领域 Mart 物化（构建入口
    ``DomainMartBuilder.build_smart_money``），此处直接读取。
    """
    try:
        sm = ctx.fs.get_domain_mart("smart_money_daily")
    except Exception:
        sm = pl.DataFrame()
    if sm.is_empty() or "trade_date" not in sm.columns:
        return pl.DataFrame(schema={"trade_date": pl.Date, "smart_money_score": pl.Float64})
    return sm.select(["trade_date", "smart_money_score"]).sort("trade_date")


# 底部导入：触发 corporate_fetchers 模块注册 corporate 提取器到 FETCHER_REGISTRY
from stock_analytics.pipelines.macro_risk.corporate_fetchers import (  # noqa: E402, F401
    fetch_corporate,
)
