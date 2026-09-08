"""公司层出口交易信号管线编排：公司观察表 → 三层信号。

依赖顺序（METHODOLOGY_COMPANY_FINAL §7）：
  公司观察表（暴露度×税号段）→ 三层信号（出口×资金×财报）→ 评级落盘。
产物保持既有契约路径（``data/analytics/industry/customs_company_*``），
Manifest 记录两阶段产物与数据水位。
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
from stock_analytics.pipelines.customs_company.exposure_panel import (
    build_exposure_panel,
    save_exposure_panel,
)
from stock_analytics.pipelines.customs_company.signal import (
    build_company_signal,
    save_company_signal,
)

logger = logging.getLogger(__name__)

MANIFEST_FILE = "customs_company_manifest.json"


def _load_customs_trade(customs_trade_path: Path | str) -> pl.DataFrame:
    df = pl.read_parquet(customs_trade_path)
    if df.is_empty():
        raise ValueError(f"海关黄金事实表为空: {customs_trade_path}")
    return df


def run_customs_company_pipeline(
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    artifact_root: Path | str | None = None,
    build_signal: bool = True,
) -> dict[str, Path]:
    """执行公司层出口交易信号管线并落盘产物与 Manifest。

    Args:
        config_path: 管线配置文件路径（YAML）。
        artifact_root: 产物输出目录覆盖（默认取配置 artifact_root）。
        build_signal: 是否合成三层信号（依赖公司观察表产物，默认 True）。

    Returns:
        dict: 步骤名 -> 产物路径。
    """
    config = load_customs_company_config(config_path)
    root = Path(artifact_root) if artifact_root else Path(config.artifact_root)
    root.mkdir(parents=True, exist_ok=True)

    trade = _load_customs_trade(config.customs_trade_path)

    # 1. 公司观察表（暴露度 × 税号段级序列）
    panel, latest, stats = build_exposure_panel(
        trade,
        exposure_map_path=config.exposure_map_path,
        hs_catalog_path=config.hs_catalog_path,
        segments_path=config.segments_path,
    )
    exposure_pq, exposure_csv = save_exposure_panel(panel, latest, root)

    outputs: dict[str, Path] = {
        "exposure_panel": exposure_pq,
        "exposure_latest": exposure_csv,
    }

    # 2. 三层信号（出口×资金×财报）
    if build_signal:
        signal = build_company_signal(
            latest,
            moneyflow_path=config.moneyflow_path,
            margin_path=config.margin_path,
            fina_path=config.fina_path,
            fund_window=config.fund_window,
            margin_chg_th=config.margin_chg_th,
        )
        signal_pq, signal_csv = save_company_signal(signal, root)
        outputs["signal_panel"] = signal_pq
        outputs["signal_latest"] = signal_csv

    # 3. Manifest（产物 + 数据水位 + 观察表统计）
    months = panel["report_month"].drop_nulls().unique().sort()
    manifest = build_manifest_base(
        artifact_type="customs_company",
        schema_version=config.schema_version,
        title=config.title,
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
        as_of_date=date.today(),
        artifact_root=str(root),
        config_path=config_path,
        watermarks={
            "exposure_panel": {
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
    logger.info("公司层出口交易信号管线完成: %s", root)
    return outputs


__all__ = ["MANIFEST_FILE", "run_customs_company_pipeline"]
