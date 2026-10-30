"""半导体深研策略全变体统一对比表（合并 5 组研究产物，口径对齐）。

口径说明：
- 主表（demand_offense / crowding_overlay / gm_confirm / offense_defense_crowd）：
  buy_hold 基准完全一致（全周期 19.59% CAGR / 63.73% MaxDD / 0.646 Sharpe，
  样本外 10.55% / 57.28% / 0.451），即 270100、2020-05 起全周期、2022-01 起样本外、
  T+1 出仓、无前视、无摩擦 —— 可直接横向对比。
- 附表（supply_legs_backtest）：2018-01 起窗口（基准 19.42%），单独标注，不混入主表。
- sox_backtest：SOX 对照（信号在美股无效），不占 A 股口径。

输出：data/analytics/industry_strategy/semi_all_variants_comparison.{csv,md}
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

OUT_DIR = Path("data/analytics/industry_strategy")
FILES = {
    "demand_offense": OUT_DIR / "industry_semi_demand_offense.csv",
    "crowding_overlay": OUT_DIR / "semi_crowding_defense_overlay.csv",
    "gm_confirm": OUT_DIR / "semi_gm_confirm.csv",
    "offense_defense_crowd": OUT_DIR / "semi_offense_defense_crowd.csv",
}
LABELS = {
    # demand_offense
    "buy_hold": "买入持有（基准）",
    "demand_strong_offense": "需求先行 demand≥70&sc≥0",
    "demand_pos_offense": "需求前置宽松 demand≥60&sc≥0",
    "demand_high_beta": "纯需求扩张 demand≥60",
    "scissors_pos_hold": "剪刀差正向 sc≥0",
    "demand_strong_offense_def": "进攻+防守门",
    # crowding_overlay
    "defense": "防守门（sc<0/DOI≥70 降仓）",
    "crowd_val80": "拥挤估值双高 crowd_val80",
    "defense_crowd": "防守门×crowd_val80",
    # gm_confirm
    "scissors_long": "剪刀差 LONG 基线",
    "scissors_confirm": "GM 单公司确认",
    "scissors_confirm_cross": "GM 跨公司确认",
    "gm_only": "GM 单公司独立",
    "gm_only_cross": "GM 跨公司独立",
    # offense_defense_crowd
    "offense": "进攻脚",
    "offense_def": "进攻脚×防守门",
    "offense_defcrowd": "进攻×防守×crowd 三层",
}

DEEMED_BY = {
    "demand_strong_offense": "demand_offense",
    "demand_strong_offense_def": "demand_offense",
    "scissors_pos_hold": "demand_offense",
    "defense": "crowding_overlay",
    "crowd_val80": "crowding_overlay",
    "defense_crowd": "crowding_overlay",
    "scissors_long": "gm_confirm",
    "scissors_confirm_cross": "gm_confirm",
    "offense_defcrowd": "offense_defense_crowd",
}


def main() -> None:
    frames: list[pl.DataFrame] = []
    col_aliases = {
        "全CAGR%": "全CAGR%",
        "全周期CAGR%": "全CAGR%",
        "全MaxDD%": "全MaxDD%",
        "全周期MaxDD%": "全MaxDD%",
        "全Sharpe": "全Sharpe",
        "全周期Sharpe": "全Sharpe",
        "外CAGR%": "外CAGR%",
        "样本外CAGR%": "外CAGR%",
        "外MaxDD%": "外MaxDD%",
        "样本外MaxDD%": "外MaxDD%",
        "外Sharpe": "外Sharpe",
        "样本外Sharpe": "外Sharpe",
    }
    for src, path in FILES.items():
        df = pl.read_csv(path)
        cols = {c: (col_aliases.get(c) or c) for c in df.columns}
        df = df.rename(cols)
        df = df.select(
            [
                pl.col("variant").alias("variant"),
                "全CAGR%",
                "全MaxDD%",
                "全Sharpe",
                "外CAGR%",
                "外MaxDD%",
                "外Sharpe",
            ]
        )
        frames.append(df)
    merged = pl.concat(frames).unique(subset=["variant"], keep="first").sort("variant")

    # 统一列名与顺序
    out = merged.select(
        [
            pl.col("variant").alias("变体"),
            pl.col("全CAGR%"),
            pl.col("全MaxDD%"),
            pl.col("全Sharpe"),
            pl.col("外CAGR%"),
            pl.col("外MaxDD%"),
            pl.col("外Sharpe"),
        ]
    )
    # 标签列（别名/口径来源）
    named = (
        out.with_columns(
            pl.col("变体").replace_strict(LABELS, default=pl.col("变体")).alias("说明"),
            pl.col("变体").replace_strict(DEEMED_BY, default=pl.lit("—")).alias("口径组"),
        )
        .select(
            [
                "变体",
                "说明",
                "外Sharpe",
                "全Sharpe",
                "外CAGR%",
                "全CAGR%",
                "外MaxDD%",
                "全MaxDD%",
                "口径组",
            ]
        )
        .sort("外Sharpe", descending=True)
    )

    out_csv = OUT_DIR / "semi_all_variants_comparison.csv"
    named.write_csv(out_csv)

    lines = [
        "# 半导体深研策略全变体统一对比（270100，2020-05 起 / 样本外 2022-01 起，T+1 无摩擦）",
        "",
        "> 口径：4 组产物 buy_hold 基准逐位一致（19.59 / 63.73 / 0.646；外 10.55 / 57.28 / 0.451），",
        "> 可横向对比。按样本外 Sharpe 降序。口径组 = 变体最完整实证来源。",
        "",
        "| 变体 | 说明 | 外Sharpe | 全Sharpe | 外CAGR% | 全CAGR% | 外MaxDD% | 全MaxDD% | 口径组 |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    for r in named.iter_rows(named=True):
        lines.append(
            f"| {r['变体']} | {r['说明']} | {r['外Sharpe']} | {r['全Sharpe']} | "
            f"{r['外CAGR%']} | {r['全CAGR%']} | {r['外MaxDD%']} | {r['全MaxDD%']} | {r['口径组']} |"
        )
    lines += [
        "",
        "## 2018-01 起窗口单独对照（supply_legs_backtest，基准 19.42%）",
        "",
        "| 变体 | 说明 | 外Sharpe | 全Sharpe | 外CAGR% | 全CAGR% | 外MaxDD% | 全MaxDD% |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        "| buy_hold | 买入持有（基准） | 0.445 | 0.642 | 10.29 | 19.42 | 57.28 | 63.73 |",
        "| scissors_neg | 剪刀差<0 空仓 | 0.638 | 0.722 | 16.80 | 20.71 | 39.15 | 41.90 |",
        "| inv_high | DOI≥70 降仓30% | 0.567 | 0.650 | 14.41 | 17.07 | 46.17 | 54.30 |",
        "| scissors_inv | 剪刀差+DOI 组合防守 | 0.698 | 0.704 | 17.44 | 16.42 | 39.15 | 39.15 |",
        "",
        "> SOX 对照（semi_sox_backtest）：同信号在美股 SOX 上样本外全部跑输买入持有 — ",
        "> 信号有效性依赖 A 股对全球产业数据的滞后反应，仅 A 股口径成立。",
    ]
    out_md = OUT_DIR / "semi_all_variants_comparison.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"写入 {out_csv} / {out_md}")
    print(named)


if __name__ == "__main__":
    main()
