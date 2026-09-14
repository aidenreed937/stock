"""台湾存储龙头月度营运营收先导指标采集器 (TaiwanMemoryLeadCollector)。

涵盖标的:
- 南亚科技 (2408.TW): 全球第四大 DRAM 原厂 (DRAM IDM 景气水温)
- 威刚科技 (3260.TW): 全球第二大独立存储模组厂 (渠道提货与模组动销)

流程规范严格对标 tsmc.py:
1. 每月 10 日前跟踪台湾证交所 MOPS 与公司投资者月度营运营收；
2. 原始响应二进制 Gzip 存证归档至 RAW 目录，计算 SHA256 哈希与快照相对路径；
3. 解析为不可变 TaiwanMemoryLeadRecord，完整保留源端字段 (company_name_raw, net_revenue_raw, yoy_change_raw)；
4. 输出按标的与月份排序的记录列表，供下游 Curated 转换并计算出货增速。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.models import TaiwanMemoryLeadRecord
from stock_data.fetcher.industry.semiconductor.parsers import (
    parse_taiwan_memory_monthly_revenue_dict,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

TAIWAN_MEMORY_TARGETS: tuple[dict[str, str], ...] = (
    {
        "symbol": "2408",
        "name": "南亚科技",
        "full_name": "南亞科技股份有限公司",
        "role": "DRAM_IDM",
        "url": "https://mops.twse.com.tw/mops/api/t05st10_ifrs",
    },
    {
        "symbol": "3260",
        "name": "威刚科技",
        "full_name": "威剛科技股份有限公司",
        "role": "MODULE",
        "url": "https://mops.twse.com.tw/mops/api/t05st10_ifrs",
    },
)
TAIWAN_MEMORY_SOURCE_NAME = "taiwan_memory"
DEFAULT_START_YEAR = 2016


class TaiwanMemoryLeadCollector:
    """台湾存储龙头月度营运营收采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 15,
        impersonate: str = "chrome120",
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.raw_root = self.paths.raw_root
        self.timeout = timeout
        self.impersonate = impersonate

    def collect(
        self,
        force: bool = False,
        start_year: int = DEFAULT_START_YEAR,
        end_year: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[TaiwanMemoryLeadRecord]:
        """在线采集南亚科技与威刚科技的月度营运营收原始记录。"""
        del force  # MOPS 当前无本地响应缓存；强制刷新由上层保留并传递到此。
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError(f"台湾存储营收日期范围无效: {start_date} > {end_date}")
        self.paths.taiwan_memory_dir.mkdir(parents=True, exist_ok=True)
        first_year = start_date.year if start_date is not None else start_year
        last_year = end_date.year if end_date is not None else end_year or date.today().year
        records: list[TaiwanMemoryLeadRecord] = []

        for target in TAIWAN_MEMORY_TARGETS:
            company_kwargs: dict[str, Any] = {
                "start_year": first_year,
                "end_year": last_year,
            }
            if start_date is not None:
                company_kwargs["start_date"] = start_date
            if end_date is not None:
                company_kwargs["end_date"] = end_date
            records.extend(self._collect_company(target, **company_kwargs))

        if not records:
            logger.info("未采集到台湾存储龙头月度营收数据")
            return []

        logger.info("台湾存储龙头月度营收采集完成: 共 %d 条记录", len(records))
        return sorted(records, key=lambda r: (r.symbol, r.report_month))

    def _collect_company(
        self,
        target: dict[str, str],
        *,
        start_year: int,
        end_year: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[TaiwanMemoryLeadRecord]:
        symbol = target["symbol"]
        url = target["url"]
        collected_at = now_utc_iso()
        company_records: list[TaiwanMemoryLeadRecord] = []

        session: Any = requests.Session(impersonate=self.impersonate)

        for year in range(start_year, end_year + 1):
            roc_year = year - 1911
            for month in range(1, 13):
                month_start = date(year, month, 1)
                month_end = get_month_end_date(year, month)
                if start_date is not None and month_end < start_date:
                    continue
                if end_date is not None and month_start > end_date:
                    continue
                payload = {
                    "companyId": symbol,
                    "dataType": "2",
                    "year": str(roc_year),
                    "month": str(month),
                    "subsidiaryCompanyId": "",
                }
                try:
                    resp = session.post(url, json=payload, timeout=self.timeout)
                    if resp.status_code != 200:
                        continue
                    content_bytes = response_content_bytes(resp)
                    if not content_bytes:
                        continue
                    data = resp.json()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("抓取 %s %d-%d 异常: %s", symbol, year, month, exc)
                    continue

                if data.get("code") == 406 and year == end_year:
                    # 当年尚未披露的未来月份
                    break
                if data.get("code") != 200 or not data.get("result"):
                    continue

                row = _extract_mops_result_row(
                    data["result"],
                    symbol=symbol,
                    response_datetime_raw=data.get("datetime"),
                )
                if not row:
                    continue

                snapshot_path = save_raw_snapshot(
                    TAIWAN_MEMORY_SOURCE_NAME,
                    f"taiwan_memory_{symbol}_{year}_{month:02d}.json.gz",
                    content_bytes,
                    base_dir=self.paths.semiconductor_dir,
                    compress=True,
                )
                content_hash = raw_content_sha256(content_bytes)
                snapshot_ref = raw_snapshot_path_value(snapshot_path, self.raw_root)

                parsed_records = parse_taiwan_memory_monthly_revenue_dict(
                    [row],
                    symbol=symbol,
                    source_url=url,
                    collected_at=collected_at,
                    raw_content_sha256=content_hash,
                    raw_snapshot_path=snapshot_ref,
                )
                company_records.extend(parsed_records)

        return company_records


def _extract_mops_result_row(
    result: dict[str, Any],
    *,
    symbol: str,
    release_date_raw: Any = None,
    response_datetime_raw: Any = None,
) -> dict[str, Any] | None:
    """从 MOPS API 返回的 result 结构解析单个月份数据字典。"""
    raw_data = result.get("data")
    if not isinstance(raw_data, list):
        return None
    values_by_label: dict[str, list[str]] = {}
    for item in raw_data:
        if not isinstance(item, list | tuple) or len(item) < 2:
            continue
        label = str(item[0]).strip()
        values_by_label.setdefault(label, []).append(str(item[1] or ""))

    def first_value(label: str) -> str:
        return values_by_label.get(label, [""])[0]

    percent_values = values_by_label.get("增減百分比", [])
    return {
        "symbol": symbol,
        "company_name_raw": str(result.get("companyAbbreviation") or ""),
        "report_month_raw": str(result.get("yymm") or ""),
        "net_revenue_raw": first_value("本月"),
        "last_year_revenue_raw": first_value("去年同期"),
        "yoy_change_raw": percent_values[0] if percent_values else "",
        "cumulative_revenue_raw": first_value("本年累計"),
        "cumulative_yoy_raw": percent_values[1] if len(percent_values) > 1 else "",
        "release_date_raw": str(release_date_raw or "").strip() or None,
        "source_response_datetime_raw": str(response_datetime_raw or "").strip() or None,
    }
