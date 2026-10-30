"""光伏设备（630500）产能周期状态 + 防守信号特征面板的腿部构建。

对齐 ``scripts/industry_solar_*.py`` 已实证实现，工程化为配置驱动、经 ``DataCatalog``
读 Curated 数据源、按 release_date/披露日生效（无前视）。

核心腿部（光伏真正验证通过的特征，非半导体式供需剪刀差——后者已证伪不生产化）：
- cycle_state ：产能周期四态 {上行, 过剩, 下行, 底部右侧}（`industry_solar_cycle_position`）。
- fin_defense ：成分股聚合净利 TTM 同比 <0 判定恶化（`industry_solar_profit_turn_ext`）。
- price_dd    ：组件周价 52 周高点回撤 %（`industry_solar_price_chain_layering`）。
- lifecycle_w / defense_w ：由 cycle_state + fin/price 映射的权重特征（供策略层消费，T+1 在策略层 shift）。

术语约定：本层产出的都是**特征（feature / 状态）**——回测/决策的输入；
**不是已验证的有效因子**。有效性由 stock_strategy 验证层确认。
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

import polars as pl

from stock_analytics.pipelines.photovoltaic.config import (
    CycleStateConfig,
    DefenseWeightConfig,
    FinDefenseConfig,
    PhotovoltaicLegsConfig,
    PricePatchConfig,
)
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

_STATE_ORDER = ["上行", "过剩", "下行", "底部右侧"]


def load_calendar(runtime: DataRuntimeContext, calendar_mart: str) -> pl.DataFrame:
    """从 Curated Mart 加载日频交易日历（仅取 trade_date）。"""
    path = runtime.data_root / "curated" / "mart" / f"{calendar_mart}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"缺少交易日历 Mart: {path}")
    return pl.read_parquet(path).select("trade_date").sort("trade_date")


def _load_curated(runtime: DataRuntimeContext, name: str) -> pl.DataFrame:
    """从 Curated industry 读数据源；缺失抛异常（本管线特征为必需）。"""
    path = runtime.data_root / "curated" / "industry" / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"缺少光伏 Curated 数据源: {path}")
    return pl.read_parquet(path)


def _load_panel(runtime: DataRuntimeContext, industry: str) -> pl.DataFrame:
    """读申万二级行业日频面板（630500 价格/收益）。"""
    path = runtime.data_root / "curated" / "mart" / "industry_l2_panel_daily.parquet"
    if not path.exists():
        raise FileNotFoundError(f"缺少行业日频面板 Mart: {path}")
    return (
        pl.read_parquet(path)
        .filter(pl.col("industry_code") == industry)
        .select(["trade_date", "close"])
        .sort("trade_date")
    )


def _monthly_pct(df: pl.DataFrame, value_col: str, window_months: int = 36) -> pl.DataFrame:
    """月频序列 → YoY → 36 月滚动分位（release_date 生效，无前视）。"""
    eff_col = "release_date" if "release_date" in df.columns else "trade_date"
    out = (
        df.select(["trade_date", *([eff_col] if eff_col != "trade_date" else []), value_col])
        .sort("trade_date")
        .with_columns(pl.col(value_col).pct_change(12).alias("yoy"))
        .drop_nulls()
    )
    pct = _rolling_pct(out["yoy"].cast(pl.Float64), window=max(window_months, 1))
    return (
        out.with_columns(pct.alias("pct")).select([eff_col, "pct"]).rename({eff_col: "trade_date"})
    )


def _rolling_pct(series: pl.Series, window: int = 36) -> pl.Series:
    """滚动历史分位 (0-100)：每个时点在过去 window 期内的分位。"""
    s = series.fill_nan(0.0).fill_null(0.0)
    return (
        s.to_frame("v")
        .select(
            pl.col("v").rolling_map(
                lambda x: float((x <= x[-1]).mean()) * 100.0 if len(x) > 0 else 50.0,
                window_size=window,
                min_samples=1,
            )
        )["v"]
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def _forward_fill(df: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    """对列做前向填充（信号生效后延伸，无前视）。"""
    exprs = [pl.col(c).fill_null(strategy="forward") for c in cols]
    return df.sort("trade_date").with_columns(exprs)


# ---------------------------------------------------------------------------
# 1. 产能周期状态（对齐 industry_solar_cycle_position）
# ---------------------------------------------------------------------------


def _state_row(
    util: float | None,
    u6: float | None,
    cy: float | None,
    flood24: float | None,
    py: float | None,
    sc: float | None,
    cfg: CycleStateConfig,
) -> str | None:
    if cy is None or util is None or flood24 is None:
        return None
    if cy >= cfg.glut_yoy_threshold:
        return "过剩"
    if flood24 >= cfg.glut_yoy_threshold:
        return "下行"
    if util >= cfg.high_util_threshold:
        return "上行"
    if util < cfg.low_util_threshold:
        if (u6 or 0) > 0 or (sc is not None and sc > 0):
            return "底部右侧"
        return "下行"
    if (u6 or 0) > 0 and (sc is None or sc > cfg.scissors_floor):
        return "上行"
    return "下行"


def build_cycle_state(
    runtime: DataRuntimeContext,
    cfg: CycleStateConfig,
) -> pl.DataFrame:
    """构建产能周期四态序列（report_month × release_date，日频保留。"""
    ps = _load_curated(runtime, "polysilicon_supply_monthly")
    sw = _load_curated(runtime, "silicon_wafer_monthly")
    sd = _load_curated(runtime, "solar_supply_demand")

    ps = ps.with_columns(
        [
            (
                pl.col("capacity_annual_w_tons") / pl.col("capacity_annual_w_tons").shift(12) - 1
            ).alias("cap_yoy"),
            (pl.col("capacity_annual_w_tons") / pl.col("capacity_annual_w_tons").shift(12) - 1)
            .rolling_max(cfg.flood_months, min_samples=1)
            .alias("flood_24m"),
            (pl.col("production_w_tons") / pl.col("production_w_tons").shift(12) - 1).alias(
                "prod_yoy"
            ),
        ]
    )
    sw = sw.with_columns(
        (
            pl.col("derived_polysilicon_utilization_rate")
            - pl.col("derived_polysilicon_utilization_rate").shift(6)
        ).alias("util_6m_chg")
    )
    skeleton = ps.select(["report_month"]).unique().sort("report_month")
    m = (
        skeleton.join(
            ps.select(["report_month", "cap_yoy", "prod_yoy", "flood_24m", "release_date"]),
            on="report_month",
            how="left",
        )
        .join(
            sw.select(["report_month", "derived_polysilicon_utilization_rate", "util_6m_chg"]),
            on="report_month",
            how="left",
        )
        .join(sd.select(["report_month", "scissors_spread_yoy"]), on="report_month", how="left")
    )
    m = m.sort("report_month").with_columns(
        pl.col("release_date").fill_null(strategy="forward"),
        pl.col("cap_yoy").fill_null(strategy="forward"),
        pl.col("prod_yoy").fill_null(strategy="forward"),
        pl.col("flood_24m").fill_null(strategy="forward"),
        pl.col("derived_polysilicon_utilization_rate").fill_null(strategy="forward"),
        pl.col("util_6m_chg").fill_null(strategy="forward"),
        pl.col("scissors_spread_yoy").fill_null(strategy="forward"),
    )
    states = [
        _state_row(
            r["derived_polysilicon_utilization_rate"],
            r["util_6m_chg"],
            r["cap_yoy"],
            r["flood_24m"],
            r["prod_yoy"],
            r["scissors_spread_yoy"],
            cfg,
        )
        for r in m.to_dicts()
    ]
    m = m.with_columns(pl.Series("state", states))
    return (
        m.drop_nulls("state")
        .select(["release_date", "state"])
        .sort("release_date")
        .unique(subset=["release_date"], keep="last")
        .sort("release_date")
    )


# ---------------------------------------------------------------------------
# 2. 财报 TTM 防守门（对齐 industry_solar_profit_turn_ext._signal）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _StockFileNotFoundError(RuntimeError):
    """成分股聚合数据缺失。"""


def _const_series(runtime: DataRuntimeContext, industry: str) -> pl.DataFrame:
    """Tushare income 成分股归母净利聚合 → 630500 季度净利 → TTM → 同比。"""
    from stock_data.catalog import DataCatalog
    from stock_data.pipeline.sw_industry_golden import load_sw_2021_industry_members

    cat_ts = DataCatalog(data_source="tushare", runtime=runtime)
    cat_lx = DataCatalog(data_source="lixinger", runtime=runtime)
    constituents = load_sw_2021_industry_members(
        cat_ts,
        current_only=True,
        canonical_only=True,
        columns=("symbol", "industry_code", "level", "is_canonical"),
    )
    if constituents.is_empty():
        constituents = load_sw_2021_industry_members(
            cat_lx,
            current_only=True,
            canonical_only=True,
            columns=("symbol", "industry_code", "level", "is_canonical"),
        )
    const = (
        constituents.filter(pl.col("industry_code") == industry)
        .get_column("symbol")
        .unique()
        .to_list()
        if not constituents.is_empty()
        else []
    )
    if not const:
        return pl.DataFrame(
            schema={"year": pl.Int64, "quarter": pl.Int64, "np_ttm": pl.Float64, "np": pl.Float64}
        )

    stock_basic = cat_ts.load_dataset("stock_basic", columns=("symbol",))
    symbol_map = (
        {
            str(symbol).split(".", 1)[0]: str(symbol)
            for symbol in stock_basic.get_column("symbol").to_list()
        }
        if not stock_basic.is_empty() and "symbol" in stock_basic.columns
        else {}
    )
    inc = cat_ts.load_dataset(
        "income", symbols=[symbol_map.get(str(code), str(code)) for code in const]
    )
    qt = (
        inc.with_columns(
            pl.col("end_date").dt.quarter().alias("q"),
            pl.col("end_date").dt.year().alias("y"),
        )
        .select(["symbol", "end_date", "y", "q", "n_income_attr_p"])
        .sort("symbol", "end_date", "q")
        .unique(subset=["symbol", "y", "q"], keep="last")
    )
    cum = qt.pivot(
        on="q", index=["symbol", "y"], values="n_income_attr_p", aggregate_function="first"
    )

    def single(
        c1: float | None, c2: float | None, c3: float | None, c4: float | None
    ) -> list[float]:
        c1 = c1 or 0
        c2 = c2 or c1
        c3 = c3 or c2
        c4 = c4 or c3
        return [c1, c2 - c1, c3 - c2, c4 - c3]

    rows = []
    for r in cum.to_dicts():
        if r["y"] is None:
            continue
        sq = single(r.get("1"), r.get("2"), r.get("3"), r.get("4"))
        for qv in [1, 2, 3, 4]:
            rows.append(
                {"symbol": r["symbol"], "year": r["y"], "quarter": qv, "single": sq[qv - 1]}
            )
    sqf = pl.DataFrame(rows)
    qsum = (
        sqf.group_by(["year", "quarter"])
        .agg(pl.col("single").sum().alias("np_q"))
        .sort(["year", "quarter"])
    )
    qtm = qsum.with_columns(
        [
            pl.col("np_q").rolling_sum(window_size=4).alias("np_ttm"),
            pl.col("np_q").shift(4).rolling_sum(window_size=4).alias("np_ttm_prev"),
        ]
    ).with_columns(
        (
            (pl.col("np_ttm") - pl.col("np_ttm_prev"))
            / pl.when(pl.col("np_ttm_prev").abs() > 0)
            .then(pl.col("np_ttm_prev").abs())
            .otherwise(None)
        ).alias("np")
    )
    return qtm.filter(pl.col("np").is_not_null())


def _disclosure_date(y: int, q: int, cfg: FinDefenseConfig) -> datetime.date:
    if q == 1:
        m, d = cfg.disclosure_q1.split("-")
    elif q == 2:
        m, d = cfg.disclosure_q2.split("-")
    elif q == 3:
        m, d = cfg.disclosure_q3.split("-")
    else:
        return datetime.date(y + 1, 4, 30)
    return datetime.date(y, int(m), int(d))


def build_fin_defense(
    runtime: DataRuntimeContext,
    industry: str,
    cfg: FinDefenseConfig,
    calendar: pl.DataFrame,
) -> pl.DataFrame:
    """财报 TTM 防守门（亏损或同比恶化判定），披露日生效，对齐日频日历。"""
    const = _const_series(runtime, industry)
    if const.is_empty():
        logger.warning("光伏 630500 成分股聚合净利为空，fin_defense 特征全 0")
        return calendar.select(["trade_date"]).with_columns(pl.lit(0.0).alias("pos"))

    # 恶化判定：TTM 净利绝对额为负（行业深度失血亏损），或同比增速低于门限
    is_neg = (
        (pl.col("np_ttm") < 0) | (pl.col("np") < cfg.net_negative_threshold)
        if "np_ttm" in const.columns
        else (pl.col("np") < cfg.net_negative_threshold)
    )

    res = (
        const.with_columns(
            pl.struct(["year", "quarter"])
            .map_elements(
                lambda r: _disclosure_date(r["year"], r["quarter"], cfg), return_dtype=pl.Date
            )
            .alias("disclose")
        )
        .sort("disclose")
        .unique(subset=["disclose"], keep="last")
        .sort("disclose")
        .with_columns(is_neg.cast(pl.Float64).alias("neg"))
        .select(["disclose", "neg"])
    )
    return (
        calendar.join(res.rename({"disclose": "trade_date"}), on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("neg").fill_null(strategy="forward").fill_null(0.0))
        .select(["trade_date", "neg"])
        .rename({"neg": "pos"})  # pos 命名对齐 research，1=恶化, 0=健康
    )


# ---------------------------------------------------------------------------
# 3. 价格回撤补丁（对齐 industry_solar_price_chain_layering._price_drawdown）
# ---------------------------------------------------------------------------


def build_price_drawdown(
    runtime: DataRuntimeContext,
    cfg: PricePatchConfig,
    calendar: pl.DataFrame,
) -> pl.DataFrame:
    """组件周价 → 滚动 N 周高点回撤 % → 日频（trade_date 生效、前向填充）。"""
    price = _load_curated(runtime, "solar_price_chain").sort("trade_date")
    dd = (
        price[cfg.price_col] / price[cfg.price_col].rolling_max(cfg.drawdown_weeks, min_samples=1)
        - 1.0
    ) * 100.0
    leg = price.select(["trade_date"]).with_columns(dd.alias("price_dd"))
    return (
        calendar.join(leg, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("price_dd").fill_null(strategy="forward"))
        .select(["trade_date", "price_dd"])
    )


# ---------------------------------------------------------------------------
# 面板组装
# ---------------------------------------------------------------------------

_ALERT_STATES = {"过剩", "下行"}


def build_photovoltaic_legs_panel(
    config: PhotovoltaicLegsConfig,
    calendar: pl.DataFrame,
    runtime: DataRuntimeContext,
) -> pl.DataFrame:
    """组装 630500 周期状态 + 防守信号特征面板（日频，release_date 生效）。"""
    industry = config.industry_codes[0]
    panel = (
        _load_panel(runtime, industry)
        .join(calendar, on="trade_date", how="inner")
        .sort("trade_date")
        .with_columns(pl.col("close").pct_change().fill_null(0.0).alias("ret"))
    )

    cyc = build_cycle_state(runtime, config.cycle_state or CycleStateConfig())
    fin = build_fin_defense(runtime, industry, config.fin_defense or FinDefenseConfig(), calendar)
    price_cfg = config.price_patch or PricePatchConfig()
    price = build_price_drawdown(runtime, price_cfg, calendar)

    lifecycle = config.lifecycle_weights or {
        "上行": 1.0,
        "过剩": 0.0,
        "下行": 0.8,
        "底部右侧": 0.5,
    }
    dw = config.defense_weight or DefenseWeightConfig()

    df = (
        panel.filter(pl.col("trade_date") >= cyc["release_date"].min())
        .join(cyc.rename({"release_date": "trade_date"}), on="trade_date", how="left")
        .join(fin, on="trade_date", how="left")
        .join(price, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(
            pl.col("state").fill_null(strategy="forward"),
            pl.col("pos").fill_null(strategy="forward").fill_null(0.0),
            pl.col("price_dd").fill_null(strategy="forward"),
        )
        .drop_nulls(["state"])  # 面板起点对齐状态机可用期起，保证每条记录都有周期状态
    )

    state = df["state"].to_list()
    neg = df["pos"].to_list()
    dd = df["price_dd"].to_list()
    lw = []
    a_cyc = []
    a_fin = []
    a_price = []
    daw = []
    for i in range(len(df)):
        s = state[i]
        lw.append(lifecycle.get(s, dw.hold))
        c_alert = s in _ALERT_STATES
        f_alert = neg[i] >= 0.5
        p_alert = dd[i] is not None and dd[i] <= -price_cfg.gate_threshold
        a_cyc.append(c_alert)
        a_fin.append(f_alert)
        a_price.append(bool(p_alert))
        # 三源防守：cycle/fin 任一触发 → reduced(0.25)；价格回撤≥阈值 → 更深空仓(0.0) 补丁
        if p_alert:
            daw.append(dw.empty)
        elif c_alert or f_alert:
            daw.append(dw.reduced)
        else:
            daw.append(dw.hold)

    df = df.with_columns(
        pl.Series("lifecycle_w", lw),
        pl.Series("al_cycle", a_cyc),
        pl.Series("al_fin", a_fin),
        pl.Series("al_price", a_price),
        pl.Series("defense_w", daw),
    )
    return df.drop_nulls("close").select(
        [
            "trade_date",
            "close",
            "ret",
            "state",
            "price_dd",
            "lifecycle_w",
            "al_cycle",
            "al_fin",
            "al_price",
            "defense_w",
        ]
    )


__all__ = [
    "build_cycle_state",
    "build_fin_defense",
    "build_photovoltaic_legs_panel",
    "build_price_drawdown",
    "load_calendar",
]
