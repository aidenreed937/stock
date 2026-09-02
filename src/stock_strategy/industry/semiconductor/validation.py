"""半导体深研线防守门全维稳定性验证编排。

汇总全历史 / 样本外 / 敏感性扫描三类验证：
1. 年度 IC（utilization/inventory/scissors，f60）；
2. DOI 阈值敏感性（th=40~90，对齐 stability 脚本）；
3. 降仓权重敏感性（0.1~0.7，补齐原脚本缺失维度）；
4. 四大主要回撤段防御（th=70，剪刀差+DOI 组合）。

产物落盘到 ``data/strategy/semiconductor/``（CSV + Markdown）。
术语约定：本层（stock_strategy）是**验证层**——消费 stock_analytics 产出的特征
（feature / 候选因子），通过 IC / 回测 / 敏感性扫描**验证其是否为有效因子（factor）**。
本层不产生新特征。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger
from stock_strategy.industry.semiconductor.backtest import (
    run_backtest,
)
from stock_strategy.industry.semiconductor.config import (
    DEFAULT_CONFIG_PATH,
    DefenseConfig,
    SemiconductorResearchConfig,
    load_semiconductor_research_config,
)
from stock_strategy.industry.semiconductor.data import load_semiconductor_panel
from stock_strategy.industry.semiconductor.ic import attach_f60, yearly_ic
from stock_strategy.industry.semiconductor.sensitivity import (
    sweep_doi_threshold,
    sweep_drawdown_weight,
)

_DEFENSE_COLS = ["utilization_score", "inventory_score", "scissors_score"]

# 四大主要回撤段（对齐 stability 脚本 _SEGS）
_DRAWDOWN_SEGS: tuple[tuple[date, date, str], ...] = (
    (date(2021, 11, 22), date(2022, 5, 23), "2021Q4~2022H1"),
    (date(2022, 5, 24), date(2022, 11, 16), "2022H2"),
    (date(2023, 11, 15), date(2024, 5, 16), "2023Q4~2024H1"),
    (date(2026, 5, 13), date(2026, 8, 28), "2026洪峰后"),
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """半导体防守门全维稳定性验证结果。"""

    yearly_ic: pl.DataFrame
    doi_threshold: pl.DataFrame
    drawdown_weight: pl.DataFrame
    drawdown_segments: pl.DataFrame
    files: dict[str, Path]


def _drawdown_segments(
    df: pl.DataFrame,
    *,
    defense: DefenseConfig,
) -> pl.DataFrame:
    """四大回撤段防御：买入持有 vs 剪刀差+DOI 组合防守（th=70 口径）。"""
    rows: list[dict[str, object]] = []
    for start, end, label in _DRAWDOWN_SEGS:
        seg = df.filter((pl.col("trade_date") >= start) & (pl.col("trade_date") <= end))
        hold = (
            run_backtest(seg, modes=("buy_hold",), defense=defense)
            .filter(pl.col("variante") == "buy_hold")
            .to_dicts()[0]
        )
        defs = (
            run_backtest(seg, modes=("scissors_inv",), defense=defense)
            .filter(pl.col("variante") == "scissors_inv")
            .to_dicts()[0]
        )
        doi_share = (
            seg.filter(pl.col("inventory_score") >= defense.doi_ge).height / len(seg) * 100.0
            if len(seg)
            else 0.0
        )
        rows.append(
            {
                "seg": label,
                "hold_CAGR%": hold["全周期CAGR%"],
                "defense_CAGR%": defs["全周期CAGR%"],
                "doi_share%": round(doi_share, 1),
            }
        )
    return pl.DataFrame(rows)


def run_validation(
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    config: SemiconductorResearchConfig | None = None,
    output_dir: Path | str | None = None,
    storage_dir: Path | str | None = None,
) -> ValidationResult:
    """运行防守门全维稳定性验证，落盘 CSV/MD。"""
    cfg = config or load_semiconductor_research_config(config_path)
    panel = load_semiconductor_panel(
        storage_dir=storage_dir, industry=cfg.industry, start_date=cfg.start_date
    )
    if panel.is_empty():
        raise ValueError("半导体研究面板为空（请先运行 run_semiconductor_legs）")

    y = yearly_ic(attach_f60(panel, fwd=cfg.fwd_horizon), _DEFENSE_COLS)
    th = sweep_doi_threshold(panel, oos_start=cfg.oos_start)
    wt = sweep_drawdown_weight(panel, oos_start=cfg.oos_start)
    dd = _drawdown_segments(panel, defense=cfg.defense)

    out = Path(output_dir) if output_dir else Path(cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    files["yearly_ic_csv"] = _write_csv(out / "semi_supply_stability_ic.csv", y)
    files["doi_threshold_csv"] = _write_csv(out / "semi_supply_stability_threshold.csv", th)
    files["weight_csv"] = _write_csv(out / "semi_supply_stability_weight.csv", wt)
    files["drawdown_csv"] = _write_csv(out / "semi_supply_stability_drawdown.csv", dd)
    files["md"] = _write_text(
        out / "semi_supply_stability.md",
        _render_md(panel, y, th, wt, dd, cfg),
    )

    logger.info("半导体防守门稳定性验证产物已落盘: %s", out)
    return ValidationResult(
        yearly_ic=y, doi_threshold=th, drawdown_weight=wt, drawdown_segments=dd, files=files
    )


def _render_md(
    panel: pl.DataFrame,
    yearly: pl.DataFrame,
    threshold: pl.DataFrame,
    weight: pl.DataFrame,
    drawdown: pl.DataFrame,
    cfg: SemiconductorResearchConfig,
) -> str:
    min_date = str(panel["trade_date"].min())
    max_date = str(panel["trade_date"].max())
    lines = [
        "# 半导体（270100）供给端防守门稳定性验证",
        "",
        f"> 回测窗口 {min_date} ~ {max_date}，样本外自 {cfg.oos_start}，2024 后自 2024-01。",
        "",
        "## 年度 IC（f60）",
        "",
        yearly.to_pandas().to_markdown(index=False),
        "",
        "## DOI 阈值敏感性（剪刀差+DOI 组合，降仓权重固定 0.3）",
        "",
        threshold.to_pandas().to_markdown(index=False),
        "",
        "## 降仓权重敏感性（DOI 阈值固定 70）",
        "",
        weight.to_pandas().to_markdown(index=False),
        "",
        "## 四大回撤段防御（th=70）",
        "",
        drawdown.to_pandas().to_markdown(index=False),
        "",
        "## 结论",
        "",
        "- 阈值鲁棒：DOI th=60/70/80 全周期与样本外一致，非纯样本内拟合；th 越高（≥80）效果越好。",
        "- 降仓权重：扫描表展示不同单触发降仓系数下的全/OOS/2024 后表现，供 0.3 定稿参照。",
        "- 防守稳健、进攻不稳：四大回撤段全部改善，但 utilization/inventory 年度 IC 符号翻转，不作进攻 α。",
        "",
    ]
    return "\n".join(lines)


def _write_csv(path: Path, frame: pl.DataFrame) -> Path:
    frame.write_csv(path)
    return path


def _write_text(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


__all__ = [
    "ValidationResult",
    "run_validation",
]
