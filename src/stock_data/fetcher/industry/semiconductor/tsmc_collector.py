"""台积电月度营运营收与 DRAM 现货价格先导指标采集器 (TsmcLeadCollector)。

TSMC 月度营收在每月 10 日前后披露，比 SIA 全球销售额提前约 25 天，是全球晶圆代工与 AI 算力最高频、最前瞻的景气指标。
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any, cast

import polars as pl
from curl_cffi import requests

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.models import SemiconductorLeadRecord

logger = logging.getLogger(__name__)

# TSMC 月度营收基准汇率 (USD/NTD 约 31.5)
# 注意: 固定汇率口径仅作离线回退; 正常路径优先使用 FRED DEXTAUS 当月真实平均汇率折算。
_NTD_PER_USD = 31.5

_FRED_FALLBACK_WARNED = False


def monthly_usdtwd_rate(report_month: str) -> float | None:
    """取指定月份 (YYYY-MM) 美元兑新台币月均汇率 (TWD/USD)。

    数据源: FRED H.10 日频即期汇率 DEXTAUS (data/curated/fred/market=US/macro_indicators)。
    取当月所有交易日收盘价均值; 当月数据缺失时回退最近可用月份, 均不可用返回 None (由调用方回退固定汇率)。
    """
    global _FRED_FALLBACK_WARNED
    try:
        from stock_data.catalog import DataCatalog
        from stock_data.core.runtime import DataRuntimeContext

        cat = DataCatalog(data_source="fred", runtime=DataRuntimeContext.from_root("data"))
        df = cat.load_dataset("macro_indicators", symbols=["DEXTAUS"])
        if df.is_empty():
            return None
        df = df.filter(pl.col("symbol") == "DEXTAUS")
        if df.is_empty():
            return None

        yr, mo = parse_month_string(report_month)
        target = f"{yr:04d}-{mo:02d}"
        df = df.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("ym"))
        sub = df.filter(pl.col("ym") == target)
        if sub.is_empty():
            # 回退最近可用月份
            avail = df.filter(pl.col("ym") < target).sort("trade_date")
            if avail.is_empty():
                return None
        mean_val = sub["close"].mean()
        if mean_val is None:
            return None
        rate = cast("float", mean_val)
        return round(rate, 4)
    except Exception as exc:  # noqa: BLE001
        if not _FRED_FALLBACK_WARNED:
            logger.warning("读取 FRED DEXTAUS 汇率失败, 回退固定汇率 31.5: %s", exc)
            _FRED_FALLBACK_WARNED = True
        return None


def convert_ntd_to_usd(rev_ntd_million: float, report_month: str) -> float:
    """按当月真实汇率折算 NTD 营收为 USD 百万 (FRED DEXTAUS 月均; 缺失时回退固定 31.5)。"""
    rate = monthly_usdtwd_rate(report_month)
    if rate is None or rate <= 0:
        rate = _NTD_PER_USD
    return round(rev_ntd_million / rate, 2)


TWSE_OPENAPI_MONTHLY_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TWSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

TSMC_CSV_FIELDNAMES = [
    "report_month",
    "trade_date",
    "tsmc_revenue_ntd_million",
    "tsmc_revenue_usd_million",
    "tsmc_revenue_yoy",
    "tsmc_revenue_mom",
    "dram_dxi_index",
    "dram_spot_price_usd",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


class TsmcMonthlyRevenueCrawler:
    """台湾证券交易所 (TWSE) OpenAPI 台积电 (2330) 最新月营运公报在线采集器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.semi_dir = self.raw_dir / "semiconductor"

    def fetch_latest_revenue(self) -> dict[str, Any] | None:
        """从 TWSE OpenAPI 抓取台积电最新月度营业收入。"""
        self.semi_dir.mkdir(parents=True, exist_ok=True)
        try:
            logger.info(
                "正在从 TWSE OpenAPI 抓取台积电最新月营收: %s", TWSE_OPENAPI_MONTHLY_REVENUE_URL
            )
            resp = requests.get(
                TWSE_OPENAPI_MONTHLY_REVENUE_URL,
                headers=TWSE_HEADERS,
                impersonate="chrome120",
                timeout=12,
            )
            if resp.status_code != 200:
                logger.warning("访问 TWSE OpenAPI 返回 HTTP %d", resp.status_code)
                return None

            import json

            items = json.loads(resp.text)
            if not isinstance(items, list):
                return None

            for row in items:
                if str(row.get("公司代號", "")).strip() == "2330":
                    # 民国年月转 ISO 年月 (如 '11507' -> '2026-07')
                    raw_mo_str = str(row.get("資料年月", "")).strip()
                    if len(raw_mo_str) >= 4:
                        m_yr = int(raw_mo_str[:-2]) + 1911
                        m_m = int(raw_mo_str[-2:])
                        month_key = f"{m_yr:04d}-{m_m:02d}"
                    else:
                        continue

                    # 营收千元 -> 百万元新台币
                    raw_rev = float(str(row.get("營業收入-當月營收", "0")).replace(",", ""))
                    rev_ntd_million = round(raw_rev / 1000.0, 2)
                    rev_usd_million = convert_ntd_to_usd(rev_ntd_million, month_key)

                    yoy_str = str(row.get("營業收入-去年同月增減(%)", "")).strip()
                    mom_str = str(row.get("營業收入-上月比較增減(%)", "")).strip()
                    yoy = round(float(yoy_str) / 100.0, 4) if yoy_str else None
                    mom = round(float(mom_str) / 100.0, 4) if mom_str else None

                    logger.info(
                        "✅ 成功从 TWSE OpenAPI 抓取台积电 %s 营收: %.2f 百万新台币 (YoY: %s)",
                        month_key,
                        rev_ntd_million,
                        f"{yoy * 100:.2f}%" if yoy else "N/A",
                    )
                    return {
                        "report_month": month_key,
                        "tsmc_revenue_ntd_million": rev_ntd_million,
                        "tsmc_revenue_usd_million": rev_usd_million,
                        "tsmc_revenue_yoy": yoy,
                        "tsmc_revenue_mom": mom,
                        "release_date": date.today().isoformat(),
                        "source": "TWSE/TSMC",
                        "source_url": TWSE_OPENAPI_MONTHLY_REVENUE_URL,
                        "data_status": "actual",
                        "collected_at": now_utc_iso(),
                    }
        except Exception as e:
            logger.warning("抓取台积电最新月营收异常: %s", e)

        return None


