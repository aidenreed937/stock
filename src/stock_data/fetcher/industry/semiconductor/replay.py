"""半导体产业 RAW → Curated 离线重放计划（不触发网络采集）。

职责边界：把"半导体各端点/派生表如何从 RAW 快照离线重建"收敛到半导体包内，
不再与其他产业混在同一份硬编码计划里（脚本侧通过
``**build_semiconductor_replay_plan()`` 合并）。

**路径权威来源（禁止硬编码目录字符串）**：

- 全部在重放计划内的表都是已注册端点 —— 取
  :mod:`stock_data.fetcher.industry.semiconductor.registry` 中 ``ENDPOINT_SPECS`` 的
  ``target_file``（Curated 相对路径，已含 5 大产研分类子目录）与 ``raw_subdir``（RAW 子目录）。

（历史：曾有一条非端点派生表 ``semiconductor_china_series``，因其与主表
``semiconductor_sales.china_yoy_growth``/``china_mom_growth`` 逐值等价且无独立消费方，
已于 2026-09-10 退役。）

注意：``IndustryEndpointSpec`` **不承载 primary_keys**（主键封装在 runner 闭包内），
故各指标主键在本模块显式声明，与 ``registry.py`` 注册时的取值保持一致。
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.replay_support import replay_entry

__all__ = ["build_semiconductor_replay_plan"]


# ---------------------------------------------------------------------------
# Loader：从各类 RAW 快照离线重建（保持函数内延迟导入，避免模块加载期重依赖）
# ---------------------------------------------------------------------------


def _load_wsts_semiconductor(raw_root: Path) -> list[Any]:
    """从 WSTS Historical Billings Excel 缓存解析全球半导体月度销售额底表。"""
    from stock_data.fetcher.industry.semiconductor.lineage import (
        raw_content_sha256,
        raw_snapshot_path_value,
    )
    from stock_data.fetcher.industry.semiconductor.parsers import (
        load_sia_news_enrichments,
        parse_wsts_excel_file,
    )
    from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

    sia_dir = SemiconductorRawPaths(raw_root).sia_dir
    excel_files = sorted(sia_dir.glob("WSTS-Historical-Billings-Report-*.xlsx"))
    if not excel_files:
        return []
    excel_path = excel_files[-1]
    content_hash = raw_content_sha256(excel_path.read_bytes())
    snapshot_ref = raw_snapshot_path_value(excel_path, raw_root)
    enrichments = load_sia_news_enrichments(sia_dir)
    release_dates = {
        month: value["release_date"]
        for month, value in enrichments.items()
        if value.get("release_date") is not None
    }
    records = []
    for record in parse_wsts_excel_file(excel_path, release_dates=release_dates):
        enrich = enrichments.get(record.report_month)
        updates: dict[str, Any] = {
            "raw_content_sha256": content_hash,
            "raw_snapshot_path": snapshot_ref,
            "release_date": record.release_date,
            "yoy_growth": None,
            "mom_growth": None,
        }
        if enrich:
            updates.update(
                {
                    "china_sales_usd": enrich.get("china_sales_usd"),
                    "china_yoy_growth": enrich.get("china_yoy_growth"),
                    "china_mom_growth": enrich.get("china_mom_growth"),
                    "china_sales_raw": enrich.get("china_sales_raw"),
                    "china_yoy_growth_raw": enrich.get("china_yoy_growth_raw"),
                    "china_mom_growth_raw": enrich.get("china_mom_growth_raw"),
                    "release_date": enrich.get("release_date") or updates["release_date"],
                }
            )
        records.append(replace(record, **updates))
    return records


def _load_tsmc_lead_from_raw_snapshot(raw_root: Path) -> list[Any]:
    """从归档的 TSMC 英文投资者年度月度营收 HTML 快照重放台积电月度营收。

    采集器已把各年度原始 HTML 以 Gzip 归档到 {raw_root}/tsmc/ 仅供对账校验；此处离线
    重放这些快照，不回填 line 数据 (2-Tier ETL RAW 曲线表始终由在线采集重建)。
    """
    from stock_data.fetcher.industry.common import (
        get_month_end_date,
        now_utc_iso,
        parse_month_string,
    )
    from stock_data.fetcher.industry.semiconductor.lineage import (
        raw_content_sha256,
        raw_snapshot_content_bytes,
        raw_snapshot_path_value,
    )
    from stock_data.fetcher.industry.semiconductor.models import SemiconductorLeadRecord
    from stock_data.fetcher.industry.semiconductor.parsers import (
        parse_tsmc_monthly_revenue_html,
    )
    from stock_data.fetcher.industry.semiconductor.paths import (
        TSMC_MONTHLY_HTML_FILENAME,
        SemiconductorRawPaths,
    )

    html_dir = SemiconductorRawPaths(raw_root).tsmc_monthly_html_dir
    if not html_dir.exists():
        return []

    records: list[SemiconductorLeadRecord] = []
    for snapshot in sorted(html_dir.glob(TSMC_MONTHLY_HTML_FILENAME.format(year="*"))):
        match = re.search(r"(\d{4})\.html\.gz$", snapshot.name)
        if match is None:
            continue
        year = int(match.group(1))
        content_bytes = raw_snapshot_content_bytes(snapshot)
        html_text = content_bytes.decode("utf-8", errors="ignore")
        content_hash = raw_content_sha256(content_bytes)
        snapshot_ref = raw_snapshot_path_value(snapshot, raw_root)
        for row in parse_tsmc_monthly_revenue_html(html_text, year=year):
            report_month = str(row["report_month"])
            yr, mo = parse_month_string(report_month)
            ntd = float(row["tsmc_revenue_ntd_million"])
            yoy = row["tsmc_revenue_yoy"]
            records.append(
                SemiconductorLeadRecord(
                    report_month=report_month,
                    trade_date=get_month_end_date(yr, mo),
                    tsmc_revenue_ntd_million=ntd,
                    tsmc_revenue_yoy=float(yoy) if yoy is not None else None,
                    tsmc_revenue_mom=None,
                    unit="million_ntd/usd",
                    source="TSMC",
                    source_url=f"https://investor.tsmc.com/english/monthly-revenue/{year}",
                    release_date=_tsmc_next_month_release_date(report_month),
                    data_status="actual",
                    collected_at=now_utc_iso(),
                    raw_content_sha256=content_hash,
                    raw_snapshot_path=snapshot_ref,
                    tsmc_month_raw=str(row.get("month_raw") or ""),
                    tsmc_revenue_raw=str(row.get("net_revenue_raw") or ""),
                    tsmc_revenue_yoy_raw=str(row.get("yoy_change_raw") or ""),
                )
            )

    if not records:
        return []
    records.sort(key=lambda r: r.report_month)
    return records


def _tsmc_next_month_release_date(report_month: str) -> date:
    """台积电在每月 10 日前后披露上月营收，故 release_date 采用下月 10 日。"""
    from stock_data.fetcher.industry.common import parse_month_string

    year, month = parse_month_string(report_month)
    next_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1
    return date(next_year, next_month, 10)


def _load_seaj_equipment_from_raw_snapshot(raw_root: Path) -> list[Any]:
    """从 SEAJ 官方历史 Excel/PDF 快照重放月度设备出货。"""
    from stock_data.fetcher.industry.common import (
        get_month_end_date,
        now_utc_iso,
        parse_month_string,
    )
    from stock_data.fetcher.industry.semiconductor.collectors.seaj import (
        SEAJ_HISTORICAL_XLS_FILENAME,
        SEAJ_INDEX_FILENAME,
        SEAJ_LATEST_PDF_FILENAME,
        SEAJ_RELEASE_DATES_FILENAME,
        SEAJ_STATISTICS_URL,
    )
    from stock_data.fetcher.industry.semiconductor.lineage import (
        raw_content_sha256,
        raw_snapshot_content_bytes,
        raw_snapshot_path_value,
    )
    from stock_data.fetcher.industry.semiconductor.models import SemiconductorEquipmentRecord
    from stock_data.fetcher.industry.semiconductor.parsers import (
        SeajPdfParser,
        parse_seaj_historical_xls,
        parse_seaj_historical_xls_url,
        parse_seaj_press_release_target,
        parse_seaj_release_calendar_pdf,
    )
    from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

    snapshot_dir = SemiconductorRawPaths(raw_root).seaj_dir
    html_file = snapshot_dir / SEAJ_INDEX_FILENAME
    if not html_file.exists():
        html_file = snapshot_dir / "seaj_statistics_index.html"
    target = None
    historical_url = SEAJ_STATISTICS_URL
    if html_file.exists():
        html_text = raw_snapshot_content_bytes(html_file).decode("shift_jis", errors="ignore")
        target = parse_seaj_press_release_target(html_text)
        historical_url = parse_seaj_historical_xls_url(html_text) or historical_url

    release_dates: dict[str, date] = {}
    release_dates_file = snapshot_dir / SEAJ_RELEASE_DATES_FILENAME
    if release_dates_file.exists():
        release_dates = parse_seaj_release_calendar_pdf(
            raw_snapshot_content_bytes(release_dates_file)
        )

    records: dict[str, SemiconductorEquipmentRecord] = {}
    xls_file = snapshot_dir / SEAJ_HISTORICAL_XLS_FILENAME
    if xls_file.exists():
        xls_bytes = raw_snapshot_content_bytes(xls_file)
        xls_hash = raw_content_sha256(xls_bytes)
        xls_ref = raw_snapshot_path_value(xls_file, raw_root)
        for item in parse_seaj_historical_xls(
            xls_bytes,
            start_year=2015,
            end_year=date.today().year,
        ):
            report_month = str(item["report_month"])
            year, month = parse_month_string(report_month)
            billings_raw = item.get("sales_3mma_raw")
            yoy_raw = item.get("yoy_growth_3mma_raw")
            release_date = release_dates.get(report_month) or _seaj_next_month_release_date(
                report_month
            )
            records[report_month] = SemiconductorEquipmentRecord(
                report_month=report_month,
                trade_date=get_month_end_date(year, month),
                billings_3mma_jpy=float(item["billings_3mma_jpy"]),
                yoy_growth_3mma=item.get("yoy_growth_3mma"),
                unit="billion_jpy",
                source="SEAJ",
                source_url=historical_url,
                release_date=release_date,
                data_status="actual",
                collected_at=now_utc_iso(),
                raw_content_sha256=xls_hash,
                raw_snapshot_path=xls_ref,
                billings_jpy_raw=billings_raw,
                yoy_reported=yoy_raw,
                billings_raw=billings_raw,
                yoy_raw=yoy_raw,
            )

    pdf_file = snapshot_dir / SEAJ_LATEST_PDF_FILENAME
    if pdf_file.exists():
        pdf_bytes = raw_snapshot_content_bytes(pdf_file)
        pdf_hash = raw_content_sha256(pdf_bytes)
        pdf_ref = raw_snapshot_path_value(pdf_file, raw_root)
        listing_release_date = target.release_date if target is not None else None
        pdf_source_url = (
            target.pdf_url if target is not None and target.pdf_url else SEAJ_STATISTICS_URL
        )
        for item in SeajPdfParser().parse_pdf_bytes(
            pdf_bytes,
            release_date=listing_release_date,
            release_dates=release_dates,
        ):
            report_month = str(item["report_month"])
            year, month = parse_month_string(report_month)
            billings_raw = item.get("sales_3mma_raw") or item.get("billings_jpy_raw")
            yoy_raw = item.get("yoy_growth_3mma_raw") or item.get("yoy_reported")
            mom_raw = item.get("mom_growth_3mma_raw") or item.get("mom_reported")
            records[report_month] = SemiconductorEquipmentRecord(
                report_month=report_month,
                trade_date=get_month_end_date(year, month),
                billings_3mma_jpy=float(item["billings_3mma_jpy"]),
                yoy_growth_3mma=item.get("yoy_growth_3mma"),
                mom_growth_3mma=item.get("mom_growth_3mma"),
                unit="billion_jpy",
                source="SEAJ",
                source_url=pdf_source_url,
                release_date=item.get("release_date")
                or release_dates.get(report_month)
                or _seaj_next_month_release_date(report_month),
                data_status="actual",
                collected_at=now_utc_iso(),
                raw_content_sha256=pdf_hash,
                raw_snapshot_path=pdf_ref,
                billings_jpy_raw=billings_raw,
                yoy_reported=yoy_raw,
                mom_reported=mom_raw,
                billings_raw=billings_raw,
                yoy_raw=yoy_raw,
                mom_raw=mom_raw,
            )
    return sorted(records.values(), key=lambda record: record.report_month)


def _seaj_next_month_release_date(report_month: str) -> date:
    """SEAJ 历史表缺少逐月发布日期时使用次月 25 日代理。"""
    from stock_data.fetcher.industry.common import parse_month_string

    year, month = parse_month_string(report_month)
    if month == 12:
        return date(year + 1, 1, 25)
    return date(year, month + 1, 25)


def _load_semi_equipment_from_raw_snapshots(raw_root: Path) -> pl.DataFrame:
    """从 SEMI/PR Newswire 新闻稿 HTML 源端快照重放季度设备出货。"""
    from stock_data.fetcher.industry.semiconductor.collectors.semi_crawler import (
        SemiEquipmentCrawler,
    )
    from stock_data.fetcher.industry.semiconductor.transforms import build_semi_equipment_raw_frame

    return build_semi_equipment_raw_frame(
        SemiEquipmentCrawler(raw_dir=raw_root).replay_cached_snapshots()
    )


def _load_foundry_from_raw_snapshots(raw_root: Path) -> pl.DataFrame:
    """从晶圆代工官方 HTML/PDF 快照重放不含代理计算与相态的 RAW 表。"""
    from stock_data.fetcher.industry.semiconductor.collectors.foundry_crawler import (
        FoundryUtilizationCrawler,
    )
    from stock_data.fetcher.industry.semiconductor.transforms import build_foundry_raw_frame

    crawler = FoundryUtilizationCrawler(raw_dir=raw_root)
    return build_foundry_raw_frame(crawler.replay_cached_snapshots())


def _load_inventory_from_raw(raw_root: Path) -> pl.DataFrame:
    """从 IDM 财报 RAW CSV 重放不含 DOI 与综合统计的 RAW 表。"""
    from stock_data.fetcher.industry.semiconductor.collectors.inventory import (
        SemiconductorInventoryCollector,
    )

    return SemiconductorInventoryCollector(raw_dir=raw_root).load_from_raw_snapshots()


# ---------------------------------------------------------------------------
# 计划构建
# ---------------------------------------------------------------------------


def build_semiconductor_replay_plan() -> dict[str, dict[str, Any]]:
    """构建半导体产业的离线重放计划（metric -> 执行计划）。

    计划字段：``loader`` / ``to_frame`` / ``raw_to_frame`` / ``curated``
    （Curated 相对 ``data/curated/industry`` 的路径）/ ``raw_subdir``
    （RAW 相对 ``data/raw/industry`` 的子目录）/ ``primary_keys``。
    """
    from stock_data.fetcher.industry.semiconductor import ChipLeadTimeCollector
    from stock_data.fetcher.industry.semiconductor.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.semiconductor.transforms import (
        build_foundry_utilization_frame,
        build_inventory_days_frame,
        build_inventory_raw_frame,
        build_semi_equipment_curated_frame,
        records_to_chip_lead_time_frame,
        records_to_raw_chip_lead_time_frame,
        records_to_raw_semiconductor_equipment_frame,
        records_to_raw_semiconductor_frame,
        records_to_raw_semiconductor_lead_frame,
        records_to_semiconductor_equipment_frame,
        records_to_semiconductor_frame,
        records_to_semiconductor_lead_frame,
    )

    # 端点路径统一由注册表推导（共享 replay_entry 工厂，见 industry/replay_support.py）
    entry = partial(replay_entry, specs=ENDPOINT_SPECS)

    plan: dict[str, dict[str, Any]] = {
        "semiconductor_sales": entry(
            "semiconductor_sales",
            loader=_load_wsts_semiconductor,
            to_frame=records_to_semiconductor_frame,
            raw_to_frame=records_to_raw_semiconductor_frame,
            primary_keys=None,
        ),
        "semiconductor_lead": entry(
            "semiconductor_lead",
            loader=_load_tsmc_lead_from_raw_snapshot,
            to_frame=records_to_semiconductor_lead_frame,
            raw_to_frame=records_to_raw_semiconductor_lead_frame,
            primary_keys=["report_month"],
        ),
        "chip_lead_time": entry(
            "chip_lead_time",
            loader=lambda raw_root: ChipLeadTimeCollector(
                raw_dir=raw_root
            ).load_from_raw_snapshots(),
            to_frame=records_to_chip_lead_time_frame,
            raw_to_frame=records_to_raw_chip_lead_time_frame,
            primary_keys=["report_month"],
        ),
        "semiconductor_equipment": entry(
            "semiconductor_equipment",
            loader=_load_seaj_equipment_from_raw_snapshot,
            to_frame=records_to_semiconductor_equipment_frame,
            raw_to_frame=records_to_raw_semiconductor_equipment_frame,
            primary_keys=["report_month"],
        ),
        "semiconductor_equipment_semi": entry(
            "semiconductor_equipment_semi",
            loader=_load_semi_equipment_from_raw_snapshots,
            to_frame=build_semi_equipment_curated_frame,
            raw_to_frame=lambda frame: frame,
            primary_keys=["report_quarter"],
        ),
        "foundry_capacity_utilization": entry(
            "foundry_capacity_utilization",
            loader=_load_foundry_from_raw_snapshots,
            to_frame=build_foundry_utilization_frame,
            raw_to_frame=lambda frame: frame,
            primary_keys=["report_quarter"],
        ),
        "semiconductor_inventory_days": entry(
            "semiconductor_inventory_days",
            loader=_load_inventory_from_raw,
            to_frame=build_inventory_days_frame,
            raw_to_frame=build_inventory_raw_frame,
            primary_keys=["report_quarter", "symbol"],
        ),
    }
    return plan
