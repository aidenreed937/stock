"""数据运行时目录上下文测试。"""

from pathlib import Path

from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext
from stock_data.core.settings import DataSettings


def test_runtime_context_from_root_uses_standard_tiers(tmp_path: Path) -> None:
    context = DataRuntimeContext.from_root(tmp_path)

    assert context.data_root == tmp_path
    assert context.raw_root == tmp_path / "raw"
    assert context.curated_root == tmp_path / "curated"
    assert context.cache_root == tmp_path / "cache"


def test_settings_root_is_shared_by_catalog_and_runtime(tmp_path: Path) -> None:
    settings = DataSettings(data_root=tmp_path)
    context = settings.runtime_context
    context.ensure_directories()

    catalog = DataCatalog(data_source="tushare", runtime=context)

    assert settings.curated_data_dir == tmp_path / "curated"
    assert catalog.storage_dir == tmp_path / "curated"


def test_settings_legacy_directory_override_remains_runtime_compatible(tmp_path: Path) -> None:
    settings = DataSettings()
    settings.curated_data_dir = tmp_path / "curated"

    assert settings.runtime_context.curated_root == tmp_path / "curated"
