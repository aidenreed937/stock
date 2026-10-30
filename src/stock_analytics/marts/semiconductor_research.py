"""半导体产业深研统一面板 Mart（semiconductor_research_panel）。

设计定位（2026-09 修正方案）：
- **L2 深研统一面板**：把剪刀差主腿、成熟制程库存腿（IDM + 渠道）、确认腿、
  驱动源识别、宏观背景、信号状态机收敛为一张日频 × 行业宽表。
- **面板日历自 2014-01-01 起**（对齐剪刀差框架起点，受 TSMC demand 腿 2014 起约束）；
  渠道库存黄金表已回补至 2009Q2，2009-2013 历史保留在季度粒度黄金表
  （`semiconductor_channel_inventory.parquet`）供研究回溯，不进入面板日频序列；
  面板内渠道分位按**全历史**（2009Q2 起）计算，分位定位不受日历截断影响。
  **口径告警**：`idm_weighted_doi_pct` / `channel_weighted_doi_pct` 由
  `_full_sample_percentile` 生成，属**全样本口径**（排序含未来期，隐含前视），
  仅适用于"最新值的历史相对位置"定位，**禁止用于回测或历史时点解读**；
  规范要求的滚动窗口口径（5Y/10Y）见 `marts/shared/rolling_percentile.py`（待迁移）。
- **不做静态制程标签**：实证表明制程二分（先进/成熟）只在 AI 轮有区分度
  （2024-2026 美洲-中国区分化 +40.2pp），存储轮/缺芯轮失真——因此用
  **驱动源识别列**（`americas_china_spread` + `driver_regime`）替代静态列。
- **定位声明（重要）**：驱动识别列（`americas_china_spread` / `driver_regime` /
  `ai_capex_leg_active`）是**归因/说明层，不作交易信号**——实测这些列对未来收益
  IC 不显著（r≈0.03/-0.16/+0.05），只用于理解"这轮谁在驱动、当前腿是否还活着"。
- **换轮换腿**：结构性腿（ai_capex）分年 IC 剧烈翻转（2021 +0.579 → 2025 -0.532 →
  2026 -0.868），`ai_capex_leg_active` 用最近 126 交易日滚动 IC 符号标记当前有效性。

输入（原始输入点均来自本地 Curated/产物，且按 `release_date` 生效，无前视；
派生列中的两个 `*_doi_pct` 为全样本分位口径，见上方「口径告警」）：
- 剪刀差主腿：`data/analytics/semiconductor/latest/semiconductor_legs.parquet`
- IDM 库存：`data/curated/industry/semiconductor_inventory_days.parquet`
- 渠道库存：`data/curated/industry/semiconductor_channel_inventory.parquet`
- GM 确认：`data/curated/mart/semiconductor_gm_confirm_legs.parquet`
- 供给确认：`data/curated/mart/semiconductor_supply_legs.parquet`
- 驱动源识别：`data/curated/industry/semiconductor_sales.parquet`（分地区 YoY）
- 宏观背景：FRED DFF + `risk_factors.parquet`（ffr_chg_6m_score）
- 行情：`industry_l2_panel_daily.parquet`（amount_yi / pe5y，crowd 触发位用）
"""

from __future__ import annotations

import logging
import math
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.primitives import calculate_dff_change_6m
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

SEMICONDUCTOR_RESEARCH_MART_NAME = "semiconductor_research_panel"


def _resolve_curated_industry_path(
    root: Path, relative_subdir_file: str, legacy_filename: str
) -> Path:
    target = root / "curated" / "industry" / relative_subdir_file
    if target.exists():
        return target
    return root / "curated" / "industry" / legacy_filename


SEMICONDUCTOR_RESEARCH_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "industry_code": pl.Utf8,
    # 主腿（剪刀差体系）
    "demand_score": pl.Float64,
    "supply_score": pl.Float64,
    "scissors_score": pl.Float64,
    # 成熟制程库存腿（IDM 厂商侧 + 渠道流通侧）
    "idm_weighted_doi_days": pl.Float64,
    "idm_weighted_doi_pct": pl.Float64,
    "idm_regime": pl.Utf8,
    "channel_weighted_doi_days": pl.Float64,
    "channel_weighted_doi_pct": pl.Float64,
    "channel_regime": pl.Utf8,
    # 确认腿
    "gm_cross": pl.Float64,
    "ai_capex_score": pl.Float64,
    "utilization_score": pl.Float64,
    # 存储先导动能腿 (P2: 台湾存储龙头高频营运)
    "nanya_revenue_yoy": pl.Float64,
    "adata_revenue_yoy": pl.Float64,
    "memory_lead_yoy": pl.Float64,
    "memory_module_idm_spread": pl.Float64,
    "memory_lead_regime": pl.Utf8,
    # 驱动源识别（归因/说明层，不作交易信号）
    "americas_china_spread": pl.Float64,
    "driver_regime": pl.Utf8,
    "ai_capex_leg_active": pl.Boolean,
    # 宏观背景（提示层，不作策略门）
    "ffr_chg_6m": pl.Float64,
    "ffr_chg_6m_score": pl.Float64,
    # 信号状态机（防守/进攻/crowd 触发位）
    "defense_trigger": pl.Boolean,
    "offense_trigger": pl.Boolean,
    "crowd_trigger": pl.Boolean,
}

