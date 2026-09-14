"""半导体产业 RAW 解析器。"""

from stock_data.fetcher.industry.semiconductor.parsers.adv_pkg_revenue import (
    append_tsmc_adv_pkg_revenue_raw_record,
    load_tsmc_adv_pkg_revenue_raw_csv,
    parse_tsmc_management_report_pdf,
)
from stock_data.fetcher.industry.semiconductor.parsers.channel_inventory import (
    parse_channel_inventory_companyfacts,
)
from stock_data.fetcher.industry.semiconductor.parsers.cowos_estimates import (
    load_cowos_capacity_estimates_raw_csv,
)
from stock_data.fetcher.industry.semiconductor.parsers.datatrack_memory import (
    parse_datatrack_memory_price_json,
)
from stock_data.fetcher.industry.semiconductor.parsers.foundry import (
    extract_smic_announcement_links,
    extract_smic_announcement_targets,
    extract_smic_financial_report_links,
    parse_smic_operating_pdf_bytes,
    parse_smic_operating_text,
)
from stock_data.fetcher.industry.semiconductor.parsers.inventory import (
    SecFiling,
    build_inventory_release_date_map,
    extract_sec_filings,
    load_inventory_raw_csv,
)
from stock_data.fetcher.industry.semiconductor.parsers.inventory_online import (
    parse_companyfacts_inventory,
    parse_sec_6k_inventory,
)
from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
    load_korea_memory_raw_csv,
    samsung_ds_ratio_minimum,
    validate_samsung_ds_ratio,
)
from stock_data.fetcher.industry.semiconductor.parsers.korea_memory_dart import (
    DART_REPORT_URL_PREFIX,
    DartReport,
    DartTocNode,
    SamsungInventoryFact,
    SamsungSegmentFact,
    SkHynixFinancialFact,
    build_dart_viewer_url,
    derive_quarterly_cumulative,
    parse_dart_search_results,
    parse_dart_toc_nodes,
    parse_report_quarter,
    parse_samsung_inventory_html,
    parse_samsung_segment_html,
    parse_skhynix_financial_html,
    select_dart_toc_node,
    select_latest_dart_revisions,
)
from stock_data.fetcher.industry.semiconductor.parsers.lead_time_raw import (
    aggregate_category_lead_times,
    extract_lead_time_release_date,
    is_valid_lead_time_weeks,
    parse_lead_time_string_to_weeks,
)
from stock_data.fetcher.industry.semiconductor.parsers.memory_price import (
    parse_trendforce_memory_price_html,
)
from stock_data.fetcher.industry.semiconductor.parsers.sales import (
    extract_sia_sales_article_links,
    extract_wsts_excel_download_url,
    load_sia_news_enrichments,
    parse_sia_china_and_date,
    parse_wsts_excel_file,
)
from stock_data.fetcher.industry.semiconductor.parsers.seaj import (
    SeajPdfParser,
    parse_seaj_historical_xls,
    parse_seaj_historical_xls_url,
    parse_seaj_pdf_text,
    parse_seaj_press_release_target,
    parse_seaj_release_calendar_pdf,
    parse_seaj_release_calendar_text,
)
from stock_data.fetcher.industry.semiconductor.parsers.semi import (
    extract_semi_press_release_links,
    parse_semi_article_text,
)
from stock_data.fetcher.industry.semiconductor.parsers.susquehanna import (
    archive_susquehanna_raw_snapshot,
    html_to_visible_text,
    parse_susquehanna_lead_time_article,
    parse_susquehanna_published_date,
    parse_susquehanna_rss_feed,
)
from stock_data.fetcher.industry.semiconductor.parsers.taiwan_memory import (
    parse_taiwan_memory_monthly_revenue_dict,
)
from stock_data.fetcher.industry.semiconductor.parsers.tsmc import (
    parse_tsmc_monthly_revenue_html,
)
from stock_data.fetcher.industry.semiconductor.parsers.tsmc_foundry import (
    extract_tsmc_quarterly_report_links,
    parse_tsmc_quarterly_report_pdf_bytes,
    parse_tsmc_quarterly_report_text,
)

__all__ = [
    "DART_REPORT_URL_PREFIX",
    "DartReport",
    "DartTocNode",
    "SamsungInventoryFact",
    "SamsungSegmentFact",
    "SeajPdfParser",
    "SecFiling",
    "SkHynixFinancialFact",
    "aggregate_category_lead_times",
    "append_tsmc_adv_pkg_revenue_raw_record",
    "archive_susquehanna_raw_snapshot",
    "build_dart_viewer_url",
    "build_inventory_release_date_map",
    "derive_quarterly_cumulative",
    "extract_lead_time_release_date",
    "extract_sec_filings",
    "extract_semi_press_release_links",
    "extract_sia_sales_article_links",
    "extract_smic_announcement_links",
    "extract_smic_announcement_targets",
    "extract_smic_financial_report_links",
    "extract_tsmc_quarterly_report_links",
    "extract_wsts_excel_download_url",
    "html_to_visible_text",
    "is_valid_lead_time_weeks",
    "load_cowos_capacity_estimates_raw_csv",
    "load_inventory_raw_csv",
    "load_korea_memory_raw_csv",
    "load_sia_news_enrichments",
    "load_tsmc_adv_pkg_revenue_raw_csv",
    "parse_channel_inventory_companyfacts",
    "parse_companyfacts_inventory",
    "parse_dart_search_results",
    "parse_dart_toc_nodes",
    "parse_datatrack_memory_price_json",
    "parse_lead_time_string_to_weeks",
    "parse_report_quarter",
    "parse_samsung_inventory_html",
    "parse_samsung_segment_html",
    "parse_seaj_historical_xls",
    "parse_seaj_historical_xls_url",
    "parse_seaj_pdf_text",
    "parse_seaj_press_release_target",
    "parse_seaj_release_calendar_pdf",
    "parse_seaj_release_calendar_text",
    "parse_sec_6k_inventory",
    "parse_semi_article_text",
    "parse_sia_china_and_date",
    "parse_skhynix_financial_html",
    "parse_smic_operating_pdf_bytes",
    "parse_smic_operating_text",
    "parse_susquehanna_lead_time_article",
    "parse_susquehanna_published_date",
    "parse_susquehanna_rss_feed",
    "parse_taiwan_memory_monthly_revenue_dict",
    "parse_trendforce_memory_price_html",
    "parse_tsmc_management_report_pdf",
    "parse_tsmc_monthly_revenue_html",
    "parse_tsmc_quarterly_report_pdf_bytes",
    "parse_tsmc_quarterly_report_text",
    "parse_wsts_excel_file",
    "samsung_ds_ratio_minimum",
    "select_dart_toc_node",
    "select_latest_dart_revisions",
    "validate_samsung_ds_ratio",
]
