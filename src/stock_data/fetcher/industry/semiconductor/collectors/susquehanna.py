"""Susquehanna 半导体交期公开报道在线采集器。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.contracts import IndustryCollectionResult
from stock_data.fetcher.industry.semiconductor.collectors.lead_time import (
    DEFAULT_CONFIG_PATH,
    load_chip_lead_time_config,
)
from stock_data.fetcher.industry.semiconductor.collectors.susquehanna_helpers import (
    _target_months,
)
from stock_data.fetcher.industry.semiconductor.collectors.susquehanna_online import (
    DEFAULT_LOOKBACK_MONTHS,
    DEFAULT_MAX_ARTICLE_CHARS,
    DEFAULT_MAX_FEED_ITEMS,
    DEFAULT_SUSQUEHANNA_DOMAINS,
    DEFAULT_SUSQUEHANNA_RSS_URL,
    DEFAULT_TIMEOUT_SECONDS,
    collect_susquehanna_online,
)
from stock_data.fetcher.industry.semiconductor.models import ChipLeadTimeRecord
from stock_data.fetcher.industry.semiconductor.parsers.lead_time_raw import (
    load_lead_time_raw_records,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths


class SusquehannaLeadTimeCollector:
    """通过公开报道发现并增量归档 Susquehanna 月度交期数据。"""

    def __init__(
        self,
        raw_dir: Path | str,
        config_path: Path | str = DEFAULT_CONFIG_PATH,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.lead_time_raw_dir = self.paths.lead_time_dir
        self.config = load_chip_lead_time_config(config_path)
        online_config = self.config.get("susquehanna_online", {})
        configured_urls = online_config.get("rss_urls", (DEFAULT_SUSQUEHANNA_RSS_URL,))
        self.rss_urls = _as_string_tuple(configured_urls)
        configured_domains = online_config.get("source_domains", DEFAULT_SUSQUEHANNA_DOMAINS)
        self.source_domains = frozenset(
            str(domain).lower().removeprefix("www.") for domain in configured_domains
        )
        self.lookback_months = int(online_config.get("lookback_months", DEFAULT_LOOKBACK_MONTHS))
        self.max_feed_items = int(online_config.get("max_feed_items", DEFAULT_MAX_FEED_ITEMS))
        self.max_article_chars = int(
            online_config.get("max_article_chars", DEFAULT_MAX_ARTICLE_CHARS)
        )
        self.infer_report_month = bool(online_config.get("infer_report_month", False))
        self.allow_rss_excerpt = bool(online_config.get("allow_rss_excerpt", True))
        self.timeout = int(online_config.get("timeout_seconds", timeout))

    def collect(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
    ) -> IndustryCollectionResult:
        """按请求月份在线增量采集，失败时只回放本地 RAW。"""
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError(f"Susquehanna 交期日期范围无效: {start_date} > {end_date}")

        local_records = self._load_records()
        target_months = _target_months(start_date, end_date)
        existing_susquehanna_months = {
            record.report_month
            for record in local_records
            if "susquehanna" in record.source.lower()
        }
        fetched, errors = collect_susquehanna_online(
            raw_root=self.paths.semiconductor_dir,
            rss_urls=self.rss_urls,
            source_domains=self.source_domains,
            target_months=target_months,
            existing_months=existing_susquehanna_months,
            force=force,
            thresholds=self.config.get("thresholds", {}),
            timeout=self.timeout,
            lookback_months=self.lookback_months,
            max_feed_items=self.max_feed_items,
            max_article_chars=self.max_article_chars,
            infer_report_month=self.infer_report_month,
            allow_rss_excerpt=self.allow_rss_excerpt,
        )
        records = self._load_records()
        covered_susquehanna = {
            record.report_month for record in records if "susquehanna" in record.source.lower()
        }
        missing = tuple(sorted(target_months - covered_susquehanna)) if target_months else ()
        if fetched:
            return IndustryCollectionResult(
                records,
                status="PARTIAL" if missing else "SUCCESS",
                fetched_periods=fetched,
                cached_periods=tuple(sorted(existing_susquehanna_months & covered_susquehanna)),
                missing_periods=missing,
                errors=errors,
                updated=True,
            )
        if records:
            return IndustryCollectionResult(
                records,
                status="PARTIAL" if missing else "NO_CHANGE",
                cached_periods=tuple(sorted(existing_susquehanna_months & covered_susquehanna)),
                missing_periods=missing,
                errors=errors,
            )
        return IndustryCollectionResult(
            [],
            status="EMPTY",
            missing_periods=tuple(sorted(target_months)) if target_months else (),
            errors=errors,
        )

    def _load_records(self) -> list[ChipLeadTimeRecord]:
        return load_lead_time_raw_records(
            self.lead_time_raw_dir,
            self.config.get("thresholds", {}),
            categories=self.config.get("categories", {}),
        )


def _as_string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple | set):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


__all__ = ["SusquehannaLeadTimeCollector"]
