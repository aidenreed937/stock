"""本地派生数据集契约。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DerivedDatasetSpec:
    """仅由本地事实构建、不对应上游 API 的数据集契约。"""

    data_source: str
    dataset: str
    primary_keys: tuple[str, ...]
    date_columns: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()
    partitioned: bool = False


CURATED_DERIVED_DATASETS: dict[tuple[str, str], DerivedDatasetSpec] = {
    ("tushare", "index_member_versioned"): DerivedDatasetSpec(
        data_source="tushare",
        dataset="index_member_versioned",
        primary_keys=("src", "index_code", "con_code", "in_date", "out_date"),
        required_columns=(
            "src",
            "src_status",
            "index_code",
            "con_code",
            "in_date",
            "out_date",
        ),
    ),
    ("derived", "sw_2021_industry_dimension_golden"): DerivedDatasetSpec(
        data_source="derived",
        dataset="sw_2021_industry_dimension_golden",
        primary_keys=("classification", "industry_code", "level"),
        required_columns=(
            "classification",
            "industry_code",
            "level",
            "src",
            "tushare_present",
            "lixinger_present",
            "mapping_status",
        ),
    ),
    ("derived", "sw_2021_industry_member_golden"): DerivedDatasetSpec(
        data_source="derived",
        dataset="sw_2021_industry_member_golden",
        primary_keys=(
            "src",
            "symbol",
            "industry_code",
            "level",
            "valid_from",
            "valid_to",
            "snapshot_date",
        ),
        date_columns=("valid_from", "valid_to", "snapshot_date"),
        required_columns=(
            "classification",
            "symbol",
            "stock_code",
            "industry_code",
            "level",
            "src",
            "canonical_source",
            "source_status",
            "is_canonical",
            "conflict_flag",
        ),
    ),
}
CURATED_DERIVED_NON_PARTITIONED_DATASETS: frozenset[str] = frozenset(
    spec.dataset for spec in CURATED_DERIVED_DATASETS.values()
)


def resolve_derived_dataset(data_source: str, dataset: str) -> DerivedDatasetSpec | None:
    """返回本地派生数据集契约；未知数据集返回 None。"""
    return CURATED_DERIVED_DATASETS.get((data_source.lower(), dataset))


__all__ = [
    "CURATED_DERIVED_DATASETS",
    "CURATED_DERIVED_NON_PARTITIONED_DATASETS",
    "DerivedDatasetSpec",
    "resolve_derived_dataset",
]
