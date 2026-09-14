"""三星 DS / SK 海力士 DART 智能增量采集器。

职责边界：
* 从 DART 定期报告搜索页发现报告，并按 `(report_quarter, filing_date, rcp_no)`
  选择最终修订版；
* 通过 ``dsaf001/main.do`` 的文档树定位 viewer HTML；
* 保存 viewer HTML 快照和公司级 source manifest；
* 将解析出的法定源端金额按季度主键幂等合并到 ``korea_memory_raw.csv``。

金额仍保持 DART 原始 KRW million / CSV 的 trillion/billion KRW 口径，汇率折算和
DOI 计算继续由既有 parser/transform 负责。
"""

from __future__ import annotations

import csv
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.parsers.korea_memory import (
    samsung_ds_ratio_minimum,
    validate_samsung_ds_ratio,
)
from stock_data.fetcher.industry.semiconductor.parsers.korea_memory_dart import (
    DART_REPORT_URL_PREFIX,
    DartReport,
    build_dart_viewer_url,
    parse_dart_search_results,
    parse_dart_toc_nodes,
    parse_samsung_inventory_html,
    parse_samsung_segment_html,
    parse_skhynix_financial_html,
    select_latest_dart_revisions,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

DART_SEARCH_URL = "https://dart.fss.or.kr/dsab001/search.ax"
DART_MAIN_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp_no}"
# DART 检索页对过长的日期范围并不稳定；历史回填按不超过 9 年的窗口拆分。
DART_DISCOVERY_WINDOW_DAYS = 365 * 9
DART_HEADERS = {
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

COMPANIES: dict[str, dict[str, str]] = {
    "samsung": {"query": "삼성전자", "corp_code": "00126380"},
    "sk_hynix": {"query": "SK하이닉스", "corp_code": "00164779"},
}

SAMSUNG_SOURCE_MANIFEST_COLUMNS = [
    "report_quarter",
    "report_type",
    "release_date",
    "report_rcp_no",
    "source_url",
    "local_snapshot_path",
    "raw_content_sha256",
    "extraction_scope",
]
SK_HYNIX_SOURCE_MANIFEST_COLUMNS = [
    "report_quarter",
    "report_type",
    "report_rcp_no",
    "report_source_url",
    "report_snapshot_path",
    "report_snapshot_sha256",
    "inventory_krw_million",
    "reported_cost_of_revenue_krw_million",
    "cost_of_revenue_used_krw_million",
    "cost_of_revenue_derivation",
    "prior_9m_rcp_no",
    "prior_9m_source_url",
    "prior_9m_snapshot_path",
    "prior_9m_snapshot_sha256",
    "prior_9m_cost_of_revenue_krw_million",
]
KOREA_RAW_COLUMNS = [
    "symbol",
    "report_quarter",
    "trade_date",
    "inventory_krw",
    "cost_of_revenue_krw",
    "cost_of_revenue_annual_raw",
    "cost_of_revenue_derivation",
    "unit",
    "group_total_inventory_krw",
    "release_date",
    "source_period_end",
    "fiscal_period_raw",
    "source",
    "source_url",
    "collected_at",
    "raw_content_sha256",
    "raw_snapshot_path",
    "ds_revenue_krw",
    "ds_operating_profit_krw",
    "cost_of_revenue_source",
    "inventory_scope",
    "memory_inventory_status",
]


class KoreaMemoryDartCollector:
    """韩国双雄 DART 定期报告增量采集与 RAW 幂等合并。"""

    def __init__(
        self,
        raw_dir: Path | str,
        *,
        timeout: float = 30.0,
        session: Any | None = None,
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.filings_dir = self.paths.semiconductor_dir / "korea_filings"
        self.raw_csv = self.paths.korea_memory_csv
        self.samsung_manifest = self.filings_dir / "samsung_dart_source_manifest.csv"
        self.sk_hynix_manifest = self.filings_dir / "sk_hynix_dart_source_manifest.csv"
        self.timeout = timeout
        self.session = session
        self._main_cache: dict[str, bytes] = {}

    def collect_raw(
        self,
        *,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        """发现、解析并幂等写入两家公司的 DART 事实。

        返回本次实际替换/新增的季度记录数。DART 网络不可用时返回 0，调用方可
        继续使用已有 RAW；不会用空响应覆盖本地事实。
        """
        targets = self._target_quarters(start_date=start_date, end_date=end_date)
        if not targets:
            return 0
        changed = 0
        try:
            changed += self._collect_samsung(targets, force=force)
            changed += self._collect_skhynix(targets, force=force)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DART 韩国存储增量采集未完成，保留已有 RAW: %s", exc)
        return changed

    def _collect_samsung(self, targets: set[str], *, force: bool) -> int:
        existing_rows = _read_csv_rows(self.raw_csv)
        existing_manifest_raw = _read_csv_rows(self.samsung_manifest)
        existing_manifest = _normalize_samsung_manifest_rows(existing_manifest_raw)
        if existing_manifest != existing_manifest_raw:
            self._write_manifest(
                self.samsung_manifest,
                existing_manifest,
                SAMSUNG_SOURCE_MANIFEST_COLUMNS,
            )
        reports = self._discover_reports("samsung", targets)
        selected = select_latest_dart_revisions(reports, target_quarters=targets)
        if not selected:
            return 0
        selected = self._skip_unchanged_reports(
            selected,
            existing_manifest,
            force=force,
            report_type_suffixes=("interim_report", "business_report"),
            raw_rows=existing_rows,
        )
        if not selected:
            return 0

        # 为半年度/三季度/年度 DS 累计值补齐同年度前置报告，才能安全做相邻差分。
        prerequisite_quarters = set(selected)
        for quarter in list(selected):
            year, quarter_number = _quarter_parts(quarter)
            prerequisite_quarters.update(
                f"{year}Q{number}" for number in range(1, quarter_number + 1)
            )
        all_reports = self._discover_reports("samsung", prerequisite_quarters)
        all_selected = select_latest_dart_revisions(
            all_reports,
            target_quarters=prerequisite_quarters,
        )
        segment_facts: dict[str, tuple[float, float, DartReport, str, str, str]] = {}
        inventory_facts: dict[str, tuple[float, float, str, DartReport, str, str]] = {}
        manifest_rows = list(existing_manifest)
        for quarter, report in sorted(all_selected.items()):
            try:
                inventory_content, inventory_path = self._fetch_samsung_section(
                    report,
                    selector_kind="inventory",
                )
                inventory = parse_samsung_inventory_html(inventory_content)
                ratio = inventory.inventory_krw_million / inventory.group_inventory_krw_million
                # 旧组织表中的 DS 半导体小计在 2016–2017 年可低至约 22%，
                # 仍明显不是误取集团总额。保留上限硬门禁，并按报告期采用
                # 集中的历史下限，避免把 DART 原值误判为抓取错误。
                minimum_ratio = samsung_ds_ratio_minimum(quarter)
                validate_samsung_ds_ratio(
                    inventory.inventory_krw_million,
                    inventory.group_inventory_krw_million,
                    minimum_ratio=minimum_ratio,
                )
                if ratio < 0.35:
                    logger.warning(
                        "三星历史旧组织 DS/集团存货占比低于当前经验下限，保留 DART 原值: %s %.1f%%",
                        quarter,
                        ratio * 100,
                    )
                inventory_facts[quarter] = (
                    inventory.inventory_krw_million,
                    inventory.group_inventory_krw_million,
                    inventory.inventory_scope,
                    report,
                    inventory_path,
                    raw_content_sha256(inventory_content),
                )
                manifest_rows = _upsert_manifest_row(
                    manifest_rows,
                    {
                        "report_quarter": quarter,
                        "report_type": report.report_type,
                        "release_date": report.filing_date.isoformat(),
                        "report_rcp_no": report.rcp_no,
                        "source_url": report.source_url,
                        "local_snapshot_path": inventory_path,
                        "raw_content_sha256": raw_content_sha256(inventory_content),
                        "extraction_scope": (
                            "C. Inventory / 다. 재고자산 현황 / "
                            f"{'DS division' if inventory.inventory_scope == 'ds_division' else 'semiconductor'} total inventory"
                        ),
                    },
                    key=("report_quarter", "report_type"),
                )
            except (OSError, ValueError) as exc:
                logger.warning("三星 DART 库存解析失败 [%s %s]: %s", quarter, report.rcp_no, exc)
                continue

            try:
                segment_content, segment_path = self._fetch_samsung_section(
                    report,
                    selector_kind="segment",
                )
                segment = parse_samsung_segment_html(segment_content)
                segment_facts[quarter] = (
                    segment.ds_revenue_krw_million,
                    segment.ds_operating_profit_krw_million,
                    report,
                    segment_path,
                    raw_content_sha256(segment_content),
                    segment.reported_unit,
                )
                manifest_rows = _upsert_manifest_row(
                    manifest_rows,
                    {
                        "report_quarter": quarter,
                        "report_type": f"{report.report_type}_segment_summary",
                        "release_date": report.filing_date.isoformat(),
                        "report_rcp_no": report.rcp_no,
                        "source_url": report.source_url,
                        "local_snapshot_path": segment_path,
                        "raw_content_sha256": raw_content_sha256(segment_content),
                        "extraction_scope": "사업부문별 요약 재무 현황 / DS revenue and operating profit",
                    },
                    key=("report_quarter", "report_type"),
                )
            except (OSError, ValueError) as exc:
                logger.warning(
                    "三星 DART 分部摘要解析失败 [%s %s]: %s", quarter, report.rcp_no, exc
                )

        self._write_manifest(self.samsung_manifest, manifest_rows, SAMSUNG_SOURCE_MANIFEST_COLUMNS)
        quarterly_segments = _quarterly_segment_values(segment_facts)
        incoming: list[dict[str, str]] = []
        for quarter in sorted(all_selected):
            if quarter not in inventory_facts or quarter not in quarterly_segments:
                continue
            (
                inventory,
                group_inventory,
                inventory_scope,
                report,
                snapshot_path,
                snapshot_hash,
            ) = inventory_facts[quarter]
            (
                revenue,
                operating_profit,
                _segment_report,
                _segment_path,
                _segment_hash,
                segment_unit,
            ) = quarterly_segments[quarter]
            incoming.append(
                _samsung_raw_row(
                    quarter=quarter,
                    inventory=inventory,
                    group_inventory=group_inventory,
                    inventory_scope=inventory_scope,
                    report=report,
                    snapshot_path=snapshot_path,
                    snapshot_hash=snapshot_hash,
                    revenue=revenue,
                    operating_profit=operating_profit,
                    reported_unit=segment_unit,
                )
            )
        return _merge_korea_raw_rows(self.raw_csv, incoming)

    def _collect_skhynix(self, targets: set[str], *, force: bool) -> int:
        reports = self._discover_reports("sk_hynix", targets)
        selected = select_latest_dart_revisions(reports, target_quarters=targets)
        if not selected:
            return 0
        existing_manifest = _read_csv_rows(self.sk_hynix_manifest)
        selected = self._skip_unchanged_reports(
            selected,
            existing_manifest,
            force=force,
            report_type_suffixes=("report",),
        )
        if not selected:
            return 0

        manifest_rows = list(existing_manifest)
        facts: dict[str, tuple[Any, DartReport, str, str]] = {}
        for quarter, report in sorted(selected.items()):
            try:
                content, snapshot_path = self._fetch_skhynix_financials(report)
                facts[quarter] = (
                    parse_skhynix_financial_html(content),
                    report,
                    snapshot_path,
                    raw_content_sha256(content),
                )
            except (OSError, ValueError) as exc:
                logger.warning("SK 海力士 DART 解析失败 [%s %s]: %s", quarter, report.rcp_no, exc)

        incoming: list[dict[str, str]] = []
        for quarter, (fact, report, snapshot_path, snapshot_hash) in sorted(facts.items()):
            annual_cost = fact.cost_of_revenue_annual_krw_million
            used_cost = fact.cost_of_revenue_quarter_krw_million
            derivation = "direct_dart_consolidated_cost_of_revenue"
            prior_row: dict[str, str] | None = None
            if quarter.endswith("Q4"):
                prior_quarter = f"{int(quarter[:4])}Q3"
                prior_row = self._ensure_skhynix_prior_9m(
                    prior_quarter,
                    selected=selected,
                    existing_manifest=existing_manifest,
                    force=force,
                )
                prior_cost = _as_float(
                    prior_row.get("prior_9m_cost_of_revenue_krw_million") if prior_row else ""
                )
                if prior_cost is None:
                    prior_cost = self._load_skhynix_9m_cost(prior_row)
                if prior_cost is None or annual_cost is None:
                    logger.warning("SK 海力士 Q4 缺少年度/9M营业成本，跳过 [%s]", quarter)
                    continue
                used_cost = annual_cost - prior_cost
                if used_cost <= 0:
                    logger.warning("SK 海力士 Q4成本差分非正，跳过 [%s]", quarter)
                    continue
                derivation = (
                    f"annual_minus_9m_dart;annual_rcp_no={report.rcp_no};"
                    f"prior_9m_rcp_no={prior_row.get('prior_9m_rcp_no', '') if prior_row else ''};"
                    f"prior_9m_cost_of_revenue_krw={prior_cost / 1000:.3f}"
                )
            if used_cost is None:
                continue
            manifest_row = _sk_manifest_row(
                quarter=quarter,
                report=report,
                snapshot_path=snapshot_path,
                snapshot_hash=snapshot_hash,
                inventory=fact.inventory_krw_million,
                reported_cost=annual_cost or used_cost,
                used_cost=used_cost,
                derivation=derivation,
                prior_row=prior_row,
            )
            manifest_rows = _upsert_manifest_row(
                manifest_rows,
                manifest_row,
                key=("report_quarter",),
            )
            incoming.append(
                _sk_raw_row(
                    quarter=quarter,
                    report=report,
                    inventory=fact.inventory_krw_million,
                    used_cost=used_cost,
                    annual_cost=annual_cost,
                    derivation=derivation,
                    snapshot_path=snapshot_path,
                    snapshot_hash=snapshot_hash,
                )
            )
        self._write_manifest(
            self.sk_hynix_manifest, manifest_rows, SK_HYNIX_SOURCE_MANIFEST_COLUMNS
        )
        return _merge_korea_raw_rows(self.raw_csv, incoming)

    def _ensure_skhynix_prior_9m(
        self,
        quarter: str,
        *,
        selected: dict[str, DartReport],
        existing_manifest: list[dict[str, str]],
        force: bool,
    ) -> dict[str, str] | None:
        existing = next(
            (row for row in existing_manifest if row.get("report_quarter") == quarter), None
        )
        report = selected.get(quarter)
        if report is None and existing is not None and not force:
            return existing
        if report is None:
            discovered = self._discover_reports("sk_hynix", {quarter})
            report = select_latest_dart_revisions(
                discovered,
                target_quarters={quarter},
            ).get(quarter)
            if report is None:
                return existing
        try:
            content, snapshot_path = self._fetch_skhynix_financials(report)
            fact = parse_skhynix_financial_html(content)
            cumulative = fact.cost_of_revenue_cumulative_krw_million
            if cumulative is None:
                return existing
            return {
                "report_quarter": quarter,
                "report_rcp_no": report.rcp_no,
                "report_source_url": report.source_url,
                "report_snapshot_path": snapshot_path,
                "report_snapshot_sha256": raw_content_sha256(content),
                "prior_9m_rcp_no": report.rcp_no,
                "prior_9m_source_url": report.source_url,
                "prior_9m_snapshot_path": snapshot_path,
                "prior_9m_snapshot_sha256": raw_content_sha256(content),
                "prior_9m_cost_of_revenue_krw_million": str(int(cumulative)),
            }
        except (OSError, ValueError) as exc:
            logger.warning("SK 海力士 Q4支撑报告解析失败 [%s]: %s", quarter, exc)
            return existing

    def _load_skhynix_9m_cost(self, row: dict[str, str] | None) -> float | None:
        if not row:
            return None
        path = row.get("prior_9m_snapshot_path") or row.get("report_snapshot_path")
        if not path:
            return None
        snapshot = Path(path)
        if not snapshot.is_absolute():
            snapshot = self.paths.raw_root / snapshot
        try:
            content = snapshot.read_bytes()
        except OSError:
            return None
        try:
            fact = parse_skhynix_financial_html(content)
        except ValueError:
            return None
        return fact.cost_of_revenue_cumulative_krw_million

    def _discover_reports(self, company: str, targets: set[str]) -> list[DartReport]:
        if not targets:
            return []
        start_quarter = min(targets)
        end_quarter = max(targets)
        start_year, start_number = _quarter_parts(start_quarter)
        end_year, end_number = _quarter_parts(end_quarter)
        start_date = date(start_year, (start_number - 1) * 3 + 1, 1)
        end_date = min(date.today(), _quarter_end(end_year, end_number) + timedelta(days=120))
        session = self._get_session()
        discovered: list[DartReport] = []
        for window_start, window_end in _discovery_windows(start_date, end_date):
            params: list[tuple[str, str]] = [
                ("currentPage", "1"),
                ("maxResults", "100"),
                ("maxLinks", "10"),
                ("sort", "date"),
                ("series", "desc"),
                ("textCrpCik", COMPANIES[company]["corp_code"]),
                ("textCrpNm", COMPANIES[company]["query"]),
                ("pageGubun", "corp"),
                ("autoSearchCorp", "Y"),
                ("startDate", window_start.strftime("%Y%m%d")),
                ("endDate", window_end.strftime("%Y%m%d")),
                ("publicType", "A001"),
                ("publicType", "A002"),
                ("publicType", "A003"),
            ]
            try:
                session.get(
                    "https://dart.fss.or.kr/dsab001/main.do",
                    headers=DART_HEADERS,
                    timeout=self.timeout,
                )
                response = session.post(
                    DART_SEARCH_URL,
                    data=params,
                    headers={
                        **DART_HEADERS,
                        "Referer": "https://dart.fss.or.kr/dsab001/main.do",
                    },
                    timeout=self.timeout,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "DART 报告发现请求失败 [%s %s~%s]: %s",
                    company,
                    window_start,
                    window_end,
                    exc,
                )
                continue
            content = response_content_bytes(response)
            if response.status_code != 200 or b"errorWrap" in content:
                logger.warning(
                    "DART 报告发现响应不可用 [%s %s~%s]: HTTP %s",
                    company,
                    window_start,
                    window_end,
                    response.status_code,
                )
                continue
            discovered.extend(parse_dart_search_results(content, company=company))
        return [report for report in discovered if report.report_quarter in targets]

    def _get_session(self) -> Any:
        if self.session is not None:
            return self.session
        self.session = requests.Session(impersonate="chrome120")
        return self.session

    def _fetch_samsung_section(
        self,
        report: DartReport,
        *,
        selector_kind: str,
    ) -> tuple[bytes, str]:
        if selector_kind == "inventory":
            selectors = ("8. 기타 재무에 관한 사항", "기타 재무에 관한 사항", "7. 기타 참고사항")
            parser = parse_samsung_inventory_html
            suffix = "inventory_by_division"
        else:
            selectors = (
                "7. 기타 참고사항",
                "사업부문별 요약 재무 현황",
                "기타 재무에 관한 사항",
                "II. 사업의 내용",
            )
            parser = parse_samsung_segment_html
            suffix = "business_segment_summary"
        for row in _read_csv_rows(self.samsung_manifest):
            if row.get("report_quarter") != report.report_quarter:
                continue
            if row.get("report_rcp_no") != report.rcp_no:
                continue
            path_ref = row.get("local_snapshot_path", "")
            is_inventory_snapshot = "inventory_by_division" in path_ref
            is_segment_snapshot = (
                "segment_summary" in row.get("report_type", "") or "segment_summary" in path_ref
            )
            if (selector_kind == "inventory" and not is_inventory_snapshot) or (
                selector_kind == "segment" and not is_segment_snapshot
            ):
                continue
            snapshot = Path(path_ref)
            if not snapshot.is_absolute():
                snapshot = self.paths.raw_root / snapshot
            if not snapshot.exists():
                continue
            cached_content = snapshot.read_bytes()
            parser(cached_content)
            return cached_content, raw_snapshot_path_value(snapshot, self.paths.raw_root)
        filename = (
            f"samsung_electronics_{report.report_quarter}_{report.report_type}_"
            f"{report.rcp_no}_{suffix}.html"
        )
        cached_path = self.filings_dir / filename
        if cached_path.exists():
            cached_content = cached_path.read_bytes()
            parser(cached_content)
            return cached_content, raw_snapshot_path_value(cached_path, self.paths.raw_root)
        main_content = self._load_main_report(report)
        nodes = parse_dart_toc_nodes(main_content)
        candidate_nodes = [
            node for node in nodes if any(selector in node.text for selector in selectors)
        ]
        if not candidate_nodes:
            candidate_nodes = nodes
        last_error: Exception | None = None
        for node in candidate_nodes:
            try:
                content = self._get_bytes(build_dart_viewer_url(node))
                parser(content)
                filename = (
                    f"samsung_electronics_{report.report_quarter}_{report.report_type}_"
                    f"{report.rcp_no}_{suffix}.html"
                )
                path = self._write_snapshot(filename, content)
                return content, raw_snapshot_path_value(path, self.paths.raw_root)
            except (OSError, ValueError) as exc:
                last_error = exc
                continue
        raise ValueError(f"三星 DART viewer 未找到可解析的 {selector_kind} 节点: {last_error}")

    def _fetch_skhynix_financials(self, report: DartReport) -> tuple[bytes, str]:
        for row in _read_csv_rows(self.sk_hynix_manifest):
            if row.get("report_quarter") != report.report_quarter:
                continue
            if row.get("report_rcp_no") != report.rcp_no:
                continue
            path_ref = row.get("report_snapshot_path", "")
            snapshot = Path(path_ref)
            if not snapshot.is_absolute():
                snapshot = self.paths.raw_root / snapshot
            if not snapshot.exists():
                continue
            cached_content = snapshot.read_bytes()
            parse_skhynix_financial_html(cached_content)
            return cached_content, raw_snapshot_path_value(snapshot, self.paths.raw_root)
        filename = (
            f"sk_hynix_dart_{report.report_quarter}_{report.report_type}_"
            "consolidated_financial_statements.html"
        )
        cached_path = self.filings_dir / filename
        if cached_path.exists():
            cached_content = cached_path.read_bytes()
            parse_skhynix_financial_html(cached_content)
            return cached_content, raw_snapshot_path_value(cached_path, self.paths.raw_root)
        main_content = self._load_main_report(report)
        nodes = parse_dart_toc_nodes(main_content)
        candidate_nodes = [node for node in nodes if "2. 연결재무제표" in node.text]
        if not candidate_nodes:
            raise ValueError(f"SK 海力士 DART 未找到连接财务报表节点: {report.rcp_no}")
        last_error: Exception | None = None
        for node in candidate_nodes:
            try:
                content = self._get_bytes(build_dart_viewer_url(node))
                parse_skhynix_financial_html(content)
                path = self._write_snapshot(filename, content)
                return content, raw_snapshot_path_value(path, self.paths.raw_root)
            except (OSError, ValueError) as exc:
                last_error = exc
        raise ValueError(f"SK 海力士 DART viewer 解析失败: {last_error}")

    def _get_bytes(self, url: str) -> bytes:
        response = self._get_session().get(url, headers=DART_HEADERS, timeout=self.timeout)
        content = response_content_bytes(response)
        if response.status_code != 200 or not content:
            raise OSError(f"DART HTTP {response.status_code}: {url}")
        return content

    def _load_main_report(self, report: DartReport) -> bytes:
        cached = self._main_cache.get(report.rcp_no)
        if cached is None:
            cached = self._get_bytes(DART_MAIN_URL.format(rcp_no=report.rcp_no))
            self._main_cache[report.rcp_no] = cached
        return cached

    def _write_snapshot(self, filename: str, content: bytes) -> Path:
        self.filings_dir.mkdir(parents=True, exist_ok=True)
        path = self.filings_dir / filename
        if not path.exists() or path.read_bytes() != content:
            path.write_bytes(content)
        return path

    def _write_manifest(self, path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = [{column: row.get(column, "") for column in columns} for row in rows]
        normalized.sort(key=lambda row: (row.get("report_quarter", ""), row.get("report_type", "")))
        temp = path.with_suffix(path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(normalized)
        temp.replace(path)

    def _skip_unchanged_reports(
        self,
        selected: dict[str, DartReport],
        existing_manifest: list[dict[str, str]],
        *,
        force: bool,
        report_type_suffixes: tuple[str, ...],
        raw_rows: list[dict[str, str]] | None = None,
    ) -> dict[str, DartReport]:
        if force:
            return selected
        result: dict[str, DartReport] = {}
        for quarter, report in selected.items():
            same_report_rows = [
                row
                for row in existing_manifest
                if row.get("report_quarter") == quarter
                and row.get("report_rcp_no") == report.rcp_no
            ]
            if report_type_suffixes == ("interim_report", "business_report"):
                complete = any(
                    "inventory_by_division" in row.get("local_snapshot_path", "")
                    for row in same_report_rows
                ) and any(
                    "segment_summary" in row.get("report_type", "")
                    or "segment_summary" in row.get("local_snapshot_path", "")
                    for row in same_report_rows
                )
            else:
                complete = bool(same_report_rows)
            if complete and report_type_suffixes == ("interim_report", "business_report"):
                raw_row = next(
                    (
                        row
                        for row in (raw_rows or [])
                        if row.get("symbol") == "005930.KS_DS"
                        and row.get("report_quarter") == quarter
                    ),
                    None,
                )
                if raw_row is None or not raw_row.get("ds_revenue_krw"):
                    complete = False
            if not complete:
                result[quarter] = report
        return result

    def _target_quarters(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> set[str]:
        upper = min(end_date or date.today(), date.today())
        if start_date is None and end_date is None:
            # 普通季度同步只检查最近四个已经结束的季度；历史缺口通过显式窗口回填。
            lower = max(date(2016, 1, 1), upper - timedelta(days=370))
        else:
            lower = start_date or date(2016, 1, 1)
        result: set[str] = set()
        for year in range(lower.year, upper.year + 1):
            for quarter in range(1, 5):
                if lower <= _quarter_end(year, quarter) <= upper:
                    result.add(f"{year}Q{quarter}")
        return result


def _quarter_parts(quarter: str) -> tuple[int, int]:
    return int(quarter[:4]), int(quarter[-1])


def _quarter_end(year: int, quarter: int) -> date:
    return date(year, (3, 6, 9, 12)[quarter - 1], (31, 30, 30, 31)[quarter - 1])


def _discovery_windows(start_date: date, end_date: date) -> list[tuple[date, date]]:
    """将 DART 报告发现范围拆成稳定的有限日期窗口。"""
    windows: list[tuple[date, date]] = []
    window_start = start_date
    while window_start <= end_date:
        window_end = min(
            end_date,
            window_start + timedelta(days=DART_DISCOVERY_WINDOW_DAYS),
        )
        windows.append((window_start, window_end))
        window_start = window_end + timedelta(days=1)
    return windows


def _canonical_samsung_report_type(
    report_quarter: str,
    report_type: str,
    snapshot_path: str,
) -> str:
    """将历史 Manifest 的 interim 命名归一为 DART 报告期类型。"""
    try:
        _year, quarter_number = _quarter_parts(report_quarter)
    except (TypeError, ValueError):
        return report_type
    base = {
        1: "quarterly_report",
        2: "half_year_report",
        3: "quarterly_report",
        4: "business_report",
    }.get(quarter_number, report_type)
    is_segment = "segment_summary" in report_type or "segment_summary" in snapshot_path
    return f"{base}_segment_summary" if is_segment else base


def _normalize_samsung_manifest_rows(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """按季度和快照类型去除旧 interim/quarterly 重复登记。"""
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        normalized = dict(row)
        normalized["report_type"] = _canonical_samsung_report_type(
            row.get("report_quarter", ""),
            row.get("report_type", ""),
            row.get("local_snapshot_path", ""),
        )
        key = (normalized.get("report_quarter", ""), normalized["report_type"])
        by_key[key] = normalized
    return sorted(
        by_key.values(),
        key=lambda row: (row.get("report_quarter", ""), row.get("report_type", "")),
    )


def _quarterly_segment_values(
    facts: dict[str, tuple[float, float, DartReport, str, str, str]],
) -> dict[str, tuple[float, float, DartReport, str, str, str]]:
    result: dict[str, tuple[float, float, DartReport, str, str, str]] = {}
    for year in sorted({quarter[:4] for quarter in facts}):
        previous: tuple[float, float] | None = None
        for number in range(1, 5):
            quarter = f"{year}Q{number}"
            fact = facts.get(quarter)
            if fact is None:
                previous = None
                continue
            revenue, operating_profit, report, path, digest, unit = fact
            if number == 1:
                quarterly = (revenue, operating_profit)
            elif previous is not None:
                quarterly = (revenue - previous[0], operating_profit - previous[1])
            else:
                previous = (revenue, operating_profit)
                continue
            # DS 营业利润在下行周期可以为负；只禁止收入累计差分为负，
            # 否则会把真实亏损季度误当作解析失败。
            if quarterly[0] < 0:
                previous = (revenue, operating_profit)
                continue
            result[quarter] = (quarterly[0], quarterly[1], report, path, digest, unit)
            previous = (revenue, operating_profit)
    return result


def _samsung_raw_row(
    *,
    quarter: str,
    inventory: float,
    group_inventory: float,
    inventory_scope: str,
    report: DartReport,
    snapshot_path: str,
    snapshot_hash: str,
    revenue: float,
    operating_profit: float,
    reported_unit: str,
) -> dict[str, str]:
    year, number = _quarter_parts(quarter)
    inventory_trillion = inventory / 1_000_000
    group_trillion = group_inventory / 1_000_000
    # parser 已将 ``억원`` 源值统一为百万韩元；这里与库存表一样换算为
    # trillion KRW。reported_unit 仍写入解析事实用于血缘审计。
    revenue_trillion = revenue / 1_000_000
    operating_profit_trillion = operating_profit / 1_000_000
    cost_trillion = revenue_trillion - operating_profit_trillion
    source = (
        "SAMSUNG_DART_BUSINESS_REPORT_C_INVENTORY_BY_DIVISION"
        if number == 4
        else "SAMSUNG_DART_INTERIM_BUSINESS_REPORT_C_INVENTORY_BY_DIVISION"
    )
    return {
        "symbol": "005930.KS_DS",
        "report_quarter": quarter,
        "trade_date": _quarter_end(year, number).isoformat(),
        "inventory_krw": f"{inventory_trillion:.6f}",
        "cost_of_revenue_krw": f"{cost_trillion:.6f}",
        "cost_of_revenue_annual_raw": "",
        "cost_of_revenue_derivation": (
            "ds_segment_extracted;ds_revenue_minus_ds_operating_profit;"
            f"segment_reported_unit={reported_unit};report_rcp_no={report.rcp_no}"
        ),
        "unit": "trillion_krw",
        "group_total_inventory_krw": f"{group_trillion:.6f}",
        "release_date": report.filing_date.isoformat(),
        "source_period_end": _quarter_end(year, number).isoformat(),
        "fiscal_period_raw": f"{number}Q{str(year)[-2:]}",
        "source": source,
        "source_url": report.source_url or f"{DART_REPORT_URL_PREFIX}{report.rcp_no}",
        "collected_at": now_utc_iso(),
        "raw_content_sha256": snapshot_hash,
        "raw_snapshot_path": snapshot_path,
        "ds_revenue_krw": f"{revenue_trillion:.6f}",
        "ds_operating_profit_krw": f"{operating_profit_trillion:.6f}",
        "cost_of_revenue_source": "proxy_ds_revenue_minus_ds_operating_profit",
        "inventory_scope": inventory_scope,
        "memory_inventory_status": "not_disclosed",
    }


def _sk_raw_row(
    *,
    quarter: str,
    report: DartReport,
    inventory: float,
    used_cost: float,
    annual_cost: float | None,
    derivation: str,
    snapshot_path: str,
    snapshot_hash: str,
) -> dict[str, str]:
    year, number = _quarter_parts(quarter)
    return {
        "symbol": "000660.KS",
        "report_quarter": quarter,
        "trade_date": _quarter_end(year, number).isoformat(),
        "inventory_krw": f"{inventory / 1000:.3f}",
        "cost_of_revenue_krw": f"{used_cost / 1000:.3f}",
        "cost_of_revenue_annual_raw": f"{annual_cost / 1000:.3f}" if annual_cost else "",
        "cost_of_revenue_derivation": derivation,
        "unit": "billion_krw",
        "group_total_inventory_krw": "",
        "release_date": report.filing_date.isoformat(),
        "source_period_end": _quarter_end(year, number).isoformat(),
        "fiscal_period_raw": f"{number}Q{str(year)[-2:]}",
        "source": "SK_HYNIX_DART_PERIODIC_REPORT",
        "source_url": report.source_url or f"{DART_REPORT_URL_PREFIX}{report.rcp_no}",
        "collected_at": now_utc_iso(),
        "raw_content_sha256": snapshot_hash,
        "raw_snapshot_path": snapshot_path,
        "ds_revenue_krw": "",
        "ds_operating_profit_krw": "",
        "cost_of_revenue_source": (
            "official_consolidated_cost_of_revenue_derived_q4"
            if number == 4
            else "official_consolidated_cost_of_revenue"
        ),
        "inventory_scope": "",
        "memory_inventory_status": "",
    }


def _sk_manifest_row(
    *,
    quarter: str,
    report: DartReport,
    snapshot_path: str,
    snapshot_hash: str,
    inventory: float,
    reported_cost: float,
    used_cost: float,
    derivation: str,
    prior_row: dict[str, str] | None,
) -> dict[str, str]:
    return {
        "report_quarter": quarter,
        "report_type": report.report_type,
        "report_rcp_no": report.rcp_no,
        "report_source_url": report.source_url,
        "report_snapshot_path": snapshot_path,
        "report_snapshot_sha256": snapshot_hash,
        "inventory_krw_million": str(int(inventory)),
        "reported_cost_of_revenue_krw_million": str(int(reported_cost)),
        "cost_of_revenue_used_krw_million": str(int(used_cost)),
        "cost_of_revenue_derivation": derivation,
        "prior_9m_rcp_no": (prior_row or {}).get("prior_9m_rcp_no", ""),
        "prior_9m_source_url": (prior_row or {}).get("prior_9m_source_url", ""),
        "prior_9m_snapshot_path": (prior_row or {}).get("prior_9m_snapshot_path", ""),
        "prior_9m_snapshot_sha256": (prior_row or {}).get("prior_9m_snapshot_sha256", ""),
        "prior_9m_cost_of_revenue_krw_million": (
            (prior_row or {}).get("prior_9m_cost_of_revenue_krw_million", "")
        ),
    }


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _upsert_manifest_row(
    rows: list[dict[str, str]],
    incoming: dict[str, str],
    *,
    key: tuple[str, ...],
) -> list[dict[str, str]]:
    incoming_key = tuple(incoming.get(field, "") for field in key)
    result = [row for row in rows if tuple(row.get(field, "") for field in key) != incoming_key]
    result.append(incoming)
    return result


def _merge_korea_raw_rows(path: Path, incoming: list[dict[str, str]]) -> int:
    if not incoming:
        return 0
    existing = _read_csv_rows(path)
    by_key = {(row.get("symbol", ""), row.get("report_quarter", "")): row for row in existing}
    changed = 0
    for row in incoming:
        key = (row["symbol"], row["report_quarter"])
        old = by_key.get(key)
        if old is None or _raw_row_payload(row) != _raw_row_payload(old):
            changed += 1
            by_key[key] = row
    rows = sorted(
        by_key.values(),
        key=lambda row: (row.get("symbol", ""), row.get("report_quarter", "")),
        reverse=True,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=KOREA_RAW_COLUMNS)
        writer.writeheader()
        writer.writerows(
            {column: row.get(column, "") for column in KOREA_RAW_COLUMNS} for row in rows
        )
    temp.replace(path)
    return changed


def _raw_row_payload(row: dict[str, str]) -> tuple[tuple[str, str], ...]:
    """忽略采集时间比较事实，避免同一快照每次同步都被视为变更。"""
    return tuple(
        sorted((key, row.get(key, "")) for key in KOREA_RAW_COLUMNS if key != "collected_at")
    )


def _as_float(value: str | None) -> float | None:
    try:
        return float(str(value or "").replace(",", "")) if str(value or "").strip() else None
    except ValueError:
        return None


__all__ = ["KoreaMemoryDartCollector"]
