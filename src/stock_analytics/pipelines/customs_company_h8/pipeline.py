"""动态 H8 公司层出口交易信号管线编排：暴露 Mart → 公司×产品面板 → 三层信号。

输入 ``customs_company_h8_exposure.parquet``（公司×月份×H8 暴露 Mart），
聚合公司×产品×月份面板（``panel.py``），再复用 ``customs_company.signal``
的三层信号口径（出口前瞻 × 资金确认 × 财报真扩张 → A/B/C/D/回避-顶背离）。
产物独立命名 ``customs_company_h8_*``；产品映射由报告期主营构成动态生成。
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.artifacts import build_manifest_base
from stock_analytics.pipelines.customs_company.config import (
    DEFAULT_CONFIG_PATH,
    load_customs_company_config,
)
from stock_analytics.pipelines.customs_company.signal import (
    build_company_signal,
    load_quality_layers,
)
from stock_analytics.pipelines.customs_company_h8.panel import (
    build_company_h8_product_panel,
    save_company_h8_product_panel,
)

logger = logging.getLogger(__name__)

MANIFEST_FILE = "customs_company_h8_manifest.json"
SIGNAL_PANEL_FILE = "customs_company_h8_signal.parquet"
SIGNAL_LATEST_FILE = "customs_company_h8_signal_latest.csv"

DEFAULT_EXPOSURE_MART = "data/curated/mart/customs_company_h8_exposure.parquet"
DEFAULT_CUSTOMS_TRADE = "data/curated/industry/customs_trade_gacc.parquet"
DEFAULT_ARTIFACT_ROOT = "data/analytics/industry"

# 研究口径：只消费 GACC 官方数据（source=GACC，2018-01 起）；
# customs_trade_gacc.parquet 为纯 GACC（UN 数据见 customs_trade.parquet）。
RESEARCH_SOURCES: tuple[str, ...] = ("GACC",)


def _load_frame(path: Path | str) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if frame.is_empty():
        raise ValueError(f"Parquet 数据为空: {path}")
    return frame


def run_customs_company_h8_pipeline(
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    exposure_mart_path: Path | str = DEFAULT_EXPOSURE_MART,
    customs_trade_path: Path | str = DEFAULT_CUSTOMS_TRADE,
    artifact_root: Path | str | None = None,
    build_signal: bool = True,
    moneyflow_path: Path | str | None = None,
    margin_path: Path | str | None = None,
    fina_path: Path | str | None = None,
) -> dict[str, Path]:
    """执行动态 H8 公司层出口交易信号管线并落盘产物与 Manifest。

    Args:
        config_path: 管线配置文件路径（资金/财报/fund 参数复用 customs_company.yaml）。
        exposure_mart_path: 公司-H8 月度暴露 Mart（``customs_company_h8.py`` 产物）。
        customs_trade_path: 海关黄金事实表（产品内单位唯一性判定；研究口径只消费 GACC 段）。
        artifact_root: 产物输出目录覆盖（默认 ``data/analytics/industry``）。
        build_signal: 是否合成三层信号（默认 True）。
        moneyflow_path: 主力资金目录覆盖（默认取配置）。
        margin_path: 两融目录覆盖（默认取配置）。
        fina_path: 财报指标目录覆盖（默认取配置）。

    Returns:
        dict: 步骤名 -> 产物路径。
    """
    config = load_customs_company_config(config_path)
    root = Path(artifact_root) if artifact_root else Path(config.artifact_root)
    root.mkdir(parents=True, exist_ok=True)

    exposure_mart = _load_frame(exposure_mart_path)
    customs_trade = _load_frame(customs_trade_path)
    if "source" in customs_trade.columns:
        customs_trade = customs_trade.filter(pl.col("source").is_in(RESEARCH_SOURCES))

    # 1. 公司×产品×月份面板（3MMA yoy/驱动/拐点/二阶导）
    panel, latest, stats = build_company_h8_product_panel(exposure_mart, customs_trade)
    panel_pq, panel_csv = save_company_h8_product_panel(panel, latest, root)

    outputs: dict[str, Path] = {
        "h8_product_panel": panel_pq,
        "h8_product_latest": panel_csv,
    }

    # 2. 三层信号（出口前瞻 × 资金确认 × 财报真扩张）
    if build_signal:
        signal = build_company_signal(
            latest,
            moneyflow_path=moneyflow_path or config.moneyflow_path,
            margin_path=margin_path or config.margin_path,
            fina_path=fina_path or config.fina_path,
            fund_window=config.fund_window,
            margin_chg_th=config.margin_chg_th,
            exclude_products=config.excluded_products,
        )
        signal = load_quality_layers(signal, fina_path or config.fina_path)
        signal_pq = root / SIGNAL_PANEL_FILE
        signal_csv = root / SIGNAL_LATEST_FILE
        signal.write_parquet(signal_pq)
        signal.write_csv(signal_csv, include_header=True)
        outputs["h8_signal_panel"] = signal_pq
        outputs["h8_signal_latest"] = signal_csv
        if config.excluded_products:
            stats["excluded_products"] = {
                "list": list(config.excluded_products),
                "rows": int(
                    latest.filter(pl.col("product_key").is_in(config.excluded_products)).height
                ),
            }

    # 3. Manifest（产物 + 数据水位 + 面板统计）
    months = panel["report_month"].drop_nulls().unique().sort()
    manifest = build_manifest_base(
        artifact_type="customs_company_h8",
        schema_version=config.schema_version,
        title="公司-H8 动态暴露 → 三层信号评级（fina_mainbz 动态映射，无人工 CSV）",
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
        as_of_date=date.today(),
        artifact_root=str(root),
        config_path=config_path,
        watermarks={
            "h8_product_panel": {
                "min": str(months.first()) if months.len() else None,
                "max": str(months.last()) if months.len() else None,
            }
        },
    )
    manifest["stats"] = stats
    manifest_path = root / MANIFEST_FILE
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("动态 H8 公司层出口交易信号管线完成: %s", root)
    return outputs


__all__ = [
    "DEFAULT_EXPOSURE_MART",
    "MANIFEST_FILE",
    "SIGNAL_LATEST_FILE",
    "SIGNAL_PANEL_FILE",
    "run_customs_company_h8_pipeline",
]