# 信号状态机阈值（methodology 定稿，不重炒）
_DEFENSE_SCISSORS_LT = 0.0
_DEFENSE_DOI_GE = 70.0
_OFFENSE_DEMAND_GE = 70.0
_CROWD_SHARE_GE = 90.0
_CROWD_PE5Y_GE = 80.0
_CROWD_WINDOW = 250

# 驱动源识别阈值（2026-09 四轮实证校准：AI 轮 +40pp / 存储轮 +16pp / 缺芯轮 ≈0 / 下行全球负）
_AI_SPREAD_GE = 25.0  # 美洲-中国区分化 ≥25pp = AI 驱动（2024-2026 实测 +40.2pp）
_LEG_IC_WINDOW = 126  # ai_capex 滚动 IC 窗口（约半年）

_IDM_REGIME_TH = (150.0, 130.0, 105.0)  # high_overstocked / elevated / normal / tight
_CHANNEL_REGIME_TH = (85.0, 70.0, 55.0)  # 渠道口径（2009Q2 起 69 季全历史，阈值经验值并标注）

_DATA_ROOT = Path("data")


def empty_semiconductor_research_panel() -> pl.DataFrame:
    """返回稳定 schema 的空面板。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_RESEARCH_SCHEMA)


def _quarterly_to_daily_forward(
    quarterly: pl.DataFrame,
    calendar: pl.DataFrame,
    *,
    release_col: str = "release_date",
) -> pl.DataFrame:
    """季度表 → 按 release_date 生效（无前视）→ asof 对齐日频前向填充。

    输入须含 release_col 与至少一个数值列（由调用方重命名）；所有数值列
    （原始值 + 分位等派生列）一并前向填充，保证派生列与原始列同源同步。
    """
    if quarterly.is_empty() or release_col not in quarterly.columns:
        return pl.DataFrame()
    value_cols = [c for c in quarterly.columns if c != release_col]
    if not value_cols:
        return pl.DataFrame()
    eff = (
        quarterly.select([release_col, *value_cols])
        .drop_nulls()
        .rename({release_col: "trade_date"})
    )
    if eff.is_empty():
        return pl.DataFrame()
    return (
        calendar.select("trade_date")
        .join_asof(eff.sort("trade_date"), on="trade_date", strategy="backward")
        .sort("trade_date")
        .with_columns([pl.col(c).fill_null(strategy="forward") for c in value_cols])
    )


def _full_sample_percentile(series: pl.Series) -> pl.Series:
    """全样本分位（0-100）：当前值在**全历史样本**中的分位。

    .. warning::
        本函数按整条序列排序（含未来期），因此每个历史时点的分位都隐含**前视**信息，
        仅适用于"当前最新值在历史中的相对位置"这类截面定位，
        **禁止**用于回测、历史时点解读或滚动统计（违反 ``quant-metric-standards``
        reference 04「剔除前瞻偏差」）。规范要求的滚动窗口口径见
        :func:`stock_analytics.marts.shared.rolling_percentile.add_rolling_percentiles`。

    公式遵循 ``quant-metric-standards`` 的百分位排名标准
    ``(Rank_min - 1) / (N - 1) * 100``：并列值共享**最小**名次（``rank("min")``），
    与同仓 ``marts/shared/rolling_percentile.py``、``pipelines/stock_screen/scoring.py``
    的既有口径保持一致；``N <= 1`` 时按规范返回缺失。
    """
    valid = series.drop_nulls()
    if len(valid) < 2:
        return pl.Series([None] * len(series), dtype=pl.Float64)
    ranked = valid.rank("min")
    pct = (ranked - 1) / (len(valid) - 1) * 100.0
    mapping = dict(zip(valid.to_list(), pct.to_list(), strict=False))
    return pl.Series(
        [mapping.get(v) if v is not None else None for v in series.to_list()], dtype=pl.Float64
    )


def _rolling_leg_active(
    leg_score: pl.Series,
    close: pl.Series,
    *,
    window: int = _LEG_IC_WINDOW,
    fwd_days: int = 60,
    min_samples: int = 40,
) -> pl.Series:
    """结构性腿滚动有效性标记：窗口内 leg_score 与未来 fwd_days 收益的 Spearman IC 符号。

    实证（2026-09）：ai_capex 分年 IC 剧烈翻转（2021 +0.579 → 2025 -0.532 → 2026 -0.868），
    正 IC = 腿仍与未来收益同向（active）；负 IC 或样本不足 = 失效（False）。
    用滚动窗口而非分年，便于日频面板消费。
    """
    n = len(leg_score)
    out: list[bool] = [False] * n
    if n < min_samples + fwd_days:
        return pl.Series(out, dtype=pl.Boolean)

    fwd_ret = [None] * n
    for i in range(n):
        j = i + fwd_days
        if j < n and close[i] is not None and close[j] is not None and close[i] > 0:
            fwd_ret[i] = close[j] / close[i] - 1.0

    from scipy import stats as _stats

    for i in range(window, n):
        leg_win = leg_score[i - window : i].to_list()
        ret_win = fwd_ret[i - window : i]
        pairs = [
            (a, b)
            for a, b in zip(leg_win, ret_win, strict=False)
            if a is not None and b is not None
        ]
        if len(pairs) < min_samples:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        if len(set(xs)) < 2 or len(set(ys)) < 2:
            continue  # 常量输入（如贴顶常值），相关无定义，视为不活跃
        try:
            rho, _ = _stats.spearmanr(xs, ys)
        except Exception:
            continue
        if not math.isnan(rho):
            out[i] = bool(rho > 0)
    return pl.Series(out, dtype=pl.Boolean)


def _regime_by_thresholds(value: float | None, thresholds: tuple[float, ...]) -> str | None:
    if value is None:
        return None
    if value >= thresholds[0]:
        return "high_overstocked"
    if value >= thresholds[1]:
        return "elevated_destocking"
    if value >= thresholds[2]:
        return "normal_balanced"
    return "tight_restocking"


def _make_doi_regime_calculator(col_name: str, thresholds: tuple[float, ...]) -> Any:
    def _calc_regime(row: dict[str, Any]) -> str | None:
        return _regime_by_thresholds(row[col_name], thresholds)

    return _calc_regime


def _memory_lead_regime(nanya_yoy: float | None, adata_yoy: float | None) -> str:
    """判定存储先导动能相态。

    - bull_divergence: 原厂仍强 (南亚科 >= 20.0%) 但模组骤冷 (威刚 < 0.0%)，预警渠道滞销见顶
    - strong_expansion: 南亚科 >= 20.0% 且 威刚 >= 15.0%，原厂与模组供需两旺
    - channel_frontrun: 威刚 >= 15.0% 但 南亚科 < 20.0%，模组厂率先抢跑补库
    - contraction: 南亚科 < 0.0% 且 威刚 < 0.0%，双弱去库周期
    - neutral: 其余平稳或过渡区间
    - unknown: 数据均缺失
    """
    if nanya_yoy is None and adata_yoy is None:
        return "unknown"
    if nanya_yoy is not None and adata_yoy is not None:
        if nanya_yoy >= 20.0 and adata_yoy < 0.0:
            return "bull_divergence"
        if nanya_yoy >= 20.0 and adata_yoy >= 15.0:
            return "strong_expansion"
        if adata_yoy >= 15.0 and nanya_yoy < 20.0:
            return "channel_frontrun"
        if nanya_yoy < 0.0 and adata_yoy < 0.0:
            return "contraction"
        return "neutral"
    if nanya_yoy is not None:
        return (
            "strong_expansion"
            if nanya_yoy >= 20.0
            else "contraction"
            if nanya_yoy < 0.0
            else "neutral"
        )
    if adata_yoy is not None:
        return (
            "channel_frontrun"
            if adata_yoy >= 15.0
            else "contraction"
            if adata_yoy < 0.0
            else "neutral"
        )
    return "unknown"


def _taiwan_lead_effective_date(report_month: str, release_date: date | None) -> date | None:
    """计算台湾月度营运营收生效日期，严格防前视偏差。若无精准 release_date 则按次月 10 日生效。"""
    if release_date is not None:
        return release_date
    try:
        parts = report_month.split("-")
        year, month = int(parts[0]), int(parts[1])
        if month == 12:
            return date(year + 1, 1, 10)
        return date(year, month + 1, 10)
    except Exception:
        return None


def _load_taiwan_memory_lead(calendar: pl.DataFrame) -> pl.DataFrame:
    """加载台湾存储龙头（南亚科 2408 + 威刚 3260）月度营运先导指标并前向填充至日频。"""
    lead_path = _resolve_curated_industry_path(
        _DATA_ROOT,
        "semiconductor/price/semiconductor_memory_taiwan_lead.parquet",
        "semiconductor_memory_taiwan_lead.parquet",
    )
    if not lead_path.exists():
        return pl.DataFrame()
    try:
        df = pl.read_parquet(lead_path)
    except Exception:
        return pl.DataFrame()
    if df.is_empty() or "symbol" not in df.columns:
        return pl.DataFrame()

    eff_dates = [
        _taiwan_lead_effective_date(rm, rd)
        for rm, rd in zip(
            df["report_month"].to_list(),
            df["release_date"].to_list(),
            strict=False,
        )
    ]
    df_eff = df.with_columns(pl.Series("effective_date", eff_dates, dtype=pl.Date)).drop_nulls(
        subset=["effective_date"]
    )

    nanya = (
        df_eff.filter(pl.col("symbol") == "2408")
        .select(["effective_date", pl.col("revenue_yoy").alias("nanya_revenue_yoy")])
        .unique(subset=["effective_date"], keep="last")
        .sort("effective_date")
    )
    adata = (
        df_eff.filter(pl.col("symbol") == "3260")
        .select(["effective_date", pl.col("revenue_yoy").alias("adata_revenue_yoy")])
        .unique(subset=["effective_date"], keep="last")
        .sort("effective_date")
    )

    combined = nanya.join(adata, on="effective_date", how="full", coalesce=True).sort(
        "effective_date"
    )
    if combined.is_empty():
        return pl.DataFrame()

    combined = combined.with_columns(
        (
            pl.when(
                pl.col("nanya_revenue_yoy").is_not_null()
                & pl.col("adata_revenue_yoy").is_not_null()
            )
            .then((pl.col("nanya_revenue_yoy") + pl.col("adata_revenue_yoy")) / 2.0)
            .otherwise(pl.coalesce(["nanya_revenue_yoy", "adata_revenue_yoy"]))
            .round(2)
        ).alias("memory_lead_yoy"),
        (
            pl.when(
                pl.col("nanya_revenue_yoy").is_not_null()
                & pl.col("adata_revenue_yoy").is_not_null()
            )
            .then((pl.col("adata_revenue_yoy") - pl.col("nanya_revenue_yoy")).round(2))
            .otherwise(None)
        ).alias("memory_module_idm_spread"),
    ).with_columns(
        pl.struct(["nanya_revenue_yoy", "adata_revenue_yoy"])
        .map_elements(
            lambda row: _memory_lead_regime(row["nanya_revenue_yoy"], row["adata_revenue_yoy"]),
            return_dtype=pl.Utf8,
        )
        .alias("memory_lead_regime")
    )

    return (
        calendar.select("trade_date")
        .join_asof(
            combined.rename({"effective_date": "trade_date"}).sort("trade_date"),
            on="trade_date",
            strategy="backward",
        )
        .sort("trade_date")
        .with_columns(
            [
                pl.col("nanya_revenue_yoy").fill_null(strategy="forward"),
                pl.col("adata_revenue_yoy").fill_null(strategy="forward"),
                pl.col("memory_lead_yoy").fill_null(strategy="forward"),
                pl.col("memory_module_idm_spread").fill_null(strategy="forward"),
                pl.col("memory_lead_regime").fill_null(strategy="forward"),
            ]
        )
    )


def _driver_regime(global_yoy: float | None, spread: float | None) -> str:
    """驱动源识别：下行 > AI > 宽基共振（memory_driven 因本地无存储价格历史暂不识别）。

    校准（2026-09 四轮实证）：
    - 下行：全球 YoY < 0（2022-2023 实测 -3.8% 中位）；
    - AI 驱动：全球正 + 美洲-中国区分化 ≥25pp（2024-2026 实测 +40.2pp）；
    - 宽基共振：其余正增长（2019-2021 缺芯轮分化 ≈0、2017-2018 存储轮 +15.7pp
      落入本档——存储轮与宽基轮在地区分化上不可分，诚实标注不作细分）。
    """
    if global_yoy is None:
        return "unknown"
    if global_yoy < 0:
        return "downturn"
    if spread is not None and spread >= _AI_SPREAD_GE:
        return "ai_driven"
    return "broad_cycle"


def _load_driver_identification() -> pl.DataFrame:
    """SIA 分地区 YoY → 月频 (ym, global_yoy, americas_china_spread)。"""
    try:
        sales_path = _resolve_curated_industry_path(
            _DATA_ROOT,
            "semiconductor/sales/semiconductor_sales.parquet",
            "semiconductor_sales.parquet",
        )
        sales = pl.read_parquet(sales_path)
    except Exception:
        return pl.DataFrame()
    reg = (
        sales.select(
            [
                pl.col("report_month").alias("ym"),
                pl.col("yoy_growth").alias("global_yoy"),
                pl.col("americas_sales_usd").pct_change(12).alias("americas_yoy"),
                pl.col("china_yoy_growth").alias("china_yoy"),
            ]
        )
        .drop_nulls()
        .with_columns((pl.col("americas_yoy") - pl.col("china_yoy")).alias("americas_china_spread"))
        # SIA yoy 为小数制（0.94 = 94%）；统一为 pp 口径（0.94 → 94.0）
        .with_columns(
            (pl.col("global_yoy") * 100.0).alias("global_yoy"),
            (pl.col("americas_china_spread") * 100.0).alias("americas_china_spread"),
        )
        .select(["ym", "global_yoy", "americas_china_spread"])
        .sort("ym")
    )
    return reg


def _monthly_to_daily_asof(
    monthly: pl.DataFrame,
    calendar: pl.DataFrame,
    *,
    ym_col: str = "ym",
) -> pl.DataFrame:
    """月频 (ym, ...) → 日频 asof（月首生效）。"""
    if monthly.is_empty():
        return pl.DataFrame()
    eff = (
        monthly.with_columns(pl.col(ym_col).str.to_date("%Y-%m", strict=False).alias("trade_date"))
        .select(["trade_date"] + [c for c in monthly.columns if c != ym_col])
        .drop_nulls()
    )
    if eff.is_empty():
        return pl.DataFrame()
    return (
        calendar.select("trade_date")
        .join_asof(eff.sort("trade_date"), on="trade_date", strategy="backward")
        .sort("trade_date")
    )


def _load_ffr_background(calendar: pl.DataFrame) -> pl.DataFrame:
    """FRED DFF 六个月变化 + macro_risk 分位（提示层，asof 无前视）。"""
    out = calendar.select("trade_date")
    try:
        mi = pl.read_parquet(
            _DATA_ROOT / "curated" / "fred" / "market=US" / "macro_indicators" / "data.parquet"
        )
        ffr = calculate_dff_change_6m(
            mi.filter(pl.col("symbol") == "DFF").select(["trade_date", "value"])
        ).select(["trade_date", "ffr_chg_6m"])
        out = out.join_asof(
            ffr.sort("trade_date"), on="trade_date", strategy="backward"
        ).with_columns(pl.col("ffr_chg_6m").fill_null(0.0))
    except Exception:
        out = out.with_columns(pl.lit(0.0, dtype=pl.Float64).alias("ffr_chg_6m"))
    try:
        rf = pl.read_parquet(
            _DATA_ROOT / "analytics" / "macro_risk" / "latest" / "risk_factors.parquet"
        ).select(["trade_date", "ffr_chg_6m_score"])
        out = out.join(rf, on="trade_date", how="left")
    except Exception:
        out = out.with_columns(pl.lit(None, dtype=pl.Float64).alias("ffr_chg_6m_score"))
    return out


def _load_signal_triggers(
    calendar: pl.DataFrame, legs_demand: pl.DataFrame | None = None
) -> pl.DataFrame:
    """信号状态机触发位（defense/offense/crowd），供面板消费。

    ``legs_demand``：270100 的 (trade_date, demand_score, scissors_score) 子集，
    缺省时从 legs 产物读取（与主腿同源，保证剪刀差触发位一致）。
    """
    try:
        if legs_demand is None:
            legs = pl.read_parquet(
                _DATA_ROOT / "analytics" / "semiconductor" / "latest" / "semiconductor_legs.parquet"
            ).filter(pl.col("industry_code") == "270100")
            legs_demand = legs.select(["trade_date", "demand_score", "scissors_score"]).sort(
                "trade_date"
            )
        panel = pl.read_parquet(_DATA_ROOT / "curated" / "mart" / "industry_l2_panel_daily.parquet")
        md = pl.read_parquet(_DATA_ROOT / "curated" / "mart" / "market_daily.parquet").select(
            ["trade_date", pl.col("total_turnover").alias("mkt_turnover")]
        )
        semi = panel.filter(pl.col("industry_code") == "270100").select(
            ["trade_date", "amount_yi", "pe_ttm_ew_percentile_5y"]
        )
        # 成交额占比时序分位（270100 成交额 / 全市场成交额）
        share = (
            semi.select(["trade_date", "amount_yi"])
            .join(md, on="trade_date", how="left")
            .sort("trade_date")
            .with_columns((pl.col("amount_yi") / pl.col("mkt_turnover")).alias("share"))
        )
        s = share["share"].fill_null(0.0)
        share_pct = (
            s.to_frame("v")
            .select(
                pl.col("v").rolling_map(
                    lambda x: float((x <= x[-1]).mean()) * 100.0 if len(x) > 0 else 50.0,
                    window_size=_CROWD_WINDOW,
                    min_samples=1,
                )
            )["v"]
            .fill_nan(50.0)
            .fill_null(50.0)
        )
        share = share.with_columns(pl.Series("share_pct_250", share_pct)).select(
            ["trade_date", "share_pct_250"]
        )
        # 供给腿 DOI（防守门用）
        try:
            supply = (
                pl.read_parquet(
                    _DATA_ROOT / "curated" / "mart" / "semiconductor_supply_legs.parquet"
                )
                .filter(pl.col("industry_code") == "270100")
                .select(["trade_date", "inventory_score"])
            )
            semi = semi.join(supply, on="trade_date", how="left")
        except Exception:
            semi = semi.with_columns(pl.lit(50.0, dtype=pl.Float64).alias("inventory_score"))
        merged = (
            semi.join(share, on="trade_date", how="left")
            .join(legs_demand, on="trade_date", how="left")
            .sort("trade_date")
            .with_columns(
                pl.col("demand_score").fill_null(strategy="forward").alias("demand_score"),
                pl.col("scissors_score").fill_null(strategy="forward").alias("scissors_score"),
                pl.col("inventory_score").fill_null(50.0).alias("inventory_score"),
                pl.col("share_pct_250").fill_null(50.0).alias("share_pct_250"),
                pl.col("pe_ttm_ew_percentile_5y").fill_null(50.0).alias("pe5y"),
            )
            .with_columns(
                (
                    (pl.col("scissors_score") < _DEFENSE_SCISSORS_LT)
                    | (pl.col("inventory_score") >= _DEFENSE_DOI_GE)
                ).alias("defense_trigger"),
                (
                    (pl.col("demand_score") >= _OFFENSE_DEMAND_GE)
                    & (pl.col("scissors_score") >= 0.0)
                ).alias("offense_trigger"),
                (
                    (pl.col("share_pct_250") >= _CROWD_SHARE_GE)
                    & (pl.col("pe5y") >= _CROWD_PE5Y_GE)
                ).alias("crowd_trigger"),
            )
        )
        return merged.select(["trade_date", "defense_trigger", "offense_trigger", "crowd_trigger"])
    except Exception as exc:
        logger.warning("信号状态机构建失败，触发位为空: %s", exc)
        return calendar.select("trade_date").with_columns(
            [
                pl.lit(False).alias("defense_trigger"),
                pl.lit(False).alias("offense_trigger"),
                pl.lit(False).alias("crowd_trigger"),
            ]
        )


def build_semiconductor_research_panel(
    store: FeatureStore,
    *,
    runtime: DataRuntimeContext | None = None,
    overwrite: bool = False,
) -> pl.DataFrame:
    """构建并保存半导体产业深研统一面板 Mart。

    产物：``data/curated/mart/semiconductor_research_panel.parquet``
    （主键 trade_date + industry_code；日频，270100）。
    """
    runtime = runtime or DataRuntimeContext.from_root("data")
    calendar = (
        pl.read_parquet(runtime.data_root / "curated" / "mart" / "global_macro_daily.parquet")
        .select("trade_date")
        .sort("trade_date")
    )

    # 1) 剪刀差主腿 + 结构性腿（legs 管线产物）
    legs_path = (
        runtime.data_root / "analytics" / "semiconductor" / "latest" / "semiconductor_legs.parquet"
    )
    if not legs_path.exists():
        raise FileNotFoundError(f"缺少半导体 legs 产物: {legs_path}（先运行半导体建腿管线）")
    legs = pl.read_parquet(legs_path)
    legs = legs.filter(pl.col("industry_code") == "270100").sort(["trade_date", "industry_code"])

    # 2) 确认腿
    def _read_mart(name: str, industry: str = "270100") -> pl.DataFrame:
        try:
            df = pl.read_parquet(runtime.data_root / "curated" / "mart" / name)
            return df.filter(pl.col("industry_code") == industry).sort("trade_date")
        except Exception:
            return pl.DataFrame()

    gm = _read_mart("semiconductor_gm_confirm_legs.parquet").select(["trade_date", "gm_cross"])
    util = _read_mart("semiconductor_supply_legs.parquet").select(
        ["trade_date", "utilization_score"]
    )

    # 3) 成熟制程库存腿（IDM + 渠道，季度 → 日频）
    #    分位在季度层用全历史序列计算（黄金表 2009/2016 起，不受面板日历 2014 起限制），
    #    与原始值一并按 release_date 前向填充。
    inv_parts: dict[str, pl.DataFrame] = {}
    try:
        inv_path = _resolve_curated_industry_path(
            runtime.data_root,
            "semiconductor/inventory/semiconductor_inventory_days.parquet",
            "semiconductor_inventory_days.parquet",
        )
        inv = pl.read_parquet(inv_path)
        idm_w = (
            inv.group_by("report_quarter")
            .agg(
                pl.col("idm_weighted_doi_days").first(),
                pl.col("release_date").max(),  # 数据完整日（全部公司披露后）
            )
            .sort("report_quarter")
        )
        idm_w = idm_w.with_columns(
            pl.Series(
                "idm_weighted_doi_pct",
                _full_sample_percentile(idm_w["idm_weighted_doi_days"]),
            )
        )
        inv_parts["idm"] = _quarterly_to_daily_forward(
            idm_w.rename({"idm_weighted_doi_days": "quarter_value"}),
            calendar,
        ).rename({"quarter_value": "idm_weighted_doi_days"})
    except Exception:
        pass
    try:
        ch_path = _resolve_curated_industry_path(
            runtime.data_root,
            "semiconductor/inventory/semiconductor_channel_inventory.parquet",
            "semiconductor_channel_inventory.parquet",
        )
        ch = pl.read_parquet(ch_path)
        ch_w = (
            ch.group_by("report_quarter")
            .agg(
                pl.col("channel_weighted_doi_days").first(),
                pl.col("release_date").max(),  # 渠道两家全部披露后的数据完整日
            )
            .sort("report_quarter")
        )
        ch_w = ch_w.with_columns(
            pl.Series(
                "channel_weighted_doi_pct",
                _full_sample_percentile(ch_w["channel_weighted_doi_days"]),
            )
        )
        inv_parts["channel"] = _quarterly_to_daily_forward(
            ch_w.rename({"channel_weighted_doi_days": "quarter_value"}),
            calendar,
        ).rename({"quarter_value": "channel_weighted_doi_days"})
    except Exception:
        pass

    # 4) 驱动源识别（SIA 分地区）
    driver = _monthly_to_daily_asof(_load_driver_identification(), calendar)
    if not driver.is_empty():
        driver = driver.with_columns(
            pl.struct(["global_yoy", "americas_china_spread"])
            .map_elements(
                lambda row: _driver_regime(row["global_yoy"], row["americas_china_spread"]),
                return_dtype=pl.Utf8,
            )
            .alias("driver_regime")
        )

    # 5) 宏观背景（ffr）
    ffr_bg = _load_ffr_background(calendar)

    # 6) 信号状态机（demand/scissors 与 legs 同源）
    legs_demand = (
        legs.filter(pl.col("industry_code") == "270100")
        .select(["trade_date", "demand_score", "scissors_score"])
        .sort("trade_date")
    )
    triggers = _load_signal_triggers(calendar, legs_demand=legs_demand)

    # 7) 存储先导动能腿（P2: 台湾存储龙头）
    taiwan_lead = _load_taiwan_memory_lead(calendar)

    # 组装（按行业扩展）
    try:
        close_panel = pl.read_parquet(
            _DATA_ROOT / "curated" / "mart" / "industry_l2_panel_daily.parquet"
        ).select(["trade_date", "industry_code", "close"])
    except Exception:
        close_panel = pl.DataFrame()
    rows: list[pl.DataFrame] = []
    for code in ["270100"]:
        base = (
            calendar.select("trade_date")
            .join(
                legs.filter(pl.col("industry_code") == code).select(
                    [
                        "trade_date",
                        "demand_score",
                        "supply_score",
                        "scissors_score",
                        "ai_capex_score",
                    ]
                ),
                on="trade_date",
                how="left",
            )
            .join(gm, on="trade_date", how="left")
            .join(util, on="trade_date", how="left")
            .sort("trade_date")
        )
        if not close_panel.is_empty():
            base = base.join(
                close_panel.filter(pl.col("industry_code") == code).select(["trade_date", "close"]),
                on="trade_date",
                how="left",
            ).with_columns(pl.col("close").fill_null(strategy="forward"))
        else:
            base = base.with_columns(pl.lit(None, dtype=pl.Float64).alias("close"))
        # 月频/季频腿生效日后前向填充（legs 产物止于其数据水位，日历余日继承最近值）
        for col in (
            "demand_score",
            "supply_score",
            "scissors_score",
            "ai_capex_score",
            "gm_cross",
            "utilization_score",
        ):
            if col in base.columns:
                base = base.with_columns(pl.col(col).fill_null(strategy="forward").alias(col))
        for key in ("idm", "channel"):
            if key in inv_parts:
                base = base.join(inv_parts[key], on="trade_date", how="left")
        # 存储先导动能腿 (P2)
        if not taiwan_lead.is_empty():
            base = base.join(taiwan_lead, on="trade_date", how="left")
        else:
            base = base.with_columns(
                pl.lit(None, dtype=pl.Float64).alias("nanya_revenue_yoy"),
                pl.lit(None, dtype=pl.Float64).alias("adata_revenue_yoy"),
                pl.lit(None, dtype=pl.Float64).alias("memory_lead_yoy"),
                pl.lit(None, dtype=pl.Float64).alias("memory_module_idm_spread"),
                pl.lit(None, dtype=pl.Utf8).alias("memory_lead_regime"),
            )
        if not driver.is_empty():
            base = base.join(
                driver.select(["trade_date", "americas_china_spread", "driver_regime"]),
                on="trade_date",
                how="left",
            )
        base = base.join(ffr_bg, on="trade_date", how="left")
        base = base.join(triggers, on="trade_date", how="left")
        base = base.with_columns(pl.lit(code).alias("industry_code"))

        # 库存相态（分位由季度层全历史计算带入：黄金表 2009/2016 起，不受面板日历 2014 起限制）
        for key, name in (
            ("idm", "idm_weighted_doi_days"),
            ("channel", "channel_weighted_doi_days"),
        ):
            if name in base.columns:
                target_th = _IDM_REGIME_TH if key == "idm" else _CHANNEL_REGIME_TH
                calc_fn = _make_doi_regime_calculator(name, target_th)
                regime_expr = pl.struct([name]).map_elements(
                    calc_fn,
                    return_dtype=pl.Utf8,
                )
                base = base.with_columns(regime_expr.alias(f"{key}_regime"))
                pct_col = f"{key}_weighted_doi_pct"
                if pct_col not in base.columns:
                    base = base.with_columns(pl.lit(None, dtype=pl.Float64).alias(pct_col))
            else:
                base = base.with_columns(
                    pl.lit(None, dtype=pl.Float64).alias(f"{key}_weighted_doi_days"),
                    pl.lit(None, dtype=pl.Float64).alias(f"{key}_weighted_doi_pct"),
                    pl.lit(None, dtype=pl.Utf8).alias(f"{key}_regime"),
                )

        # 结构性腿有效性标记（滚动 _LEG_IC_WINDOW 日 ai_capex vs 未来 60 日收益 IC 符号）
        # 实证：ai_capex 分年 IC 剧烈翻转（2021 +0.579 → 2025 -0.532 → 2026 -0.868），
        # 换轮必须换腿——此列标记当前腿是否仍有效（正 IC = active）。
        base = base.with_columns(
            _rolling_leg_active(base["ai_capex_score"], base["close"]).alias("ai_capex_leg_active")
        )

        rows.append(base)

    panel = (
        pl.concat(rows)
        .select(list(SEMICONDUCTOR_RESEARCH_SCHEMA))
        .sort(["trade_date", "industry_code"])
    )
    if not panel.is_empty():
        store.save_domain_mart(
            SEMICONDUCTOR_RESEARCH_MART_NAME,
            panel,
            keys=["trade_date", "industry_code"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return panel


__all__ = [
    "SEMICONDUCTOR_RESEARCH_MART_NAME",
    "SEMICONDUCTOR_RESEARCH_SCHEMA",
    "_load_taiwan_memory_lead",
    "_memory_lead_regime",
    "_taiwan_lead_effective_date",
    "build_semiconductor_research_panel",
    "empty_semiconductor_research_panel",
]
