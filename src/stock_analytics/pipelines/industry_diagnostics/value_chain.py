"""中观产业链上下游图谱多级配置扫描与级联继承解析引擎。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from stock_analytics.pipelines.industry_diagnostics.types import IndustryValueChainSnapshot
from stock_core.utils.logger import logger


def _collect_value_chain_dicts(cfg_path: Path) -> dict[str, dict[str, Any]]:
    """扫描指定单文件或目录下全部 YAML 文件，合并构建行业产业链全集字典。"""
    aggregated: dict[str, dict[str, Any]] = {}
    files_to_read: list[Path] = []

    if cfg_path.is_dir():
        files_to_read = sorted(list(cfg_path.glob("*.yaml")) + list(cfg_path.glob("*.yml")))
    elif cfg_path.is_file():
        files_to_read = [cfg_path]

    for f_path in files_to_read:
        try:
            with open(f_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            ind_dict = data.get("industries", {})
            if isinstance(ind_dict, dict):
                for k, v in ind_dict.items():
                    if isinstance(v, dict):
                        aggregated[k] = v
        except Exception as exc:
            logger.warning(f"读取产业链图谱文件 {f_path} 失败: {exc}")

    return aggregated


def _merge_value_chain_snapshots(
    parent: dict[str, Any] | None,
    child: dict[str, Any] | None,
) -> IndustryValueChainSnapshot:
    """级联深合并父子层级产业链快照 (子级专属差量优先覆盖，共性自动继承)。"""
    if not parent and not child:
        return IndustryValueChainSnapshot()
    if not parent:
        c = child or {}
        return IndustryValueChainSnapshot(
            upstream=list(c.get("upstream", [])),
            downstream=list(c.get("downstream", [])),
            cost_sensitivity=str(c.get("cost_sensitivity", "")),
            high_frequency_indicators=list(c.get("high_frequency_indicators", [])),
        )
    if not child:
        p = parent
        return IndustryValueChainSnapshot(
            upstream=list(p.get("upstream", [])),
            downstream=list(p.get("downstream", [])),
            cost_sensitivity=str(p.get("cost_sensitivity", "")),
            high_frequency_indicators=list(p.get("high_frequency_indicators", [])),
        )

    # 1. 上下游去重合并 (子级在先，父级在后)
    up_merged: list[str] = []
    for item in list(child.get("upstream", [])) + list(parent.get("upstream", [])):
        if item and item not in up_merged:
            up_merged.append(str(item))

    down_merged: list[str] = []
    for item in list(child.get("downstream", [])) + list(parent.get("downstream", [])):
        if item and item not in down_merged:
            down_merged.append(str(item))

    # 2. 成本传导机制 (子级优先)
    cost_sens = str(child.get("cost_sensitivity") or parent.get("cost_sensitivity", ""))

    # 3. 高频微观指标 (子级专属指标置顶，父级指标补充在后)
    hf_merged: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for ind in list(child.get("high_frequency_indicators", [])) + list(
        parent.get("high_frequency_indicators", [])
    ):
        if isinstance(ind, dict):
            name = str(ind.get("name", ""))
            if name and name not in seen_names:
                seen_names.add(name)
                hf_merged.append(
                    {
                        "name": name,
                        "source": str(ind.get("source", "")),
                    }
                )

    return IndustryValueChainSnapshot(
        upstream=up_merged,
        downstream=down_merged,
        cost_sensitivity=cost_sens,
        high_frequency_indicators=hf_merged,
    )


def load_value_chain_map(
    industry_name: str,
    config_path: Path | str = "config/industry/value_chain",
    parent_name: str | None = None,
) -> IndustryValueChainSnapshot:
    """从本地 YAML 配置 (单文件或分级目录) 中读取行业上下游图谱并执行级联继承合并。"""
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        # 回退检查单文件路径
        alt_path = Path("config/industry/value_chain_map.yaml")
        if alt_path.exists():
            cfg_path = alt_path
        else:
            return IndustryValueChainSnapshot()

    try:
        all_industries = _collect_value_chain_dicts(cfg_path)
        if not all_industries:
            return IndustryValueChainSnapshot()

        # 查找子级行业专属配置
        child_dict: dict[str, Any] | None = None
        matched_child_key = None
        for name_key, details in all_industries.items():
            if name_key == industry_name or name_key in industry_name or industry_name in name_key:
                child_dict = details
                matched_child_key = name_key
                break

        # 查找父级行业基线配置
        inferred_parent = parent_name or (child_dict.get("parent_name") if child_dict else None)
        parent_dict: dict[str, Any] | None = None
        if inferred_parent:
            for name_key, details in all_industries.items():
                if (
                    name_key == inferred_parent
                    or name_key in inferred_parent
                    or inferred_parent in name_key
                ):
                    parent_dict = details
                    break

        if child_dict and parent_dict and matched_child_key != inferred_parent:
            return _merge_value_chain_snapshots(parent=parent_dict, child=child_dict)
        if child_dict:
            return _merge_value_chain_snapshots(parent=None, child=child_dict)
        if parent_dict:
            return _merge_value_chain_snapshots(parent=parent_dict, child=None)

    except Exception as exc:
        logger.warning(f"读取分级产业链图谱失败: {exc}")

    return IndustryValueChainSnapshot()
