"""全球半导体 IDM 龙头季度存货周转天数 (DOI / Days of Inventory) 2-Tier ETL 转换与物化。

数据源:
1. SEC companyfacts: TXN / ADI 的 XBRL 库存与营业成本事实
2. SEC 6-K / 10-Q / 10-K: STM / NXPI 的季度业绩材料与缺失季度补充
3. RAW 层: 保留源字符串、源期末、来源 URL、快照哈希和快照路径
4. Curated 层: 由 endpoint registry + industry runner 按注册路径物化

核心指标:
- 个股 DOI (天) = (期末存货 / 季度营业成本) * 90
- 综合加权 DOI (天) = sum(存货) / sum(营业成本) * 90
- 库存周期相态 (inventory_regime):
  * high_overstocked: DOI >= 150 天 (严重累库去化压力)
  * elevated_destocking: 130 <= DOI < 150 天 (去库存周期中)
  * normal_balanced: 105 <= DOI < 130 天 (健康供需平衡)
  * tight_restocking: DOI < 105 天 (低库存强补库需求)
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from curl_cffi import requests as curl_requests

from stock_data.fetcher.industry.common import now_utc_iso, save_raw_snapshot
from stock_data.fetcher.industry.semiconductor.collectors.korea_memory_dart import (
    KoreaMemoryDartCollector,
)
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_content_bytes,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.models import SemiconductorInventoryRecord
from stock_data.fetcher.industry.semiconductor.parsers import (
    load_inventory_raw_csv,
    load_korea_memory_raw_csv,
)
from stock_data.fetcher.industry.semiconductor.parsers.inventory import (
    SecFiling,
    build_inventory_release_date_map,
    extract_sec_filings,
)
from stock_data.fetcher.industry.semiconductor.parsers.inventory_online import (
    parse_companyfacts_inventory,
    parse_sec_6k_inventory,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths
from stock_data.fetcher.industry.semiconductor.transforms import build_inventory_raw_frame

logger = logging.getLogger(__name__)

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{filename}"
SEC_HEADERS = {
    "User-Agent": os.getenv("SEC_USER_AGENT", "stock-data-semiconductor/1.0 (contact@example.com)"),
    "Accept": "application/json",
}
INVENTORY_CIK = {
    "TXN": "0000097476",
    "ADI": "0000006281",
    "STM": "0000932787",
    "NXPI": "0001413447",
    "MU": "0000723125",
}
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_ARCHIVE_CIK = {
    "TXN": "97476",
    "ADI": "6281",
    "STM": "932787",
    "NXPI": "1413447",
    "MU": "723125",
}
INVENTORY_SYMBOLS = tuple(INVENTORY_CIK)
KOREA_MEMORY_SYMBOLS = ("000660.KS", "005930.KS_DS")
ALL_INVENTORY_SYMBOLS = INVENTORY_SYMBOLS + KOREA_MEMORY_SYMBOLS
INVENTORY_START_DATE = date(2016, 1, 1)


class SemiconductorInventoryCollector:
    """全球半导体 IDM 龙头存货周转天数 (DOI) 采集与转换器。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.raw_csv = self.paths.inventory_csv
        self.korea_dart = KoreaMemoryDartCollector(raw_dir)
        canonical_raw_parquet = (
            self.paths.semiconductor_dir / "inventory" / "semiconductor_inventory_days.parquet"
        )
        legacy_raw_parquet = self.paths.semiconductor_dir / "semiconductor_inventory_days.parquet"
        self.raw_parquet = (
            canonical_raw_parquet
            if canonical_raw_parquet.exists() or not legacy_raw_parquet.exists()
            else legacy_raw_parquet
        )

    def collect_raw(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """按运行窗口增量更新 DART/SEC 官方源，失败时回退本地 RAW。"""
        try:
            local = self._load_raw_frame(
                force=False,
                start_date=start_date,
                end_date=end_date,
                allow_network=not force,
            )
        except ValueError as exc:
            if not force and start_date is None and end_date is None:
                raise
            logger.warning("本地 IDM RAW 不可直接使用，继续尝试官方在线源: %s", exc)
            local = build_inventory_raw_frame(pl.DataFrame())

        # 韩国双雄不是 SEC 标的：DART 负责发现最新定期报告、抓取修订版并把
        # 快照/Manifest/季度事实写回韩国 RAW。默认季度同步只检查近期窗口；
        # 历史回填通过 start_date/end_date 显式扩大窗口，避免每次任务扫描全史。
        # 只有项目已有韩国存证目录/RAW 时才启用 DART。这样隔离的临时 RAW
        # 或只测试美股 SEC 逻辑的运行不会因日期窗口意外触网并写入韩国事实。
        if self.paths.korea_memory_csv.exists() or self.korea_dart.filings_dir.exists():
            try:
                korea_changed = self.korea_dart.collect_raw(
                    force=force,
                    start_date=start_date,
                    end_date=end_date,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("韩国双雄 DART 增量采集失败，保留已有 RAW: %s", exc)
                korea_changed = 0
            if korea_changed:
                local = self._load_raw_frame(
                    force=False,
                    start_date=start_date,
                    end_date=end_date,
                    allow_network=False,
                )
        if not force and start_date is None and end_date is None:
            return local
        targets = _target_quarters(start_date=start_date, end_date=end_date)
        if not force and (not self.raw_parquet.exists() or _contains_all_targets(local, targets)):
            return local

        online_records = self._collect_online(
            start_date=start_date,
            end_date=end_date,
            force=force,
        )
        if not online_records:
            return local
        online = build_inventory_raw_frame(online_records)
        if _contains_all_targets(online, targets):
            return online

        logger.warning(
            "IDM 官方源仅返回 %d/%d 个目标季度标的组合，合并本地 RAW 作为缺口回退",
            _target_count(online),
            len(targets) * len(INVENTORY_SYMBOLS),
        )
        return _merge_raw_frames(local, online)

    def load_from_raw_snapshots(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """按运行窗口离线读取 RAW Parquet/CSV 与已缓存 SEC submissions。"""
        return self._load_raw_frame(
            force=False,
            start_date=start_date,
            end_date=end_date,
            allow_network=False,
        )

    def _load_raw_frame(
        self,
        *,
        force: bool,
        start_date: date | None,
        end_date: date | None,
        allow_network: bool,
    ) -> pl.DataFrame:
        frame: pl.DataFrame
        if self.raw_parquet.exists():
            try:
                frame = pl.read_parquet(self.raw_parquet)
                frame = _filter_frame_date_range(frame, start_date=start_date, end_date=end_date)
                frame = build_inventory_raw_frame(frame)
            except (OSError, pl.exceptions.PolarsError, ValueError) as exc:
                logger.warning(
                    "读取 IDM RAW Parquet 失败，回退 CSV [%s]: %s", self.raw_parquet, exc
                )
                frame = build_inventory_raw_frame(pl.DataFrame())
        elif self.raw_csv.exists():
            records = load_inventory_raw_csv(self.raw_csv)
            records = _filter_record_date_range(records, start_date=start_date, end_date=end_date)
            if any(record.release_date is None for record in records):
                release_dates = self._resolve_release_dates(
                    records,
                    force=force,
                    allow_network=allow_network,
                )
                records = load_inventory_raw_csv(self.raw_csv, release_dates=release_dates)
                records = _filter_record_date_range(
                    records,
                    start_date=start_date,
                    end_date=end_date,
                )
            frame = build_inventory_raw_frame(records)
        else:
            frame = build_inventory_raw_frame(pl.DataFrame())

        if self.paths.korea_memory_csv.exists():
            korea_records = load_korea_memory_raw_csv(self.paths.korea_memory_csv)
            korea_records = _filter_record_date_range(
                korea_records, start_date=start_date, end_date=end_date
            )
            if korea_records:
                korea_frame = build_inventory_raw_frame(korea_records)
                frame = _merge_raw_frames(frame, korea_frame)

        return frame

    def _collect_online(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        force: bool,
    ) -> list[SemiconductorInventoryRecord]:
        targets = _target_quarters(start_date=start_date, end_date=end_date)
        if not targets:
            return []

        collected_at = now_utc_iso()
        records: list[SemiconductorInventoryRecord] = []
        available_by_symbol: dict[str, set[str]] = {}
        for symbol in ("TXN", "ADI", "NXPI", "MU"):
            payload_info = self._load_companyfacts(symbol, force=force)
            if payload_info is None:
                available_by_symbol[symbol] = set()
                continue
            payload, source_url, content_hash, snapshot_path = payload_info
            parsed = parse_companyfacts_inventory(
                payload,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                source_url=source_url,
                raw_content_hash=content_hash,
                raw_snapshot_path=snapshot_path,
                collected_at=collected_at,
            )
            if symbol == "NXPI":
                parsed = [record for record in parsed if int(record.report_quarter[:4]) >= 2019]
            available_by_symbol[symbol] = {record.report_quarter for record in parsed}
            records.extend(parsed)

        filings_by_symbol = self._load_sec_filings(
            ["STM", "NXPI"],
            force=force,
            allow_network=True,
        )
        records.extend(
            self._collect_6k_quarters(
                "STM",
                filings_by_symbol.get("STM", []),
                targets=targets - available_by_symbol.get("STM", set()),
                force=force,
                collected_at=collected_at,
            )
        )
        records.extend(
            self._collect_6k_quarters(
                "NXPI",
                filings_by_symbol.get("NXPI", []),
                targets=targets - available_by_symbol.get("NXPI", set()),
                force=force,
                collected_at=collected_at,
            )
        )
        return _dedupe_records(records)

    def _load_companyfacts(
        self,
        symbol: str,
        *,
        force: bool,
    ) -> tuple[dict[str, Any], str, str, str] | None:
        url = SEC_COMPANYFACTS_URL.format(cik=INVENTORY_CIK[symbol])
        cache_path = (
            self.paths.inventory_dir / "sec_companyfacts" / f"{symbol}_companyfacts.json.gz"
        )
        content = self._load_online_bytes(url, cache_path=cache_path, force=force)
        if content is None:
            return None
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("SEC companyfacts JSON 解析失败 [%s]: %s", symbol, exc)
            return None
        if not isinstance(payload, dict):
            return None
        return (
            payload,
            url,
            raw_content_sha256(content),
            raw_snapshot_path_value(cache_path, self.paths.raw_root),
        )

    def _collect_6k_quarters(
        self,
        symbol: str,
        filings: Sequence[SecFiling],
        *,
        targets: set[str],
        force: bool,
        collected_at: str,
    ) -> list[SemiconductorInventoryRecord]:
        records: list[SemiconductorInventoryRecord] = []
        for report_quarter in sorted(targets):
            parsed = self._collect_6k_quarter(
                symbol,
                report_quarter,
                filings,
                force=force,
                collected_at=collected_at,
            )
            if parsed is not None:
                records.append(parsed)
        return records

    def _collect_6k_quarter(
        self,
        symbol: str,
        report_quarter: str,
        filings: Sequence[SecFiling],
        *,
        force: bool,
        collected_at: str,
    ) -> SemiconductorInventoryRecord | None:
        year = int(report_quarter[:4])
        quarter = int(report_quarter[-1])
        target_date = _quarter_trade_date(year, quarter)
        lower = target_date + timedelta(days=10)
        upper = target_date + timedelta(days=75)
        candidates = sorted(
            (
                filing
                for filing in filings
                if filing.form in {"6-K", "10-Q", "10-K", "10-Q/A", "10-K/A"}
                and filing.accession_number
                and lower <= filing.filing_date <= upper
                and filing.size >= 100_000
            ),
            key=lambda filing: (filing.filing_date, -filing.size),
        )
        for filing in candidates:
            for url in self._filing_document_urls(symbol, filing, force=force):
                cache_name = (
                    f"{symbol}_{report_quarter}_{filing.accession_number.replace('-', '')}_"
                    f"{Path(url).name}"
                )
                cache_path = self.paths.inventory_dir / "sec_6k" / f"{cache_name}.gz"
                loaded = self._load_online_bytes(url, cache_path=cache_path, force=force)
                if loaded is None:
                    continue
                parsed = parse_sec_6k_inventory(
                    loaded,
                    symbol=symbol,
                    report_quarter=report_quarter,
                    release_date=filing.filing_date,
                    source_url=url,
                    raw_content_hash=raw_content_sha256(loaded),
                    raw_snapshot_path=raw_snapshot_path_value(
                        cache_path,
                        self.paths.raw_root,
                    ),
                    collected_at=collected_at,
                )
                if (
                    parsed is not None
                    and _quarter_key(symbol, parsed.source_period_end) == report_quarter
                ):
                    return parsed
        logger.warning("SEC 6-K 未解析到 IDM 季度数据 [%s %s]", symbol, report_quarter)
        return None

    def _filing_document_urls(
        self,
        symbol: str,
        filing: SecFiling,
        *,
        force: bool,
    ) -> list[str]:
        base = (
            f"https://www.sec.gov/Archives/edgar/data/{SEC_ARCHIVE_CIK[symbol]}/"
            f"{filing.accession_number.replace('-', '')}/"
        )
        urls = [base + filing.primary_document] if filing.primary_document else []
        index_url = base + "index.json"
        index_path = (
            self.paths.inventory_dir
            / "sec_6k_index"
            / f"{symbol}_{filing.accession_number.replace('-', '')}_index.json.gz"
        )
        content = self._load_online_bytes(index_url, cache_path=index_path, force=force)
        if content is None:
            return urls
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return urls
        items = payload.get("directory", {}).get("item", []) if isinstance(payload, dict) else []
        documents = [
            (str(item.get("name") or ""), int(item.get("size") or 0))
            for item in items
            if isinstance(item, dict)
            and str(item.get("name") or "").lower().endswith((".htm", ".html"))
            and str(item.get("name") or "") != filing.primary_document
        ]
        preferred = [
            name
            for name, _size in documents
            if any(marker in name.lower() for marker in ("ex99", "exhibit", "dex991"))
        ]
        others = [name for name, _size in sorted(documents, key=lambda item: -item[1])]
        urls.extend(base + name for name in preferred + others if base + name not in urls)
        return urls

    def _load_online_bytes(
        self,
        url: str,
        *,
        cache_path: Path,
        force: bool,
    ) -> bytes | None:
        if cache_path.exists() and not force:
            try:
                return raw_snapshot_content_bytes(cache_path)
            except (OSError, EOFError) as exc:
                logger.warning("读取 SEC 快照失败 [%s]: %s", cache_path, exc)
        try:
            response = curl_requests.get(
                url,
                headers=SEC_HEADERS,
                timeout=20,
                impersonate="chrome120",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SEC 在线请求异常 [%s]: %s", url, exc)
            return None
        content = response_content_bytes(response)
        if response.status_code != 200 or not content:
            logger.warning("SEC 在线请求失败 [%s]: HTTP %s", url, response.status_code)
            return None
        snapshot_path = save_raw_snapshot(
            cache_path.parent.name,
            cache_path.name.removesuffix(".gz"),
            content,
            base_dir=cache_path.parent.parent,
            compress=True,
        )
        if snapshot_path != cache_path:
            logger.warning("SEC 快照路径与预期不一致: %s != %s", snapshot_path, cache_path)
        return content

    def _resolve_release_dates(
        self,
        records: Sequence[SemiconductorInventoryRecord],
        *,
        force: bool,
        allow_network: bool = True,
    ) -> dict[tuple[str, str], date]:
        symbols = sorted(
            {record.symbol.upper() for record in records if record.release_date is None}
        )
        filings = self._load_sec_filings(symbols, force=force, allow_network=allow_network)
        rows = [
            {
                "symbol": record.symbol,
                "report_quarter": record.report_quarter,
                "trade_date": record.trade_date,
            }
            for record in records
            if record.release_date is None
        ]
        return build_inventory_release_date_map(rows, filings)

    def _load_sec_filings(
        self,
        symbols: list[str],
        *,
        force: bool,
        allow_network: bool,
    ) -> dict[str, list[SecFiling]]:
        if allow_network:
            self.paths.inventory_sec_dir.mkdir(parents=True, exist_ok=True)
        result: dict[str, list[SecFiling]] = {}
        for symbol in symbols:
            cik = INVENTORY_CIK.get(symbol)
            if cik is None:
                continue
            payloads = self._load_submission_payloads(
                symbol,
                cik,
                force=force,
                allow_network=allow_network,
            )
            filings: list[SecFiling] = []
            for payload in payloads:
                filings.extend(extract_sec_filings(payload))
            result[symbol] = filings
        return result

    def _load_submission_payloads(
        self,
        symbol: str,
        cik: str,
        *,
        force: bool,
        allow_network: bool,
    ) -> list[dict[str, Any]]:
        main_path = self.paths.inventory_sec_dir / f"{symbol}.json"
        main_payload = self._load_submission_json(
            main_path,
            SEC_SUBMISSIONS_URL.format(cik=cik),
            force=force,
            allow_network=allow_network,
        )
        if main_payload is not None and not _submission_matches_identity(main_payload, symbol, cik):
            logger.warning("SEC submissions 缓存标的或 CIK 不匹配，拒绝复用: %s", main_path.name)
            main_payload = self._load_submission_json(
                main_path,
                SEC_SUBMISSIONS_URL.format(cik=cik),
                force=True,
                allow_network=allow_network,
            )
            if main_payload is not None and not _submission_matches_identity(
                main_payload, symbol, cik
            ):
                main_payload = None
        if main_payload is None:
            return []

        payloads = [main_payload]
        filings = main_payload.get("filings", {})
        older_files = filings.get("files", []) if isinstance(filings, dict) else []
        for item in older_files:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("name") or "")
            if not filename or Path(filename).name != filename:
                continue
            older_path = self.paths.inventory_sec_dir / f"{symbol}__{filename}"
            older_payload = self._load_submission_json(
                older_path,
                SEC_SUBMISSIONS_FILE_URL.format(filename=filename),
                force=force,
                allow_network=allow_network,
            )
            if older_payload is not None and _submission_matches_identity(
                older_payload,
                symbol,
                cik,
                require_identity=False,
            ):
                payloads.append(older_payload)
            elif older_payload is not None:
                logger.warning(
                    "SEC submissions 历史缓存标的或 CIK 不匹配，拒绝复用: %s", older_path.name
                )
        return payloads

    def _load_submission_json(
        self,
        cache_path: Path,
        url: str,
        *,
        force: bool,
        allow_network: bool,
    ) -> dict[str, Any] | None:
        if cache_path.exists() and not force:
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else None
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("读取 SEC submissions 缓存失败 [%s]: %s", cache_path.name, exc)

        if not allow_network:
            return None
        try:
            response = curl_requests.get(
                url,
                headers=SEC_HEADERS,
                timeout=20,
                impersonate="chrome120",
            )
            if response.status_code != 200 or not response.content:
                logger.warning("SEC submissions 请求失败 [%s]: HTTP %s", url, response.status_code)
                return None
            payload = json.loads(response.text)
            if not isinstance(payload, dict):
                logger.warning("SEC submissions 响应不是 JSON 对象 [%s]", url)
                return None
            cache_path.write_text(response.text, encoding="utf-8")
            return payload
        except Exception as exc:  # noqa: BLE001
            logger.warning("SEC submissions 请求异常 [%s]: %s", url, exc)
            return None


def _submission_matches_identity(
    payload: dict[str, Any],
    symbol: str,
    cik: str,
    *,
    require_identity: bool = True,
) -> bool:
    raw_payload_cik = str(payload.get("cik") or "").strip()
    if not raw_payload_cik and require_identity:
        return False
    payload_cik = raw_payload_cik.lstrip("0") or "0"
    expected_cik = str(cik).lstrip("0") or "0"
    if raw_payload_cik and payload_cik != expected_cik:
        return False
    tickers = payload.get("tickers")
    if isinstance(tickers, list) and tickers:
        return symbol in {str(ticker).upper() for ticker in tickers}
    return True


def _filter_record_date_range(
    records: Sequence[SemiconductorInventoryRecord],
    *,
    start_date: date | None,
    end_date: date | None,
) -> list[SemiconductorInventoryRecord]:
    """按报告期末 trade_date 裁剪季度事实，不使用发布日期裁剪。"""
    return [
        record
        for record in records
        if (start_date is None or record.trade_date >= start_date)
        and (end_date is None or record.trade_date <= end_date)
    ]


def _filter_frame_date_range(
    frame: pl.DataFrame,
    *,
    start_date: date | None,
    end_date: date | None,
) -> pl.DataFrame:
    if "trade_date" not in frame.columns:
        return frame
    condition = pl.lit(True)
    if start_date is not None:
        condition = condition & (pl.col("trade_date") >= start_date)
    if end_date is not None:
        condition = condition & (pl.col("trade_date") <= end_date)
    return frame.filter(condition)


def _quarter_trade_date(year: int, quarter: int) -> date:
    return date(year, (3, 6, 9, 12)[quarter - 1], (31, 30, 30, 31)[quarter - 1])


def _quarter_key(symbol: str, period_end: date | None) -> str:
    if period_end is None:
        return ""
    month = period_end.month
    if symbol.upper() == "ADI":
        quarter = 1 if month <= 2 else 2 if month <= 5 else 3 if month <= 8 else 4
    else:
        quarter = 1 if month <= 4 else 2 if month <= 7 else 3 if month <= 10 else 4
    return f"{period_end.year}Q{quarter}"


def _target_quarters(
    *,
    start_date: date | None,
    end_date: date | None,
) -> set[str]:
    lower = start_date or INVENTORY_START_DATE
    upper = end_date or date.today()
    targets: set[str] = set()
    for year in range(lower.year, upper.year + 1):
        for quarter in range(1, 5):
            trade_date = _quarter_trade_date(year, quarter)
            if lower <= trade_date <= upper:
                targets.add(f"{year}Q{quarter}")
    return targets


def _contains_all_targets(frame: pl.DataFrame, targets: set[str]) -> bool:
    if not targets:
        return True
    if frame.is_empty() or not {"symbol", "report_quarter"}.issubset(frame.columns):
        return False
    actual = set(zip(frame["symbol"].to_list(), frame["report_quarter"].to_list()))
    expected = {(symbol, quarter) for symbol in ALL_INVENTORY_SYMBOLS for quarter in targets}
    return expected.issubset(actual)


def _target_count(frame: pl.DataFrame) -> int:
    if frame.is_empty() or not {"symbol", "report_quarter"}.issubset(frame.columns):
        return 0
    return frame.select(["symbol", "report_quarter"]).unique().height


def _merge_raw_frames(left: pl.DataFrame, right: pl.DataFrame) -> pl.DataFrame:
    frames = [frame for frame in (left, right) if not frame.is_empty()]
    if not frames:
        return build_inventory_raw_frame(pl.DataFrame())
    merged = pl.concat(frames, how="diagonal_relaxed").unique(
        subset=["report_quarter", "symbol"],
        keep="last",
    )
    return build_inventory_raw_frame(merged)


def _dedupe_records(
    records: Sequence[SemiconductorInventoryRecord],
) -> list[SemiconductorInventoryRecord]:
    unique: dict[tuple[str, str], SemiconductorInventoryRecord] = {}
    for record in records:
        unique[(record.symbol, record.report_quarter)] = record
    return sorted(unique.values(), key=lambda record: (record.report_quarter, record.symbol))
