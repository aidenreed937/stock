"""数据集物理路径选择测试。"""

from pathlib import Path

from stock_data.storage.dataset_paths import matching_dataset_files


def test_matching_dataset_files_scopes_provider_before_canonical_preference(tmp_path: Path) -> None:
    legacy = tmp_path / "tushare" / "market=CN" / "index_daily" / "data.parquet"
    other_source = tmp_path / "lixinger" / "market=CN" / "index_daily_bar" / "data.parquet"
    legacy.parent.mkdir(parents=True)
    other_source.parent.mkdir(parents=True)
    legacy.touch()
    other_source.touch()

    files = matching_dataset_files(
        tmp_path,
        {"index_daily", "index_daily_bar"},
        "index_daily_bar",
        data_source="tushare",
    )

    assert files == [legacy]
