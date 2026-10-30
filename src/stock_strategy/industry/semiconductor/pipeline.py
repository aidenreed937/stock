"""半导体深研线回测/IC 验证编排。

`run_semiconductor_research`：加载面板 → IC 验证（整体/年度/当前截面）→
事件状态机回测（4 变体）→ 落盘 CSV + Markdown 报告。

依赖上游 `stock_analytics.pipelines.semiconductor` 门面产物（剪刀差/结构腿），
以及既有 Mart（close / 供给腿）。仅研究验证，不产生交易信号。
术语约定：本层（stock_strategy）是**验证层**——消费 stock_analytics 产出的特征
（feature / 候选因子），通过 IC / 回测 / 敏感性扫描**验证其是否为有效因子（factor）**。
本层不产生新特征。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger
from stock_strategy.industry.semiconductor.backtest import (
    MODE_LABELS,
    run_backtest,
)
from stock_strategy.industry.semiconductor.config import (
    DEFAULT_CONFIG_PATH,
    SemiconductorResearchConfig,
    load_semiconductor_research_config,
)
from stock_strategy.industry.semiconductor.data import load_semiconductor_panel
from stock_strategy.industry.semiconductor.ic import (
    attach_f60,
    current_cross_section,
    overall_ic,
    yearly_ic,
)
from stock_strategy.industry.semiconductor.report import (
    render_backtest_report,
    render_ic_report,
    write_research_outputs,
)


@dataclass(frozen=True, slots=True)
class SemiconductorResearchResult:
    """半导体深研线一次研究运行结果。"""

    panel: pl.DataFrame
    ic_overall: dict[str, float | None]
    ic_yearly: pl.DataFrame
    ic_current: pl.DataFrame
    backtest: pl.DataFrame
    files: dict[str, Path]


def run_semiconductor_research(
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    config: SemiconductorResearchConfig | None = None,
    output_dir: Path | str | None = None,
    storage_dir: Path | str | None = None,
) -> SemiconductorResearchResult:
    """运行半导体深研线 IC 验证 + 事件回测，落盘 CSV/MD 报告。

    ``output_dir`` 覆盖配置项；``storage_dir`` 覆盖数据根（测试用）。
    """
    cfg = config or load_semiconductor_research_config(config_path)
    panel = load_semiconductor_panel(
        storage_dir=storage_dir,
        industry=cfg.industry,
        start_date=cfg.start_date,
    )
    if panel.is_empty():
        raise ValueError("半导体研究面板为空（请先运行 run_semiconductor_legs）")

    # IC 验证（配置驱动的 fwd 窗口 / 腿列表 / 最小样本）
    ic_frame = attach_f60(panel, fwd=cfg.fwd_horizon)
    ic_legs = list(cfg.ic_legs)
    ic_overall = overall_ic(ic_frame, ic_legs, min_samples=cfg.ic_min_samples)
    ic_yearly = yearly_ic(ic_frame, ic_legs, min_samples=cfg.ic_min_samples)
    ic_current = current_cross_section(ic_frame, ic_legs)

    # 事件回测（配置驱动的防守阈值 / 样本外起点 / 年化）
    bt_result = run_backtest(
        panel,
        oos_start=cfg.oos_start,
        defense=cfg.defense,
        trading_days=cfg.trading_days,
    )

    labels = _ic_labels(ic_legs)
    ic_md = render_ic_report(
        ic_frame,
        overall=ic_overall,
        yearly=ic_yearly,
        current=ic_current,
        labels=labels,
    )
    bt_md = render_backtest_report(panel, bt_result, MODE_LABELS)
    files = write_research_outputs(
        output_dir=output_dir or cfg.output_dir,
        ic_md=ic_md,
        ic_yearly=ic_yearly,
        ic_current=ic_current,
        bt_md=bt_md,
        bt_result=bt_result,
    )

    logger.info("半导体深研线研究产物已落盘: %s", ", ".join(str(v) for v in files.values()))
    return SemiconductorResearchResult(
        panel=panel,
        ic_overall=ic_overall,
        ic_yearly=ic_yearly,
        ic_current=ic_current,
        backtest=bt_result,
        files=files,
    )


def _ic_labels(ic_legs: list[str]) -> dict[str, str]:
    """IC 验证腿的中文标签（默认映射；未知腿回退原名）。"""
    known = {
        "ai_capex_score": "云CapEx算力（AI 算力扩张）",
    }
    return {leg: known.get(leg, leg) for leg in ic_legs}


__all__ = ["SemiconductorResearchResult", "run_semiconductor_research"]
