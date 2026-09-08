"""公司层出口交易信号管线配置（customs_company）。

把行业层出口景气下沉到受益公司（暴露度 × 税号段级序列），合成三层信号
（出口前瞻 × 资金确认 × 财报真扩张）评级 A/B/C/D/回避-顶背离（
METHODOLOGY_COMPANY_FINAL.md 定稿口径）。产物路径与既有脚本契约一致
（``data/analytics/industry/customs_company_*.parquet/csv``），供抓机会手册消费。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/customs_company.yaml"

DEFAULT_ARTIFACT_ROOT = "data/analytics/industry"
EXPOSURE_PANEL_FILE = "customs_company_exposure.parquet"
EXPOSURE_LATEST_FILE = "customs_company_exposure_latest.csv"
SIGNAL_PANEL_FILE = "customs_company_signal.parquet"
SIGNAL_LATEST_FILE = "customs_company_signal_latest.csv"

DEFAULT_CUSTOMS_TRADE = "data/curated/industry/customs_trade.parquet"
DEFAULT_EXPOSURE_MAP = "config/data/customs/company_exposure_map.csv"
DEFAULT_HS_CATALOG = "config/data/customs/hs_codes_catalog.csv"
DEFAULT_SEGMENTS = "config/data/customs/taxline_segments.csv"
DEFAULT_MONEYFLOW = "data/curated/tushare/market=CN/moneyflow"
DEFAULT_MARGIN = "data/curated/tushare/market=CN/margin_detail"
DEFAULT_FINA = "data/curated/tushare/market=CN/fina_indicator"


@dataclass(frozen=True, slots=True)
class CustomsCompanyConfig:
    """公司层出口交易信号管线配置（METHODOLOGY_COMPANY_FINAL 定稿口径）。"""

    schema_version: int = 1
    title: str = "公司层出口交易信号管线（暴露度×税号段 → 三层信号评级）"
    artifact_root: str = DEFAULT_ARTIFACT_ROOT
    customs_trade_path: str = DEFAULT_CUSTOMS_TRADE
    exposure_map_path: str = DEFAULT_EXPOSURE_MAP
    hs_catalog_path: str = DEFAULT_HS_CATALOG
    segments_path: str = DEFAULT_SEGMENTS
    moneyflow_path: str = DEFAULT_MONEYFLOW
    margin_path: str = DEFAULT_MARGIN
    fina_path: str = DEFAULT_FINA
    fund_window: int = 20  # 资金腿近 N 交易日
    margin_chg_th: float = 2.0  # 融资余额 20 日变化率阈值（%）

    @property
    def artifact_root_path(self) -> Path:
        return Path(self.artifact_root)


def load_customs_company_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> CustomsCompanyConfig:
    """从 YAML 读取公司层管线配置；缺失/异常时使用默认值。"""
    path = Path(config_path)
    if not path.exists():
        return CustomsCompanyConfig()

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return CustomsCompanyConfig()
    if not isinstance(payload, dict):
        return CustomsCompanyConfig()

    def _str(key: str, default: str) -> str:
        value: Any = payload.get(key, default)
        return value if isinstance(value, str) and value else default

    def _int(key: str, default: int) -> int:
        try:
            return int(payload.get(key, default))
        except (TypeError, ValueError):
            return default

    def _number(key: str, default: float) -> float:
        try:
            return float(payload.get(key, default))
        except (TypeError, ValueError):
            return default

    return CustomsCompanyConfig(
        schema_version=_int("schema_version", 1),
        title=_str("title", "公司层出口交易信号管线（暴露度×税号段 → 三层信号评级）"),
        artifact_root=_str("artifact_root", DEFAULT_ARTIFACT_ROOT),
        customs_trade_path=_str("customs_trade_path", DEFAULT_CUSTOMS_TRADE),
        exposure_map_path=_str("exposure_map_path", DEFAULT_EXPOSURE_MAP),
        hs_catalog_path=_str("hs_catalog_path", DEFAULT_HS_CATALOG),
        segments_path=_str("segments_path", DEFAULT_SEGMENTS),
        moneyflow_path=_str("moneyflow_path", DEFAULT_MONEYFLOW),
        margin_path=_str("margin_path", DEFAULT_MARGIN),
        fina_path=_str("fina_path", DEFAULT_FINA),
        fund_window=_int("fund_window", 20),
        margin_chg_th=_number("margin_chg_th", 2.0),
    )


__all__ = [
    "DEFAULT_ARTIFACT_ROOT",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_CUSTOMS_TRADE",
    "DEFAULT_EXPOSURE_MAP",
    "DEFAULT_FINA",
    "DEFAULT_HS_CATALOG",
    "DEFAULT_MARGIN",
    "DEFAULT_MONEYFLOW",
    "DEFAULT_SEGMENTS",
    "EXPOSURE_LATEST_FILE",
    "EXPOSURE_PANEL_FILE",
    "SIGNAL_LATEST_FILE",
    "SIGNAL_PANEL_FILE",
    "CustomsCompanyConfig",
    "load_customs_company_config",
]
