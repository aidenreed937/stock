"""化工月频产业调研采集器 (ChemicalMonthlySurveyCollector)。

免费月频数值源（SMM 钛快讯 / 隆众·Mysteel 月度产量统计）的 2-Tier 采集：
1. 清单驱动：``config/data_sources/chemicals_monthly_sources.csv`` 维护
   (product_name, symbol, report_month, source, release_date, source_url)；
2. 抓取正文 → 保存 RAW HTML 快照（SHA-256 + 相对路径）→ 正则提取
   产量/产能利用率/厂商库存（含环比同比）→ Upsert 至
   ``data/raw/industry/chemicals/operating_rates/monthly_survey.csv``；
3. 离线模式（enable_online=False）仅从 RAW 读回，不触发网络请求。
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from curl_cffi import requests

from stock_data.fetcher.industry.chemicals.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.chemicals.parsers.monthly_survey import (
    has_monthly_metrics,
    parse_monthly_survey_record,
)
from stock_data.fetcher.industry.chemicals.schemas import (
    MONTHLY_SURVEY_COLLECTION_SCHEMA,
)
from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.contracts import IndustryFrameResult

_MANIFEST_PATHS = (
    Path("config/data_sources/chemicals_monthly_sources.csv"),
    Path("data/raw/industry/chemicals/operating_rates/chemicals_monthly_sources.csv"),
)

_RAW_FIELDS = [
    "report_month",
    "product_name",
    "symbol",
    "production_w_tons",
    "operating_rate_pct",
    "factory_inventory_w_tons",
    "inventory_mom_pct",
    "inventory_yoy_pct",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
    "raw_content_sha256",
    "raw_snapshot_path",
]

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ChemicalMonthlySurveyCollector:
    """SMM / 隆众·Mysteel 钛白粉月频调研采集器。"""

    def __init__(self, raw_dir: Path | str, enable_online: bool = False) -> None:
        self.raw_dir = Path(raw_dir)
        self.survey_dir = self.raw_dir / "chemicals" / "operating_rates"
        self.snapshot_dir = self.survey_dir / "monthly_snapshots"
        self.csv_file = self.survey_dir / "monthly_survey.csv"
        self.survey_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.enable_online = enable_online
        self.session: Any = requests.Session(impersonate="chrome120")
        self.headers = {"User-Agent": _UA}
        self.collection_errors: list[str] = []
        self.missing_periods: set[str] = set()
        self.fetched_periods: set[str] = set()
        self.cached_periods: set[str] = set()

    # ---------- RAW CSV ----------
    def _load_raw_csv(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        if not self.csv_file.exists():
            return {}
        records: dict[tuple[str, str, str], dict[str, Any]] = {}
        with self.csv_file.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["product_name"], row["report_month"], row["source"])
                records[key] = {
                    "report_month": row["report_month"],
                    "product_name": row["product_name"],
                    "symbol": row.get("symbol") or "",
                    "production_w_tons": _to_float(row.get("production_w_tons")),
                    "operating_rate_pct": _to_float(row.get("operating_rate_pct")),
                    "factory_inventory_w_tons": _to_float(row.get("factory_inventory_w_tons")),
                    "inventory_mom_pct": _to_float(row.get("inventory_mom_pct")),
                    "inventory_yoy_pct": _to_float(row.get("inventory_yoy_pct")),
                    "source": row["source"],
                    "source_url": row.get("source_url") or "",
                    "release_date": _to_date(row.get("release_date")),
                    "data_status": row.get("data_status") or "actual",
                    "collected_at": row.get("collected_at") or now_utc_iso(),
                    "raw_content_sha256": row.get("raw_content_sha256") or "",
                    "raw_snapshot_path": row.get("raw_snapshot_path") or "",
                }
        return records

    def _save_raw_csv(self, records: dict[tuple[str, str, str], dict[str, Any]]) -> None:
        rows = sorted(
            records.values(),
            key=lambda r: (r["product_name"], r["report_month"], r["source"]),
        )
        with self.csv_file.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_RAW_FIELDS)
            writer.writeheader()
            for r in rows:
                writer.writerow(
                    {
                        **r,
                        "release_date": r["release_date"].isoformat()
                        if r.get("release_date")
                        else "",
                    }
                )

    # ---------- Manifest ----------
    def _load_sources(self) -> list[dict[str, Any]]:
        for manifest_path in _MANIFEST_PATHS:
            if not manifest_path.exists():
                continue
            rows: list[dict[str, Any]] = []
            with manifest_path.open("r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if not row.get("product_name") or not row.get("source_url"):
                        continue
                    rows.append(
                        {
                            "product_name": row["product_name"],
                            "symbol": row.get("symbol") or "",
                            "report_month": row["report_month"],
                            "source": row.get("source") or "",
                            "release_date": _to_date(row.get("release_date")),
                            "source_url": row["source_url"],
                        }
                    )
            return rows
        return []

    # ---------- 网络 ----------
    def _request(self, url: str) -> str | None:
        if not self.enable_online:
            return None
        try:
            response = self.session.get(url, headers=self.headers, timeout=20)
            if response.status_code != 200:
                return None
            response.encoding = "utf-8"
            return str(response.text)
        except Exception:
            return None

    def _save_snapshot(self, name: str, html_text: str) -> tuple[str, str]:
        content_hash = raw_content_sha256(html_text.encode("utf-8"))
        snapshot_path = self.snapshot_dir / f"{name}_{content_hash[:16]}.html"
        if not snapshot_path.exists():
            snapshot_path.write_text(html_text, encoding="utf-8")
        return content_hash, raw_snapshot_path_value(snapshot_path, self.raw_dir)

    # ---------- 采集 ----------
    def collect(self, force: bool = False) -> pl.DataFrame:
        self.collection_errors = []
        self.missing_periods = set()
        self.fetched_periods = set()
        self.cached_periods = set()
        records = self._load_raw_csv()
        now_iso = now_utc_iso()

        if not self.enable_online:
            for key, record in records.items():
                if has_monthly_metrics(record):
                    self.cached_periods.add(f"{key[2]}:{key[1]}")
        else:
            for item in self._load_sources():
                key = (item["product_name"], item["report_month"], item["source"])
                if not force and key in records and has_monthly_metrics(records[key]):
                    self.cached_periods.add(f"{item['source']}:{item['report_month']}")
                    continue
                html_text = self._request(item["source_url"])
                if not html_text:
                    self.missing_periods.add(f"{item['source']}:{item['report_month']}")
                    self.collection_errors.append(
                        f"{item['report_month']}:{item['source']}: 请求失败或空响应"
                    )
                    continue
                content_hash, snapshot_path = self._save_snapshot(
                    f"{item['symbol']}_{item['report_month']}", html_text
                )
                parsed_record = parse_monthly_survey_record(
                    html_text,
                    report_month=item["report_month"],
                    source=item["source"],
                    source_url=item["source_url"],
                    release_date=item["release_date"],
                    symbol=item["symbol"],
                    product_name=item["product_name"],
                )
                if parsed_record is None or not has_monthly_metrics(parsed_record):
                    self.missing_periods.add(f"{item['source']}:{item['report_month']}")
                    self.collection_errors.append(
                        f"{item['report_month']}:{item['source']}: 未解析出有效指标"
                    )
                    continue
                parsed_record["collected_at"] = now_iso
                parsed_record["raw_content_sha256"] = content_hash
                parsed_record["raw_snapshot_path"] = snapshot_path
                records[key] = parsed_record
                self.fetched_periods.add(f"{item['source']}:{item['report_month']}")

        self._save_raw_csv(records)
        return self.load_from_raw()

    def collect_result(self, force: bool = False) -> IndustryFrameResult:
        frame = self.collect(force=force)
        errors = tuple(self.collection_errors)
        missing = tuple(sorted(self.missing_periods))
        if frame.is_empty() and missing:
            status = "MISSING_RANGE"
        elif errors and frame.is_empty():
            status = "FAILED"
        elif errors or missing:
            status = "PARTIAL"
        elif frame.is_empty():
            status = "EMPTY"
        else:
            status = "SUCCESS"
        return IndustryFrameResult(
            frame=frame,
            status=status,
            fetched_periods=tuple(sorted(self.fetched_periods)),
            cached_periods=tuple(sorted(self.cached_periods)),
            missing_periods=missing,
            errors=errors,
            updated=bool(self.fetched_periods),
        )

    def load_from_raw(self) -> pl.DataFrame:
        records = self._load_raw_csv()
        if not records:
            return pl.DataFrame(schema=MONTHLY_SURVEY_COLLECTION_SCHEMA)
        return pl.DataFrame(list(records.values()), schema=MONTHLY_SURVEY_COLLECTION_SCHEMA)


def _to_float(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


__all__ = ["ChemicalMonthlySurveyCollector"]
