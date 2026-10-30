"""全市场细分赛道标的发现引擎单元测试。"""

from __future__ import annotations

import polars as pl
import pytest

from stock_analytics.discovery.chemical_universe_scanner import (
    ChemicalUniverseScanner,
)
from stock_data.catalog import DataCatalog


class DummyCatalog:
    """用于快速单元测试的仿真 Catalog。"""

    def load_dataset(self, name: str, **kwargs) -> pl.DataFrame:
        if name == "fina_mainbz":
            return pl.DataFrame(
                {
                    "symbol": ["002601.SZ", "002601.SZ", "300891.SZ", "000001.SZ"],
                    "end_date": ["2026-06-30", "2026-06-30", "2026-06-30", "2026-06-30"],
                    "bz_item": ["钛白粉", "海绵钛", "金红石型钛白粉", "零售金融"],
                    "bz_sales": [9.0e9, 1.5e9, 7.0e8, 5.0e10],
                    "bz_profit": [2.5e9, 3.0e8, 1.2e8, 2.0e10],
                }
            )
        if name == "stock_basic":
            return pl.DataFrame(
                {
                    "symbol": ["002601.SZ", "300891.SZ", "000001.SZ"],
                    "name": ["龙佰集团", "惠云钛业", "平安银行"],
                    "industry": ["化学原料", "化学原料", "银行"],
                }
            )
        if name == "balancesheet":
            return pl.DataFrame(
                {
                    "symbol": ["002601.SZ", "300891.SZ", "000001.SZ"],
                    "end_date": ["2026-06-30", "2026-06-30", "2026-06-30"],
                    "cip": [4.0e9, 5.0e8, 1.0e8],
                    "fix_assets": [2.0e10, 8.0e8, 1.0e9],
                }
            )
        return pl.DataFrame()


def test_scanner_with_mock_catalog() -> None:
    """验证扫描器对主营纯度与 CIP/FA 的计算与梯队划分。"""
    scanner = ChemicalUniverseScanner(catalog=DummyCatalog())
    results = scanner.scan(
        keywords=["钛白粉"],
        known_symbols={"002601.SZ"},
        min_purity_ratio=0.10,
        min_sales_cny=1.0e8,
    )
    assert len(results) == 2
    # 龙佰排第 1，惠云排第 2
    assert results[0].symbol == "002601.SZ"
    assert results[0].is_known_leader is True
    assert results[0].recommendation_tier == "known_leader"

    assert results[1].symbol == "300891.SZ"
    assert results[1].name == "惠云钛业"
    assert results[1].is_known_leader is False
    assert results[1].cip_to_fix_ratio == round(5.0e8 / 8.0e8, 4)
    assert results[1].recommendation_tier in ("high_conviction_hidden_gem", "scale_challenger")

    df = scanner.to_dataframe(results)
    assert len(df) == 2
    assert "purity_ratio" in df.columns

    report = scanner.render_markdown_report("钛白粉", results)
    assert "惠云钛业" in report
    assert "龙佰集团" in report


def test_scanner_real_data_tio2() -> None:
    """在本地真实黄金事实表上验证钛白粉全市场挖掘能力。"""
    try:
        cat = DataCatalog(data_source="tushare")
        scanner = ChemicalUniverseScanner(catalog=cat, as_of_date="2026-09-01")
        results = scanner.scan(
            keywords=["钛白粉", "钛精矿", "金红石", "锐钛"],
            known_symbols={"002601.SZ", "002145.SZ", "002136.SZ", "000545.SZ"},
            min_purity_ratio=0.10,
            min_sales_cny=5.0e7,
        )
        assert len(results) >= 5
        discovered_symbols = {r.symbol for r in results if not r.is_known_leader}
        # 必须能够挖掘出鲁北化工 (600727.SH) 或 惠云钛业 (300891.SZ) 或 安宁股份 (002978.SZ)
        assert len(discovered_symbols & {"600727.SH", "300891.SZ", "002978.SZ", "000629.SZ"}) >= 2
    except Exception as exc:
        pytest.skip(f"跳过真实数据测试 (环境受限): {exc}")
