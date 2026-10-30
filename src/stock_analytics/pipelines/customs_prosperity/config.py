"""海关出口景气研究管线配置（customs_prosperity）。

配置驱动：月度 SOP（METHODOLOGY_FINAL §8）的「金额面板 → 量价分解 → 商品拐点 →
观察表」四步在此统一编排，产物与既有脚本路径保持一致
（``data/analytics/industry/customs_*.parquet``），供 three_leg 与公司层管线消费。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/customs_prosperity.yaml"

# 产物根目录与四步产物文件名（保持与既有脚本/下游消费者路径契约一致）。
DEFAULT_ARTIFACT_ROOT = "data/analytics/industry"
AMOUNT_PANEL_FILE = "customs_export_prosperity_panel.parquet"
VOLUME_PRICE_FILE = "customs_l2_volume_price_monthly.parquet"
PRODUCT_PANEL_FILE = "customs_product_volume_price.parquet"
FORWARD_WATCH_L2_FILE = "customs_forward_watch_l2.parquet"
FORWARD_WATCH_L3_FILE = "customs_forward_watch_l3.parquet"

# 数据源路径（黄金表与配置类资产，可被 YAML 覆盖）
# 海关研究统一采用 GACC 官方数据（source=GACC，2018-01 起）；
# customs_trade_gacc.parquet 为纯 GACC 官方行（2026-10 已清出 UN Comtrade 桥接行，
# UN 桥接/扩展数据见 customs_trade.parquet）；research_sources 过滤保留为防御性。
DEFAULT_CUSTOMS_TRADE = "data/curated/industry/customs_trade_gacc.parquet"
DEFAULT_HS_CATALOG = "config/data/customs/good_h8_codes.csv"

# 研究口径：只消费 GACC 官方数据；传 ("UN_Comtrade", "GACC") 可复现旧混合桥接口径。
RESEARCH_SOURCES: tuple[str, ...] = ("GACC",)


@dataclass(frozen=True, slots=True)
class CustomsProsperityConfig:
    """海关出口景气研究管线配置。

    阈值与口径均来自 METHODOLOGY_FINAL 定稿；YAML 中缺失或异常时回退默认值。
    """

    schema_version: int = 1
    title: str = "海关出口景气研究管线（金额面板→量价分解→商品拐点→观察表）"
    artifact_root: str = DEFAULT_ARTIFACT_ROOT
    customs_trade_path: str = DEFAULT_CUSTOMS_TRADE
    hs_catalog_path: str = DEFAULT_HS_CATALOG
    # 研究消费的黄金表 source 白名单（默认仅 GACC 官方数据）
    research_sources: tuple[str, ...] = RESEARCH_SOURCES
    # L2 聚合跳过组合码（METHODOLOGY §6.5 强制规则 4）
    skip_l2: frozenset[str] = frozenset({"801033.SI;801034.SI"})
    # 行业聚合层量价置空的伪影产品（METHODOLOGY §7.5）
    skip_vp: frozenset[str] = frozenset({"hydrogen_electrolyzer"})
    # 桥接校验跳过的高分化产品（METHODOLOGY §6.5 审计口径）
    skip_bridge_products: frozenset[str] = frozenset()
    # 财报后视验证数据源（L2 四张表 + L3 一张表，data-catalog §1.3 口径）
    l2_financial_datasets: tuple[str, ...] = (
        "sw_2021_l2_fs_non_financial",
        "sw_2021_l2_fs_bank",
        "sw_2021_l2_fs_security",
        "sw_2021_l2_fs_insurance",
    )
    l3_financial_dataset: str = "sw_2021_l3_fs_non_financial"
    consistency_table: dict[str, tuple[float, str]] = field(default_factory=dict)

    @property
    def artifact_root_path(self) -> Path:
        return Path(self.artifact_root)


def load_customs_prosperity_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> CustomsProsperityConfig:
    """从 YAML 读取海关出口景气管线配置；缺失/异常时使用默认值。"""
    path = Path(config_path)
    if not path.exists():
        return CustomsProsperityConfig()

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return CustomsProsperityConfig()
    if not isinstance(payload, dict):
        return CustomsProsperityConfig()

    def _str(key: str, default: str) -> str:
        value: Any = payload.get(key, default)
        return value if isinstance(value, str) and value else default

    def _frozenset(key: str, default: frozenset[str]) -> frozenset[str]:
        value = payload.get(key)
        if isinstance(value, list):
            return frozenset(item for item in value if isinstance(item, str))
        return default

    def _tuple(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = payload.get(key)
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return default

    return CustomsProsperityConfig(
        schema_version=int(payload.get("schema_version", 1)),
        title=_str("title", "海关出口景气研究管线（金额面板→量价分解→商品拐点→观察表）"),
        artifact_root=_str("artifact_root", DEFAULT_ARTIFACT_ROOT),
        customs_trade_path=_str("customs_trade_path", DEFAULT_CUSTOMS_TRADE),
        hs_catalog_path=_str("hs_catalog_path", DEFAULT_HS_CATALOG),
        research_sources=_tuple("research_sources", RESEARCH_SOURCES),
        skip_l2=_frozenset("skip_l2", frozenset({"801033.SI;801034.SI"})),
        skip_vp=_frozenset("skip_vp", frozenset({"hydrogen_electrolyzer"})),
        skip_bridge_products=_frozenset("skip_bridge_products", frozenset()),
        l2_financial_datasets=_tuple(
            "l2_financial_datasets",
            (
                "sw_2021_l2_fs_non_financial",
                "sw_2021_l2_fs_bank",
                "sw_2021_l2_fs_security",
                "sw_2021_l2_fs_insurance",
            ),
        ),
        l3_financial_dataset=_str("l3_financial_dataset", "sw_2021_l3_fs_non_financial"),
        consistency_table=_load_consistency_table(payload.get("consistency_table")),
    )


def _load_consistency_table(value: Any) -> dict[str, tuple[float, str]]:
    """解析一致率分级表 YAML（02 文档口径，仅 L2）。

    YAML 形态::

        consistency_table:
          "801738.SI": [1.00, "A"]
    """
    if not isinstance(value, dict):
        return {}
    table: dict[str, tuple[float, str]] = {}
    for code, raw in value.items():
        if isinstance(raw, list) and len(raw) == 2:
            try:
                table[str(code)] = (float(raw[0]), str(raw[1]).upper())
            except (TypeError, ValueError):
                continue
    return table


__all__ = [
    "AMOUNT_PANEL_FILE",
    "DEFAULT_ARTIFACT_ROOT",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_CUSTOMS_TRADE",
    "DEFAULT_HS_CATALOG",
    "FORWARD_WATCH_L2_FILE",
    "FORWARD_WATCH_L3_FILE",
    "PRODUCT_PANEL_FILE",
    "RESEARCH_SOURCES",
    "VOLUME_PRICE_FILE",
    "CustomsProsperityConfig",
    "load_customs_prosperity_config",
]
