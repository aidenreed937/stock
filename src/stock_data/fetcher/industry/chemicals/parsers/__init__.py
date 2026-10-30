"""化工产业源端解析器。"""

from stock_data.fetcher.industry.chemicals.parsers.commodity_index import (
    CommodityIndexRow,
    parse_100ppi_ptrade_html,
)
from stock_data.fetcher.industry.chemicals.parsers.monthly_survey import (
    has_monthly_metrics,
    parse_monthly_survey_record,
)
from stock_data.fetcher.industry.chemicals.parsers.nbs_production_materials import (
    DEFAULT_NBS_COMMODITY_MAPPING,
    extract_nbs_commodity_prices,
    parse_nbs_report_metadata,
    save_nbs_prices_to_survey_csv,
)
from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser
from stock_data.fetcher.industry.chemicals.parsers.spot_price import (
    COMMODITY_CATALOG,
    parse_100ppi_chart_text,
    previous_weekday,
    unpack_100ppi_packer,
    validate_spot_extraction,
)

__all__ = [
    "CHEMICALS_CSV_FIELDNAMES",
    "COMMODITY_CATALOG",
    "DEFAULT_NBS_COMMODITY_MAPPING",
    "CommodityIndexRow",
    "ResearchReportParser",
    "extract_nbs_commodity_prices",
    "has_monthly_metrics",
    "load_chemicals_raw_csv",
    "parse_100ppi_chart_text",
    "parse_100ppi_ptrade_html",
    "parse_monthly_survey_record",
    "parse_nbs_report_metadata",
    "previous_weekday",
    "save_chemicals_raw_csv",
    "save_nbs_prices_to_survey_csv",
    "unpack_100ppi_packer",
    "validate_spot_extraction",
]


def __getattr__(name: str) -> object:
    if name in {"CHEMICALS_CSV_FIELDNAMES", "load_chemicals_raw_csv", "save_chemicals_raw_csv"}:
        from stock_data.fetcher.industry.chemicals.parsers.raw_csv import (
            CHEMICALS_CSV_FIELDNAMES,
            load_chemicals_raw_csv,
            save_chemicals_raw_csv,
        )

        return {
            "CHEMICALS_CSV_FIELDNAMES": CHEMICALS_CSV_FIELDNAMES,
            "load_chemicals_raw_csv": load_chemicals_raw_csv,
            "save_chemicals_raw_csv": save_chemicals_raw_csv,
        }[name]
    raise AttributeError(name)
