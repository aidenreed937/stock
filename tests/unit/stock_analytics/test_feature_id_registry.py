"""ID 语义登记表（feature_id_registry.yaml）一致性测试。"""

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATH = _REPO_ROOT / "config" / "analytics" / "feature_id_registry.yaml"


def _load_registry() -> dict:
    with _REGISTRY_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_registry_entries_have_no_duplicate_id_entity_unit_triples() -> None:
    """同一 (id, entity_type, unit) 三元组不得重复登记。"""
    registry = _load_registry()
    entries = registry["entries"]
    assert isinstance(entries, list) and entries

    triples = [(e["id"], e["entity_type"], e["unit"]) for e in entries]
    assert len(triples) == len(set(triples)), f"重复三元组: {triples}"


def test_registry_covers_conflicting_id_families() -> None:
    """登记表须覆盖计划 1.3 节的全部存量冲突 ID 家族。"""
    registry = _load_registry()
    ids = {(e["id"], e["entity_type"]) for e in registry["entries"]}
    required_families = {
        ("return_20d", "STOCK"),
        ("return_20d", "MARKET"),
        ("return_20d", "INDUSTRY"),
        ("return_60d", "STOCK"),
        ("rsi_14d", "STOCK"),
        ("rsi_14d", "MARKET"),
        ("ma_bias_20d", "STOCK"),
        ("ma_bias_20d", "MARKET"),
        ("realized_vol_20d", "STOCK"),
        ("realized_volatility_20d", "STOCK"),
        ("dist_to_high_250d", "STOCK"),
        ("distance_to_252d_high", "STOCK"),
        ("rel_return_20d", "STOCK"),
        ("rel_return_60d", "STOCK"),
    }
    missing = required_families - ids
    assert missing == set(), f"登记表缺失冲突条目: {sorted(missing)}"


def test_naming_rules_are_documented() -> None:
    """登记表须随附命名规范说明。"""
    registry = _load_registry()
    rules = registry.get("naming_rules")
    assert isinstance(rules, list) and len(rules) >= 3
