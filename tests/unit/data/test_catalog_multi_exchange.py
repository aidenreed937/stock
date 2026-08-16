"""DataCatalog 多交易所复合主键与多维去重回归测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock.data.catalog import DataCatalog


def test_load_dataset_multi_exchange_margin_preservation(tmp_path: Path) -> None:
    """验证包含 exchange_id 的多所数据集（如 margin）在 load_dataset 时不会被误杀。"""
    margin_dir = tmp_path / "tushare/market=CN/margin"
    margin_dir.mkdir(parents=True, exist_ok=True)
    file_path = margin_dir / "data.parquet"

    # 同一交易日、同一个 symbol='margin'，但分别属于 SSE, SZSE, BSE 三个不同交易所
    df = pl.DataFrame(
        {
            "market": ["CN", "CN", "CN"],
            "symbol": ["margin", "margin", "margin"],
            "trade_date": [date(2026, 8, 12), date(2026, 8, 12), date(2026, 8, 12)],
            "exchange_id": ["SSE", "SZSE", "BSE"],
            "rzye": [13552.0, 12837.0, 84.0],
            "rqye": [165.0, 91.0, 0.04],
            "rzrqye": [13717.0, 12928.0, 84.04],
            "data_source": ["tushare", "tushare", "tushare"],
            "source_endpoint": ["margin", "margin", "margin"],
        }
    )
    df.write_parquet(file_path)

    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    loaded = catalog.load_dataset("margin")

    # 关键断言：必须完整保留 3 家交易所的数据，严禁被误杀至 1 家
    assert len(loaded) == 3
    assert set(loaded["exchange_id"].to_list()) == {"SSE", "SZSE", "BSE"}
    assert float(loaded["rzye"].sum()) == pytest.approx(26473.0, 0.1)


def test_load_dataset_dedup_true_duplicates(tmp_path: Path) -> None:
    """验证真正的同交易所重复批次数据能被正确去重并保留最新一行。"""
    margin_dir = tmp_path / "tushare/market=CN/margin"
    margin_dir.mkdir(parents=True, exist_ok=True)
    file_path = margin_dir / "data.parquet"

    # 2022 年北交所尚未纳入两融汇总口径，同一日期的 SSE 有两条记录。
    df = pl.DataFrame(
        {
            "market": ["CN", "CN", "CN"],
            "symbol": ["margin", "margin", "margin"],
            "trade_date": [date(2022, 8, 12), date(2022, 8, 12), date(2022, 8, 12)],
            "exchange_id": ["SSE", "SSE", "SZSE"],
            "rzye": [13000.0, 13552.0, 12837.0],
            "data_source": ["tushare", "tushare", "tushare"],
            "source_endpoint": ["margin", "margin", "margin"],
        }
    )
    df.write_parquet(file_path)

    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    loaded = catalog.load_dataset("margin")

    # 应该去重为 2 行（1 条 SSE 最新 + 1 条 SZSE），且该日覆盖完整。
    assert len(loaded) == 2
    sse_row = loaded.filter(pl.col("exchange_id") == "SSE")
    assert len(sse_row) == 1
    assert sse_row["rzye"][0] == 13552.0


def test_load_dataset_excludes_incomplete_margin_date(tmp_path: Path) -> None:
    margin_dir = tmp_path / "tushare/market=CN/margin"
    margin_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14), date(2026, 8, 14)],
            "exchange_id": ["SSE", "SZSE"],
            "rzye": [100.0, 200.0],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["margin", "margin"],
        }
    ).write_parquet(margin_dir / "data.parquet")

    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)

    assert catalog.load_dataset("margin").is_empty()


import pytest
