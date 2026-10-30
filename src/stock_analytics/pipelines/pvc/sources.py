"""聚氯乙烯 (PVC) 数据源提取与加载模块。

负责从本地 Curated 数据湖和声明式配置中提取：
1. 产能事件库 (capacity_projects.yaml)
2. 工艺理论成本模型 (cost_models.yaml)
3. 大商所期货行情与交割仓单 (futures_daily.parquet / futures_inventory.parquet)
4. 现期基差与仓单异动 Mart (chemical_basis_inventory_mart.parquet)
5. 隆众/Mysteel 周度开工率与企业厂库 (chemical_weekly_survey.parquet)
6. 海关总署 GACC 出口月度数据 (customs_trade_gacc.parquet)
7. 生意社 100ppi 现货基准出厂价 (chemical_spot_price.parquet)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PVCCapacityProject:
    """PVC 扩产/投产项目结构体。"""

    project_id: str
    company: str
    plant_name: str
    province: str
    technology: str
    capacity_w_tons: float
    status: str
    expected_start: str | None
    actual_start: str | None
    source: str


def load_pvc_capacity_projects(config_path: Path | str) -> list[PVCCapacityProject]:
    """读取 PVC 产能建设项目库。"""
    p = Path(config_path)
    if not p.exists():
        logger.warning("PVC 产能建设项目库不存在: %s", p)
        return []

    try:
        raw: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        projects_data = raw.get("projects", [])
        return [
            PVCCapacityProject(
                project_id=str(pj.get("project_id", "")),
                company=str(pj.get("company", "")),
                plant_name=str(pj.get("plant_name", "")),
                province=str(pj.get("province", "")),
                technology=str(pj.get("technology", "")),
                capacity_w_tons=float(pj.get("capacity_w_tons", 0.0)),
                status=str(pj.get("status", "")),
                expected_start=pj.get("expected_start"),
                actual_start=pj.get("actual_start"),
                source=str(pj.get("source", "")),
            )
            for pj in projects_data
        ]
    except Exception as exc:
        logger.warning("解析 PVC 产能项目库异常: %s", exc)
        return []


def load_pvc_cost_models(config_path: Path | str) -> dict[str, Any]:
    """读取 PVC 多工艺成本模型参数。"""
    p = Path(config_path)
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("解析 PVC 成本模型异常: %s", exc)
        return {}


def load_pvc_warehouse_receipts(curated_root: Path | str) -> pl.DataFrame:
    """从 futures_inventory 读取 PVC (代码 V) 交易所交割仓单历史。"""
    path = Path(curated_root) / "industry" / "futures_inventory.parquet"
    if not path.exists():
        return pl.DataFrame()
    try:
        df = pl.read_parquet(path)
        sub = df.filter(pl.col("symbol") == "V").sort("trade_date")
        return sub.select(
            [
                pl.col("trade_date").cast(pl.Date),
                pl.col("inventory").cast(pl.Float64).alias("warrant_contracts"),
                (pl.col("inventory") * 5.0 / 10000.0).cast(pl.Float64).alias("warrant_w_tons"),
                pl.col("change").cast(pl.Float64).alias("warrant_change"),
            ]
        )
    except Exception as exc:
        logger.warning("读取 PVC 仓单数据失败: %s", exc)
        return pl.DataFrame()


def load_pvc_weekly_survey(curated_root: Path | str) -> pl.DataFrame:
    """从 chemical_weekly_survey 读取 PVC 周度开工率与样本企业厂库。"""
    path = Path(curated_root) / "industry" / "chemical_weekly_survey.parquet"
    if not path.exists():
        return pl.DataFrame()
    try:
        df = pl.read_parquet(path)
        sym_col = "symbol" if "symbol" in df.columns else "product_name"
        sub = df.filter(
            (pl.col(sym_col).str.to_uppercase() == "V")
            | (pl.col("product_name").str.contains("聚氯乙烯"))
        ).sort("trade_date")
        return sub.select(
            [
                pl.col("trade_date").cast(pl.Date),
                pl.col("operating_rate_pct").cast(pl.Float64),
                pl.col("factory_inventory_w_tons").cast(pl.Float64),
            ]
        )
    except Exception as exc:
        logger.warning("读取 PVC 周度调查数据失败: %s", exc)
        return pl.DataFrame()


def load_pvc_customs_export(curated_root: Path | str) -> pl.DataFrame:
    """从 customs_trade_gacc 读取 PVC (税号 39041010/39041090) 海关月度出口。"""
    path = Path(curated_root) / "industry" / "customs_trade_gacc.parquet"
    if not path.exists():
        return pl.DataFrame()
    try:
        df = pl.read_parquet(path)
        sub = (
            df.filter(pl.col("hs_code").str.starts_with("3904"))
            .group_by("trade_date")
            .agg(
                [
                    (pl.col("export_volume").sum() / 10000.0).alias("export_volume_w_tons"),
                    (pl.col("export_value_usd").sum() / 1e4).alias("export_value_w_usd"),
                ]
            )
            .sort("trade_date")
        )
        # 计算同比
        sub = sub.with_columns(
            (
                (pl.col("export_volume_w_tons") - pl.col("export_volume_w_tons").shift(12))
                / pl.col("export_volume_w_tons").shift(12)
                * 100.0
            ).alias("export_volume_yoy_pct")
        )
        return sub
    except Exception as exc:
        logger.warning("读取 PVC 海关出口数据失败: %s", exc)
        return pl.DataFrame()


def load_pvc_basis_mart(curated_root: Path | str) -> pl.DataFrame:
    """从 chemical_basis_inventory_mart 读取 PVC 现期微观时钟特征。"""
    path = Path(curated_root) / "mart" / "chemical_basis_inventory_mart.parquet"
    if not path.exists():
        return pl.DataFrame()
    try:
        df = pl.read_parquet(path)
        return df.filter(
            (pl.col("commodity_code") == "V") | (pl.col("futures_symbol") == "V")
        ).sort("trade_date")
    except Exception as exc:
        logger.warning("读取 PVC 期现基差 Mart 失败: %s", exc)
        return pl.DataFrame()
