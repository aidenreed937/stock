"""中观行业因子单因子有效性检验（RankIC / ICIR / 胜率）。

升级路线 P0 第 1 项前置研究：检验 `industry_panel_daily` 里被 `factor_panel.py`
浪费的景气/超预期/资金流/估值字段，对比现有量价因子，看哪些对下期行业收益有
横截面预测力。标准做法：每个交易日计算因子值与下期收益的横截面秩相关（RankIC），
汇总 IC 均值、ICIR（均值/标准差）与 IC 胜率。

无前视：因子值均来自 `industry_panel_daily`（已按公告日 ann_date 点内对齐），
下期收益用 `industry_daily` 的 close 前推 5/20 日。
"""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl
from scipy.stats import spearmanr

_FACTORS = {
    "量价-return_20d": "return_20d",
    "量价-return_60d": "return_60d",
    "量价-ma_bias_20d": "ma_bias_20d",
    "量价-tcr_percentile": "tcr_percentile",
    "估值-pe_percentile_5y": "pe_percentile_5y",
    "估值-pb_percentile_5y": "pb_percentile_5y",
    "景气-forecast_positive": "forecast_positive_share",
    "景气-forecast_p_chg": "forecast_p_change_mid_median",
    "景气-express_profit": "express_profit_growth_median",
    "景气-express_roe": "express_roe_median",
    "超预期-report_rc_revision": "report_rc_revision_ratio",
    "资金流-large_money_20d": "large_money_net_inflow_share_20d",
    "资金流-money_share_20d": "money_net_inflow_share_20d",
    "资金流-money_share_5d": "money_net_inflow_share_5d",
    "估值-pbroe_residual": "pbroe_residual",
}
_FWD_WINDOWS = (5, 20)


def _forward_return(daily: pl.DataFrame, window: int) -> pl.DataFrame:
    """行业未来 N 日收益。"""
    return (
        daily.sort(["industry_code", "trade_date"])
        .with_columns(
            (pl.col("close").shift(-window).over("industry_code") / pl.col("close") - 1.0).alias(
                f"fwd_ret_{window}d"
            )
        )
        .select(["trade_date", "industry_code", f"fwd_ret_{window}d"])
    )


def _rank_ic(df: pl.DataFrame, factor_col: str, fwd_col: str) -> tuple[float, float, float]:
    """逐日横截面 RankIC 的均值、ICIR、胜率。"""
    ics: list[float] = []
    for _, group in df.group_by("as_of_date", maintain_order=True):
        sub = group.filter(pl.col(factor_col).is_not_null() & pl.col(fwd_col).is_not_null())
        if sub.height < 10:
            continue
        ic, _ = spearmanr(sub[factor_col].to_list(), sub[fwd_col].to_list())
        if not math.isnan(ic):
            ics.append(ic)
    if not ics:
        return 0.0, 0.0, 0.0
    mean_ic = sum(ics) / len(ics)
    var_ic = sum((x - mean_ic) ** 2 for x in ics) / (len(ics) - 1) if len(ics) > 1 else 0.0
    std_ic = var_ic**0.5
    icir = mean_ic / std_ic if std_ic > 0 else 0.0
    win_rate = sum(1 for x in ics if x > 0) / len(ics) * 100.0
    return mean_ic, icir, win_rate


def main() -> None:
    panel = pl.read_parquet("data/curated/mart/industry_panel_daily.parquet")
    daily = pl.read_parquet("data/curated/mart/industry_daily.parquet")

    rows: list[dict] = []
    for window in _FWD_WINDOWS:
        fwd = _forward_return(daily, window)
        df = panel.select(["as_of_date", "industry_code", *list(_FACTORS.values())]).join(
            fwd,
            left_on=["as_of_date", "industry_code"],
            right_on=["trade_date", "industry_code"],
            how="left",
        )
        fwd_col = f"fwd_ret_{window}d"
        for label, col in _FACTORS.items():
            mean_ic, icir, win_rate = _rank_ic(df, col, fwd_col)
            rows.append(
                {
                    "fwd_window": window,
                    "factor": label,
                    "ic_mean": round(mean_ic * 100, 2),
                    "icir": round(icir, 2),
                    "ic_win_rate": round(win_rate, 1),
                }
            )

    result = pl.DataFrame(rows)
    out = Path("data/analytics/industry_strategy")
    out.mkdir(parents=True, exist_ok=True)
    result.write_csv(out / "industry_factor_ic.csv")

    print("=== 单因子 RankIC (下期5日 / 20日) ===")
    for window in _FWD_WINDOWS:
        sub = result.filter(pl.col("fwd_window") == window).sort("ic_mean", descending=True)
        print(f"\n--- 下期 {window} 日 ---")
        print(sub)


if __name__ == "__main__":
    main()