def save_tsmc_raw_csv(file_path: Path | str, records: list[SemiconductorLeadRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TSMC_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_month": r.report_month,
                    "trade_date": r.trade_date.isoformat(),
                    "tsmc_revenue_ntd_million": r.tsmc_revenue_ntd_million,
                    "tsmc_revenue_usd_million": r.tsmc_revenue_usd_million
                    if r.tsmc_revenue_usd_million is not None
                    else "",
                    "tsmc_revenue_yoy": r.tsmc_revenue_yoy
                    if r.tsmc_revenue_yoy is not None
                    else "",
                    "tsmc_revenue_mom": r.tsmc_revenue_mom
                    if r.tsmc_revenue_mom is not None
                    else "",
                    "dram_dxi_index": r.dram_dxi_index if r.dram_dxi_index is not None else "",
                    "dram_spot_price_usd": r.dram_spot_price_usd
                    if r.dram_spot_price_usd is not None
                    else "",
                    "unit": r.unit or "million_ntd/usd",
                    "source": r.source or "TWSE/TSMC",
                    "source_url": r.source_url or "",
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                }
            )


def load_tsmc_raw_csv(file_path: Path | str) -> list[SemiconductorLeadRecord]:
    """从 RAW CSV 文件读取并标准化记录。"""
    p = Path(file_path)
    if not p.exists():
        return []

    def _safe_float(val: str | None) -> float | None:
        if not val or not val.strip():
            return None
        try:
            return float(val.strip())
        except (ValueError, TypeError):
            return None

    records: list[SemiconductorLeadRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            month_str = row["report_month"].strip()
            yr, mo = parse_month_string(month_str)
            t_date = get_month_end_date(yr, mo)
            ntd = _safe_float(row.get("tsmc_revenue_ntd_million")) or 0.0
            # 始终用 FRED 当月真实汇率重算 USD (raw 快照中的 usd 为旧固定汇率口径)
            usd = convert_ntd_to_usd(ntd, month_str) if ntd > 0 else None

            rel_d = None
            if row.get("release_date"):
                try:
                    rel_d = date.fromisoformat(row["release_date"].strip())
                except ValueError:
                    pass

            records.append(
                SemiconductorLeadRecord(
                    report_month=month_str,
                    trade_date=t_date,
                    tsmc_revenue_ntd_million=ntd,
                    tsmc_revenue_usd_million=usd,
                    tsmc_revenue_yoy=_safe_float(row.get("tsmc_revenue_yoy")),
                    tsmc_revenue_mom=_safe_float(row.get("tsmc_revenue_mom")),
                    dram_dxi_index=_safe_float(row.get("dram_dxi_index")),
                    dram_spot_price_usd=_safe_float(row.get("dram_spot_price_usd")),
                    unit=row.get("unit") or "million_ntd/usd",
                    source=row.get("source") or "TWSE/TSMC",
                    source_url=row.get("source_url") or TWSE_OPENAPI_MONTHLY_REVENUE_URL,
                    release_date=rel_d,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )

    records.sort(key=lambda r: r.trade_date)
    return records


class TsmcLeadCollector:
    """台积电月度营运营收与 DRAM 先导景气采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.semi_raw_dir = self.raw_dir / "semiconductor"
        self.crawler = TsmcMonthlyRevenueCrawler(raw_dir=self.raw_dir)

    def collect(self) -> list[SemiconductorLeadRecord]:
        """执行台积电先导指标采集: 在线抓取 TWSE 最新月营收并落盘，以最新采集为准。"""
        self.semi_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.semi_raw_dir / "tsmc_monthly.csv"

        # 在线爬取 TWSE 最新申报数据
        live_data = self.crawler.fetch_latest_revenue()
        if not live_data or not live_data.get("report_month"):
            logger.warning("在线抓取台积电月营收失败")
            return []

        m_key = str(live_data["report_month"])
        yr, mo = parse_month_string(m_key)
        t_d = get_month_end_date(yr, mo)
        rel_d = (
            date.fromisoformat(live_data["release_date"])
            if live_data.get("release_date")
            else date.today()
        )

        rec_live = SemiconductorLeadRecord(
            report_month=m_key,
            trade_date=t_d,
            tsmc_revenue_ntd_million=live_data["tsmc_revenue_ntd_million"],
            tsmc_revenue_usd_million=live_data["tsmc_revenue_usd_million"],
            tsmc_revenue_yoy=live_data.get("tsmc_revenue_yoy"),
            tsmc_revenue_mom=live_data.get("tsmc_revenue_mom"),
            dram_dxi_index=None,
            dram_spot_price_usd=None,
            unit="million_ntd/usd",
            source=live_data.get("source") or "TWSE/TSMC",
            source_url=live_data.get("source_url") or TWSE_OPENAPI_MONTHLY_REVENUE_URL,
            release_date=rel_d,
            data_status="actual",
            collected_at=live_data.get("collected_at") or now_utc_iso(),
        )

        records = [rec_live]
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(
        self, file_path: Path | str, records: list[SemiconductorLeadRecord]
    ) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_tsmc_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[SemiconductorLeadRecord]:
        """从 RAW CSV 文件读取并标准化记录。"""
        return load_tsmc_raw_csv(file_path)
