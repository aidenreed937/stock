"""单元测试: 申万行业分类解析 (IndustryClassifier)
与 PB-ROE 横截面残差分析 (IndustryPBROEAnalyzer)。
"""

from datetime import date
from unittest.mock import MagicMock

import polars as pl

from stock_analytics.pipelines.industry_structure.classifier import IndustryClassifier
from stock_analytics.pipelines.industry_structure.pb_roe import IndustryPBROEAnalyzer
from stock_data.catalog import DataCatalog


def test_industry_classifier_l1_and_name_map() -> None:
    mock_catalog = MagicMock(spec=DataCatalog)
    mock_df = pl.DataFrame(
        {
            "index_code": ["801010.SI", "801020.SI", "801030.SI"],
            "industry_name": ["农林牧渔", "采掘", "化工"],
            "level": ["L1", "L1", "L1"],
            "src": ["SW2021", "SW2021", "SW2021"],
        }
    )
    mock_catalog.load_dataset.return_value = mock_df

    classifier = IndustryClassifier(catalog=mock_catalog)
    codes = classifier.get_l1_codes("SW2021")
    assert "801010.SI" in codes
    assert len(codes) == 3

    name_map = classifier.get_name_map("SW2021")
    assert name_map.get("801010.SI") == "农林牧渔"
    assert name_map.get("801010") == "农林牧渔"

    resolved = classifier.resolve_name("801010.SI")
    assert resolved == "农林牧渔"
    assert classifier.resolve_name("801010") == "农林牧渔"
    assert classifier.resolve_name("UNKNOWN") == "UNKNOWN"


def test_industry_classifier_empty() -> None:
    mock_catalog = MagicMock(spec=DataCatalog)
    mock_catalog.load_dataset.side_effect = Exception("No dataset")

    classifier = IndustryClassifier(catalog=mock_catalog)
    assert classifier.get_l1_codes() == frozenset()
    assert classifier.get_name_map() == {}
    assert classifier.resolve_name("801010") == "801010"


def test_industry_pb_roe_analyzer() -> None:
    mock_catalog = MagicMock(spec=DataCatalog)
    classify_df = pl.DataFrame(
        {
            "index_code": [f"8010{i:02d}.SI" for i in range(1, 11)],
            "industry_name": [f"行业{i}" for i in range(1, 11)],
            "level": ["L1"] * 10,
            "src": ["SW2021"] * 10,
        }
    )
    val_df = pl.DataFrame(
        {
            "symbol": [f"8010{i:02d}.SI" for i in range(1, 11)],
            "trade_date": [date(2026, 8, 14)] * 10,
            "pb.ew": [1.0 + i * 0.2 for i in range(10)],
            "roe.ttm": [5.0 + i * 1.5 for i in range(10)],
        }
    )

    def mock_load(dataset: str, **kwargs: object) -> pl.DataFrame:
        if dataset == "index_classify":
            return classify_df
        if dataset == "sw_2021_fundamental":
            return val_df
        return pl.DataFrame()

    mock_catalog.load_dataset.side_effect = mock_load

    analyzer = IndustryPBROEAnalyzer(catalog=mock_catalog)
    result = analyzer.analyze_cross_section(target_date=date(2026, 8, 14), val_df=val_df)

    assert result is not None
    assert result.trade_date == date(2026, 8, 14)
    assert len(result.industries) == 10
    assert result.r_squared >= 0.0
