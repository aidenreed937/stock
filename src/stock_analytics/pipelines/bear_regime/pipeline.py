"""熊市区间识别管线：双引擎识别 + ArtifactStore 落盘 + 可重复运行。

引擎 1 (价格回撤)：基准 250 日滚动新高回撤低于阈值且持续 >= 阈值天数；
引擎 2 (四低共振)：估值分位低 + 成交分位低 + 杠杆资金分位低 + 价格分位低
  四低中至少 N 项共振（价格分位由基准 250 日滚动区间位置计算）。

输入（Ground Truth）：
  - 宏观风控因子: data/analytics/macro_risk/latest/risk_factors.parquet
  - 多策略净值宽表: data/analytics/macro_strategy/multi_strategy_nav.csv

产物（ArtifactStore 事务落盘）：
  - bear_regime.parquet: 识别区间 × 策略 明细 (区间收益/最深回撤/回本所需交易日)
  - bear_regime_report.md: 双引擎区间速览
  - manifest.json: 运行清单 (含输入水位与配置指纹)
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import polars as pl

from stock_analytics.pipelines.artifacts import (
    ArtifactStore,
    ArtifactWriteSession,
    build_manifest_base,
)
from stock_analytics.pipelines.bear_regime.config import (
    BearRegimeConfig,
    load_bear_regime_config,
)

logger = logging.getLogger(__name__)

_BENCH_COL = "中证全指"
_DEFAULT_NAV_CSV = "data/analytics/macro_strategy/multi_strategy_nav.csv"
_DEFAULT_RISK_ROOT = "data/analytics/macro_risk"
_DEFAULT_OUTPUT_DIR = "data/analytics/bear_regime"


def _segments_from_mask(
    mask: pl.Series, frame: pl.DataFrame, min_days: int, gap_buffer: int = 20
) -> list[tuple[date, date, int]]:
    """把布尔 mask 合并为连续区间（允许 ``gap_buffer`` 交易日回升缓冲），返回 [(start, end, days)]。"""
    dates = frame["trade_date"].to_list()
    flags = mask.to_list()
    segs: list[tuple[date, date, int]] = []
    i, n = 0, len(flags)
    while i < n:
        if flags[i]:
            j = i
            gap = 0
            while j < n and (flags[j] or gap <= gap_buffer):
                if flags[j]:
                    gap = 0
                else:
                    gap += 1
                j += 1
            seg_end = j - gap if gap > 0 else j
            if seg_end - i >= min_days:
                segs.append((dates[i], dates[seg_end - 1], seg_end - i))
            i = seg_end
        else:
            i += 1
    return segs


def _identify_price_bears(
    close: pl.DataFrame,
    bench_col: str,
    cfg: BearRegimeConfig,
) -> list[tuple[date, date, int]]:
    """引擎 1: 基准 250 日新高回撤识别熊市区间。"""
    close = close.with_columns(
        pl.col(bench_col).rolling_max(window_size=250, min_samples=60).alias("_peak250")
    ).with_columns(((pl.col(bench_col) / pl.col("_peak250") - 1.0).fill_null(0.0)).alias("_dd250"))
    return _segments_from_mask(
        close["_dd250"] <= cfg.drawdown_threshold,
        close,
        min_days=cfg.price_min_days,
        gap_buffer=cfg.price_gap_buffer,
    )


def _identify_factor_bears(
    close: pl.DataFrame,
    risk_factors: pl.DataFrame,
    bench_col: str,
    cfg: BearRegimeConfig,
) -> list[tuple[date, date, int]]:
    """引擎 2: 四低共振识别熊市底部 (估值/成交/杠杆/价格分位)。"""
    rf = risk_factors.select(["trade_date", "dim_leverage", "dim_crowding", "dim_valuation"]).sort(
        "trade_date"
    )

    # 价格分位: 基准 250 日滚动分位数 (rolling_rank, 与估值/成交/杠杆分位口径统一;
    # 处于历史底部 20% 视为低; min_samples=60 避免窗口未满时 rank 异常偏低)
    close_rank = close.with_columns(
        pl.col(bench_col)
        .rolling_rank(window_size=250, method="min", min_samples=60)
        .alias("_rank_raw")
    ).with_columns((pl.col("_rank_raw") / 250.0).alias("_price_rank"))
    rf = rf.join(close_rank.select(["trade_date", "_price_rank"]), on="trade_date", how="left")
    score = (
        (rf["dim_valuation"] <= cfg.valuation_threshold).cast(pl.Int8)
        + (rf["dim_crowding"] <= cfg.crowding_threshold).cast(pl.Int8)
        + (rf["dim_leverage"] <= cfg.leverage_threshold).cast(pl.Int8)
        + (rf["_price_rank"] <= cfg.price_rank_threshold).cast(pl.Int8)
    )
    rf = rf.with_columns(score.fill_null(0).alias("_low_score"))
    return _segments_from_mask(
        rf["_low_score"] >= cfg.factor_score_min,
        rf,
        min_days=cfg.factor_min_days,
        gap_buffer=cfg.factor_gap_buffer,
    )


def identify_bear_regimes(
    wide_df: pl.DataFrame,
    risk_factors: pl.DataFrame | None,
    cfg: BearRegimeConfig | None = None,
    cols: list[str] | None = None,
) -> pd.DataFrame:
    """双引擎熊市区间识别，输出识别区间 × 策略明细。

    Args:
        wide_df: 含 trade_date 与各策略/基准净值的宽表。
        risk_factors: 宏观因子 (dim_leverage/dim_crowding/dim_valuation)。
        cfg: 阈值配置；缺省用默认值。
        cols: 需要统计的列；缺省取除 trade_date 外全部列。

    Returns:
        DataFrame[识别引擎, 熊市区间, 区间天数, 标的/策略, 区间收益, 最深回撤, 回本所需交易日]
    """
    cfg = cfg or BearRegimeConfig()
    if cols is None:
        cols = [c for c in wide_df.columns if c != "trade_date"]

    bench_col = _BENCH_COL if _BENCH_COL in cols else cols[0]
    close = wide_df.select(["trade_date", bench_col]).sort("trade_date")

    price_bears = _identify_price_bears(close, bench_col, cfg)
    factor_bears = (
        _identify_factor_bears(close, risk_factors, bench_col, cfg)
        if risk_factors is not None and not risk_factors.is_empty()
        else []
    )

    rows: list[dict[str, Any]] = []
    for engine, bears in [
        ("价格回撤 (250日新高回撤)", price_bears),
        ("四低共振 (估值/成交/杠杆/价格)", factor_bears),
    ]:
        for b0, b1, n_days in bears:
            seg = wide_df.filter((pl.col("trade_date") >= b0) & (pl.col("trade_date") <= b1))
            if seg.is_empty():
                continue
            for col in cols:
                navs = seg[col].to_list()
                if not navs:
                    continue
                first_v = float(navs[0])
                final_v = float(navs[-1])
                tot_ret = (final_v / first_v - 1.0) if first_v > 0 else 0.0
                peak = navs[0]
                max_dd = 0.0
                for v in navs:
                    peak = max(peak, v)
                    dd = (v - peak) / peak if peak > 0 else 0.0
                    max_dd = min(max_dd, dd)

                # 回本所需交易日: 从区间最低点之后首次回到区间起点净值
                min_idx = int(np.argmin(navs))
                min_val = float(navs[min_idx])
                recovery_days = 0
                if min_val < first_v:
                    post = wide_df.filter(pl.col("trade_date") > b1).sort("trade_date")
                    post_navs = post[col].to_list()
                    for idx, pv in enumerate(post_navs):
                        if pv >= first_v:
                            recovery_days = idx + 1
                            break
                    else:
                        recovery_days = len(post_navs)

                rows.append(
                    {
                        "识别引擎": engine,
                        "熊市区间": f"{b0} ~ {b1}",
                        "区间天数": n_days,
                        "标的/策略": col,
                        "区间收益": tot_ret,
                        "最深回撤": max_dd,
                        "回本所需交易日": recovery_days,
                    }
                )
    return pd.DataFrame(rows)


def _render_report_markdown(result: pd.DataFrame) -> str:
    """把识别结果渲染为 Markdown 速览。"""
    lines = [
        "# 熊市区间识别报告 (双引擎)",
        "",
        "| 识别引擎 | 熊市区间 | 持续天数 | 标的/策略 | 区间收益 | 最深回撤 | 回本所需交易日 |",
        "| :--- | :--- | :---: | :--- | :---: | :---: | :---: |",
    ]
    for _, row in result.iterrows():
        name = (
            f"**`{row['标的/策略']}`**"
            if "macro" in str(row["标的/策略"])
            else str(row["标的/策略"])
        )
        lines.append(
            f"| {row['识别引擎']} | {row['熊市区间']} | {int(row['区间天数'])} | {name} "
            f"| {float(row['区间收益']) * 100:+.2f}% | {float(row['最深回撤']) * 100:+.2f}% "
            f"| {int(row['回本所需交易日'])} |"
        )
    lines.append("")
    lines.append(
        "> 引擎 1 (价格回撤) 回答「历史最惨能多深、多久收复」；"
        "引擎 2 (四低共振: 估值/成交/杠杆/价格分位) 回答「当前是否处于熊市底部区域」。"
    )
    return "\n".join(lines)


class BearRegimePipeline:
    """熊市识别管线：读取黄金产物 -> 双引擎识别 -> ArtifactStore 事务落盘。"""

    def __init__(
        self,
        config_path: Path | str = "config/analytics/bear_regime.yaml",
    ) -> None:
        self.config = load_bear_regime_config(config_path)

    def run(
        self,
        *,
        as_of: date | None = None,
        nav_csv: Path | str = _DEFAULT_NAV_CSV,
        risk_root: Path | str = _DEFAULT_RISK_ROOT,
        output_dir: Path | str = _DEFAULT_OUTPUT_DIR,
        update_latest: bool = True,
        run_class: Literal["official", "backfill", "experiment"] = "official",
    ) -> pd.DataFrame:
        """执行熊市识别并落盘产物，返回识别结果 DataFrame。"""
        wide = (
            pl.read_csv(nav_csv).with_columns(pl.col("trade_date").str.to_date()).sort("trade_date")
        )
        if wide.is_empty():
            raise ValueError(f"策略净值宽表为空: {nav_csv}")

        try:
            from stock_analytics.pipelines.macro_risk import load_latest_risk_factors

            _, risk_factors, _ = load_latest_risk_factors(Path(risk_root))
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载宏观因子失败，四低共振引擎将跳过: %s", exc)
            risk_factors = None

        as_of_val = as_of or wide["trade_date"].max()
        if as_of_val is None or not isinstance(as_of_val, date):
            raise ValueError("无法确定基准日期")

        result = identify_bear_regimes(wide, risk_factors, cfg=self.config)

        paths = ArtifactStore.build_run_paths(
            as_of_date=as_of_val, artifact_root=output_dir, run_class=run_class
        )
        report_md = _render_report_markdown(result)

        with ArtifactWriteSession(paths, update_latest=update_latest) as session:
            session.write_parquet("bear_regime.parquet", pl.from_pandas(result))
            session.write_text("bear_regime_report.md", report_md)

            manifest = build_manifest_base(
                artifact_type="bear_regime",
                schema_version=1,
                title="双引擎熊市区间识别",
                run_id=paths.run_dir.name,
                as_of_date=as_of_val,
                artifact_root=output_dir,
                config_path="config/analytics/bear_regime.yaml",
                inputs={
                    "nav_csv": str(nav_csv),
                    "risk_root": str(risk_root),
                },
            )
            if not result.empty:
                price_n = int(
                    result[result["识别引擎"].str.startswith("价格回撤")]["熊市区间"].nunique()
                )
                factor_n = int(
                    result[result["识别引擎"].str.startswith("四低共振")]["熊市区间"].nunique()
                )
                manifest["summary"] = {
                    "识别区间数": int(result["熊市区间"].nunique()),
                    "价格回撤区间": price_n,
                    "四低共振区间": factor_n,
                    "策略数": int(result["标的/策略"].nunique()),
                }
            session.write_json("manifest.json", manifest)

        logger.info("熊市识别管线完成: %s", paths.run_dir)
        return result


__all__ = [
    "BearRegimePipeline",
    "identify_bear_regimes",
]
