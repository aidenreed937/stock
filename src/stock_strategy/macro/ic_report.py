"""宏观风控因子时序 Rank IC 验证的报告渲染层。

``build_ic_report`` 编排 IC 验证全流程并落盘 CSV / Markdown 报告；
``_render_markdown`` 渲染整体 / 年度 / 当前时窗三口径（含置换检验「运气区间」与
单因子独立章节）。核心计算与配置见 ``ic`` / ``ic_config``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from stock_data.catalog import DataCatalog
from stock_strategy.macro.ic import (
    build_ic_panel,
    overall_ic,
    permutation_ic,
    trailing_ic,
    yearly_ic,
)
from stock_strategy.macro.ic_config import (
    _DEFAULT_CONFIG_PATH,
    _DEFAULT_OUTPUT_DIR,
    _DEFAULT_RISK_ROOT,
    IcConfig,
    load_ic_config,
)


def build_ic_report(
    *,
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
    risk_root: Path | str = _DEFAULT_RISK_ROOT,
    output_dir: Path | str = _DEFAULT_OUTPUT_DIR,
    data_source: str = "tushare",
) -> dict[str, pl.DataFrame]:
    """运行并产出宏观风控因子时序 IC 验证报告到 ``output_dir``。

    默认产出双轨指数 + 维度分（``ic.factors``）的整体/年度/时窗 IC；
    若配置了 ``ic.single_factors``（23 个单因子 score 列），额外产出独立的
    ``ic_single_*.csv`` 与报告，**不混入默认 12 信号报告**。

    Returns:
        ``{overall, yearly, trailing}`` 三张 IC 表（已写 CSV 落盘）；
        若配置了单因子，额外含 ``{single_overall, single_yearly, single_trailing}``。
    """
    config_path = Path(config_path)
    risk_root = Path(risk_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ic_cfg = load_ic_config(config_path)
    catalog = DataCatalog(data_source=data_source)
    panel = build_ic_panel(
        catalog=catalog,
        risk_root=risk_root,
        benchmark_symbol=ic_cfg.benchmark_symbol,
        horizons=ic_cfg.horizons,
    )

    overall = overall_ic(panel, ic_cfg.factors, ic_cfg.horizons, ic_cfg.min_samples)
    yearly = yearly_ic(panel, ic_cfg.factors, ic_cfg.horizons, ic_cfg.min_samples)
    trailing = trailing_ic(
        panel, ic_cfg.factors, ic_cfg.horizons, ic_cfg.min_samples, ic_cfg.trailing_window
    )
    permutation = permutation_ic(
        panel,
        ic_cfg.factors,
        ic_cfg.horizons,
        ic_cfg.min_samples,
        ic_cfg.n_permutations,
        ic_cfg.seed,
        ic_cfg.alpha,
    )

    overall.write_csv(out / "ic_summary.csv")
    yearly.write_csv(out / "ic_yearly.csv")
    trailing.write_csv(out / "ic_trailing.csv")
    permutation.write_csv(out / "ic_permutation.csv")

    result: dict[str, pl.DataFrame] = {
        "overall": overall,
        "yearly": yearly,
        "trailing": trailing,
        "permutation": permutation,
    }

    # 单因子独立验证（23 个 score 列，独立面板与产物，不混入默认报告）
    single = None
    if ic_cfg.single_factors:
        s_panel = build_ic_panel(
            catalog=catalog,
            risk_root=risk_root,
            benchmark_symbol=ic_cfg.benchmark_symbol,
            horizons=ic_cfg.horizons,
            factor_cols=ic_cfg.single_factors,
        )
        single = {
            "overall": overall_ic(
                s_panel, ic_cfg.single_factors, ic_cfg.horizons, ic_cfg.min_samples
            ),
            "yearly": yearly_ic(
                s_panel, ic_cfg.single_factors, ic_cfg.horizons, ic_cfg.min_samples
            ),
            "trailing": trailing_ic(
                s_panel,
                ic_cfg.single_factors,
                ic_cfg.horizons,
                ic_cfg.min_samples,
                ic_cfg.trailing_window,
            ),
            "permutation": permutation_ic(
                s_panel,
                ic_cfg.single_factors,
                ic_cfg.horizons,
                ic_cfg.min_samples,
                ic_cfg.n_permutations,
                ic_cfg.seed,
                ic_cfg.alpha,
            ),
        }
        single["overall"].write_csv(out / "ic_single_summary.csv")
        single["yearly"].write_csv(out / "ic_single_yearly.csv")
        single["trailing"].write_csv(out / "ic_single_trailing.csv")
        single["permutation"].write_csv(out / "ic_single_permutation.csv")
        result.update(
            {
                "single_overall": single["overall"],
                "single_yearly": single["yearly"],
                "single_trailing": single["trailing"],
                "single_permutation": single["permutation"],
            }
        )

    _render_markdown(
        overall,
        yearly,
        trailing,
        ic_cfg,
        out / "ic_report.md",
        panel,
        permutation=permutation,
        single=single,
    )
    return result


def _fmt(v: float | None) -> str:
    return "N/A" if v is None else f"{v:+.3f}"


def _render_markdown(
    overall: pl.DataFrame,
    yearly: pl.DataFrame,
    trailing: pl.DataFrame,
    cfg: IcConfig,
    out_path: Path,
    panel: pl.DataFrame,
    permutation: pl.DataFrame | None = None,
    single: dict[str, pl.DataFrame] | None = None,
) -> None:
    """渲染 IC 验证 Markdown 报告（整体 + 年度 + 当前时窗 + 覆盖区间）。

    ``permutation`` 非空时，整体 IC 表追加「运气区间 / p 值 / 显著」三列
    （置换检验，α=``cfg.alpha``）；``single`` 非空时，额外追加
    「单因子独立 IC」章节（探索性成分层验证）。
    """
    lines = [
        "# 宏观风控因子时序 Rank IC 验证",
        "",
        "SOP S3 IC 验证：整体 + 年度 + 当前时窗三口径（路线 A：单序列时序 Spearman IC）。",
        "",
    ]
    if panel.is_empty() or "trade_date" not in panel.columns:
        lines.append("（无有效面板，未生成 IC）")
    else:
        start = panel["trade_date"].min()
        end = panel["trade_date"].max()
        lines += [
            f"- 覆盖区间：`{start!s}` ~ `{end!s}`",
            f"- 因子数：`{len(cfg.factors)}`；前瞻窗口（交易日/日）：`{tuple(cfg.horizons)}`",
            f"- min_samples（有效样本下限）：`{cfg.min_samples}`；当前时窗：最近 `{cfg.trailing_window}` 交易日",
        ]
        if permutation is not None and not permutation.is_empty():
            lines.append(
                f"- 置换检验（运气区间）：打乱收益 `{cfg.n_permutations}` 次，"
                f"α=`{cfg.alpha}`（双侧），seed=`{cfg.seed}`；"
                "「显著」= 真实 IC 超出 95% 运气区间"
            )
        lines.append("")
    lines.append("## 一、整体 IC（全样本 pooled）")
    lines.append("")
    has_perm = permutation is not None and not permutation.is_empty()
    perm_frame = permutation if has_perm else None
    perm_map: dict[tuple[str, int], dict[str, Any]] = {}
    if perm_frame is not None:
        for r in perm_frame.to_dicts():
            perm_map[(r["factor"], int(r["horizon"]))] = r
    if has_perm:
        lines.append("| 因子 | 前瞻收益 | IC | 样本数 | 运气区间(95%) | p 值 | 显著 |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    else:
        lines.append("| 因子 | 前瞻收益 | IC | 样本数 |")
        lines.append("| :--- | :---: | :---: | :---: |")
    for r in overall.to_dicts():
        if has_perm:
            p = perm_map.get((r["factor"], int(r["horizon"])))
            if p is None or p["p_value"] is None:
                interval, pv, sig = "N/A", "N/A", "N/A"
            else:
                interval = f"[{float(p['ci_lo']):+.3f}, {float(p['ci_hi']):+.3f}]"
                pv = f"{float(p['p_value']):.4f}"
                sig = "显著" if p["significant"] else "未显著"
            lines.append(
                f"| {r['factor']} | `{r['horizon']}D` | {_fmt(r['ic'])} | {r['n']} | {interval} | {pv} | {sig} |"
            )
        else:
            lines.append(f"| {r['factor']} | `{r['horizon']}D` | {_fmt(r['ic'])} | {r['n']} |")
    lines.append("")

    lines.append("## 二、年度 IC（跨周期稳定性）")
    lines.append("")
    lines.append("| 年份 | 因子 | 前瞻收益 | IC | 样本数 |")
    lines.append("|:---:| :--- | :---: | :---: | :---: |")
    for r in yearly.to_dicts():
        lines.append(
            f"| {r['year']} | {r['factor']} | `{r['horizon']}D` | {_fmt(r['ic'])} | {r['n']} |"
        )
    lines.append("")

    lines.append(f"## 三、当前截面/时窗 IC（最近 {cfg.trailing_window} 交易日）")
    lines.append("")
    lines.append("| 因子 | 前瞻收益 | IC | 样本数 |")
    lines.append("| :--- | :---: | :---: | :---: |")
    for r in trailing.to_dicts():
        lines.append(f"| {r['factor']} | `{r['horizon']}D` | {_fmt(r['ic'])} | {r['n']} |")
    lines.append("")

    if single is not None:
        lines.append("## 四、单因子独立 IC（探索性成分层验证，不参与双轨合成）")
        lines.append("")
        lines.append("> 23 个原始因子 score 列的独立观测，用于佐证维度归组与独立因子取舍；")
        lines.append("> 成分层探索性结论，非最终因子确认（多重比较下需谨慎解读）。")
        lines.append("")
        single_perm = single.get("permutation")
        s_has_perm = single_perm is not None and not single_perm.is_empty()
        s_perm_frame = single_perm if s_has_perm else None
        s_perm_map: dict[tuple[str, int], dict[str, Any]] = {}
        if s_perm_frame is not None:
            for r in s_perm_frame.to_dicts():
                s_perm_map[(r["factor"], int(r["horizon"]))] = r
        for section_title, key in (
            ("整体", "overall"),
            ("当前时窗", "trailing"),
        ):
            df = single.get(key)
            if df is None or df.is_empty():
                continue
            lines.append(f"### 单因子 {section_title} IC")
            lines.append("")
            if s_has_perm and key == "overall":
                lines.append("| 因子 | 前瞻收益 | IC | 样本数 | 运气区间(95%) | p 值 | 显著 |")
                lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
            else:
                lines.append("| 因子 | 前瞻收益 | IC | 样本数 |")
                lines.append("| :--- | :---: | :---: | :---: |")
            for r in df.to_dicts():
                if s_has_perm and key == "overall":
                    p = s_perm_map.get((r["factor"], int(r["horizon"])))
                    if p is None or p["p_value"] is None:
                        interval, pv, sig = "N/A", "N/A", "N/A"
                    else:
                        interval = f"[{float(p['ci_lo']):+.3f}, {float(p['ci_hi']):+.3f}]"
                        pv = f"{float(p['p_value']):.4f}"
                        sig = "显著" if p["significant"] else "未显著"
                    lines.append(
                        f"| {r['factor']} | `{r['horizon']}D` | {_fmt(r['ic'])} | {r['n']} | {interval} | {pv} | {sig} |"
                    )
                else:
                    lines.append(
                        f"| {r['factor']} | `{r['horizon']}D` | {_fmt(r['ic'])} | {r['n']} |"
                    )
            lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


__all__ = ["build_ic_report"]
