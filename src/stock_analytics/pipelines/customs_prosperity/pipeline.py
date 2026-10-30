"""海关出口景气研究管线编排：金额面板 → 量价分解 → 商品拐点 → 观察表。

依赖顺序（METHODOLOGY_FINAL §8 月度 SOP）：
  金额面板 / 量价分解 / 商品拐点 三者可独立并行（都只依赖 customs_trade 黄金表）；
  观察表依赖 金额面板 + 量价分解 的产物文件，必须在两者之后执行。

产物保持既有契约路径（``data/analytics/industry/customs_*.parquet``），
Manifest 记录四步产物与数据水位。
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.artifacts import build_manifest_base
from stock_analytics.pipelines.customs_prosperity.amount_panel import (
    build_amount_panel,
    save_amount_panel,
)
from stock_analytics.pipelines.customs_prosperity.config import (
    DEFAULT_CONFIG_PATH,
    load_customs_prosperity_config,
)
from stock_analytics.pipelines.customs_prosperity.forward_watch import build_forward_watch
from stock_analytics.pipelines.customs_prosperity.product_panel import (
    build_product_panel,
    save_product_panel,
)
from stock_analytics.pipelines.customs_prosperity.volume_price import (
    build_volume_price_panel,
    save_volume_price_panel,
)

logger = logging.getLogger(__name__)

MANIFEST_FILE = "customs_prosperity_manifest.json"


def _load_customs_trade(customs_trade_path: Path | str) -> pl.DataFrame:
    df = pl.read_parquet(customs_trade_path)
    if df.is_empty():
        raise ValueError(f"海关黄金事实表为空: {customs_trade_path}")
    return df


def _build_watermarks(frames: dict[str, pl.DataFrame]) -> dict[str, dict[str, str | None]]:
    """提取各面板数据水位（report_month 最小/最大），写入 Manifest。"""
    watermarks: dict[str, dict[str, str | None]] = {}
    for name, frame in frames.items():
        if frame.is_empty() or "report_month" not in frame.columns:
            watermarks[name] = {"min": None, "max": None}
            continue
        months = frame["report_month"].drop_nulls().unique().sort()
        watermarks[name] = {
            "min": str(months.first()) if months.len() else None,
            "max": str(months.last()) if months.len() else None,
        }
    return watermarks


def run_customs_prosperity_pipeline(
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    storage_dir: Path | str | None = None,
    artifact_root: Path | str | None = None,
    build_product: bool = True,
    build_forward: bool = True,
    product_bridge_check: bool = True,
) -> dict[str, Path]:
    """执行海关出口景气研究管线四步并落盘产物与 Manifest。

    Args:
        config_path: 管线配置文件路径（YAML）。
        storage_dir: 数据根目录（维度/财报读取，默认 None 使用项目内置 data/）。
        artifact_root: 产物输出目录覆盖（默认取配置 artifact_root）。
        build_product: 是否构建商品级拐点面板（默认 True）。
        build_forward: 是否构建观察表（依赖金额+量价产物，默认 True）。
        product_bridge_check: 商品面板是否执行桥接校验（L3 归属断言；
            依赖维度黄金表，测试/离线场景可关闭）。

    Returns:
        dict: 步骤名 -> 产物路径。
    """
    config = load_customs_prosperity_config(config_path)
    root = Path(artifact_root) if artifact_root else Path(config.artifact_root)
    root.mkdir(parents=True, exist_ok=True)

    trade = _load_customs_trade(config.customs_trade_path)
    outputs: dict[str, Path] = {}
    frames: dict[str, pl.DataFrame] = {}

    # 1. 金额面板
    amount = build_amount_panel(trade, skip_l2=config.skip_l2, sources=config.research_sources)
    outputs["amount"] = save_amount_panel(amount, root)
    frames["amount"] = amount

    # 2. 量价分解（L2/L3）
    vp = build_volume_price_panel(
        trade,
        skip_l2=config.skip_l2,
        skip_vp=config.skip_vp,
        sources=config.research_sources,
    )
    outputs["volume_price"] = save_volume_price_panel(vp, root)
    frames["volume_price"] = vp

    # 3. 商品级拐点（独立，可跳过）
    if build_product:
        product = build_product_panel(
            trade,
            catalog_path=config.hs_catalog_path,
            storage_dir=storage_dir or "data",
            validate_bridge_flag=product_bridge_check,
            sources=config.research_sources,
        )
        outputs["product"] = save_product_panel(product, root)
        frames["product"] = product

    # 4. 观察表（依赖金额+量价产物文件，必须在两者之后）
    if build_forward:
        fw_outputs = build_forward_watch(
            root,
            consistency_table=config.consistency_table,
            l2_financial_datasets=config.l2_financial_datasets,
            l3_financial_dataset=config.l3_financial_dataset,
            storage_dir=storage_dir or "data",
        )
        outputs.update({f"forward_watch_{k.lower()}": v for k, v in fw_outputs.items()})

    # 5. Manifest（产物 + 数据水位）
    manifest = build_manifest_base(
        artifact_type="customs_prosperity",
        schema_version=config.schema_version,
        title=config.title,
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
        as_of_date=date.today(),
        artifact_root=str(root),
        config_path=config_path,
        watermarks=_build_watermarks(frames),
    )
    manifest_path = root / MANIFEST_FILE
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("海关出口景气管线完成: %s", root)
    return outputs


__all__ = ["MANIFEST_FILE", "run_customs_prosperity_pipeline"]
