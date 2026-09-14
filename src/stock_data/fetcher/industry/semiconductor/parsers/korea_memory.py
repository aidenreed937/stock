"""韩国半导体存储龙头 (三星电子 DS 事业部 / SK海力士) 官方财报解析器.

硬约束要求：
1. 信源：三星使用官方 DART Interim/Business Report 的分部存货表；SK 海力士统一使用官方 DART 定期报告.
2. 三星分部：严格提取 Device Solutions (DS) 半导体事业部，禁止混入集团合并报表；纯存储库存未单独披露.
3. 门禁防护：DS 存货占集团总存货比例断言在 [0.35, 0.70] 区间内；2021Q1
   之前的旧组织表允许历史低位至 0.20.
4. 汇率双轨：存货用期末即期汇率，成本代理用季度均价折算为百万美元；三星 DS 成本代理不是官方 COGS.
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.semiconductor.fx import (
    convert_krw_to_usd_million,
    get_krw_usd_rates,
)
from stock_data.fetcher.industry.semiconductor.models import SemiconductorInventoryRecord

logger = logging.getLogger(__name__)

# 三星 IR 仅保留为兼容缺省链接；实际三星分部库存记录使用 DART。
SAMSUNG_IR_ENGLISH_URL = (
    "https://www.samsung.com/global/ir/financial-information/quarterly-results/"
)
SK_HYNIX_DART_SOURCE = "SK_HYNIX_DART_PERIODIC_REPORT"
SK_HYNIX_DART_URL_PREFIX = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
SAMSUNG_DART_SOURCE_PREFIX = "SAMSUNG_DART_"
SAMSUNG_DART_URL_PREFIX = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="

# 三星电子 DS 事业部存货占集团合并总存货的安全合理区间
SAMSUNG_DS_RATIO_MIN = 0.35
SAMSUNG_DS_LEGACY_RATIO_MIN = 0.20
SAMSUNG_DS_RATIO_MAX = 0.70


def samsung_ds_ratio_minimum(report_quarter: str) -> float:
    """返回三星 DS 存货占比的报告期门禁下限。"""
    return SAMSUNG_DS_LEGACY_RATIO_MIN if report_quarter < "2021Q1" else SAMSUNG_DS_RATIO_MIN


def validate_samsung_ds_ratio(
    ds_inventory: float,
    group_inventory: float,
    *,
    minimum_ratio: float = SAMSUNG_DS_RATIO_MIN,
) -> bool:
    """验证三星 DS 半导体事业部存货占集团总存货比例是否在合理区间内.

    防止网页或报表改版导致抓取到集团合并值，严重污染 IDM DOI 口径.
    """
    if group_inventory <= 0:
        raise ValueError(f"三星集团总存货必须为正数: {group_inventory}")
    if ds_inventory <= 0:
        raise ValueError(f"三星 DS 事业部存货必须为正数: {ds_inventory}")

    ratio = ds_inventory / group_inventory
    if ratio < minimum_ratio or ratio > SAMSUNG_DS_RATIO_MAX:
        raise ValueError(
            f"三星 DS 存货比例异常 ({ratio:.1%})，不在安全区间 "
            f"[{minimum_ratio:.0%}, {SAMSUNG_DS_RATIO_MAX:.0%}] 内: "
            f"ds={ds_inventory}, group={group_inventory}"
        )
    return True


def load_korea_memory_raw_csv(
    file_path: Path | str,
    runtime: Any = None,
) -> list[SemiconductorInventoryRecord]:
    """从韩国存储龙头 RAW CSV 载入并按 IAS 21 双轨折算为标准化记录模型."""
    path = Path(file_path)
    if not path.exists():
        return []

    records: list[SemiconductorInventoryRecord] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"].strip().upper()
            report_quarter = row["report_quarter"].strip().upper()
            trade_date_str = row["trade_date"].strip()
            trade_date = date.fromisoformat(trade_date_str)

            inv_raw_str = row["inventory_krw"].strip()
            cogs_raw_str = row["cost_of_revenue_krw"].strip()
            unit = (row.get("unit") or "trillion_krw").strip().lower()
            inv_raw = float(inv_raw_str.replace(",", ""))
            cogs_raw = float(cogs_raw_str.replace(",", ""))

            # 若为三星且提供了集团总存货，进行分部比例断言
            group_inv_str = (row.get("group_total_inventory_krw") or "").strip()
            if symbol == "005930.KS_DS" and group_inv_str:
                group_inv = float(group_inv_str.replace(",", ""))
                minimum_ratio = samsung_ds_ratio_minimum(report_quarter)
                validate_samsung_ds_ratio(
                    inv_raw,
                    group_inv,
                    minimum_ratio=minimum_ratio,
                )

            source = (row.get("source") or "").strip()
            source_url = (row.get("source_url") or "").strip()
            if symbol == "005930.KS_DS":
                if not source.startswith(SAMSUNG_DART_SOURCE_PREFIX):
                    raise ValueError(
                        "三星 DS RAW 必须统一来自 DART Interim/Business Report: "
                        f"{report_quarter} source={source or '<empty>'}"
                    )
                if not source_url.startswith(SAMSUNG_DART_URL_PREFIX):
                    raise ValueError(
                        "三星 DS RAW 的 source_url 必须为 DART 报告页: "
                        f"{report_quarter} source_url={source_url or '<empty>'}"
                    )
            if symbol == "000660.KS":
                if source != SK_HYNIX_DART_SOURCE:
                    raise ValueError(
                        "SK 海力士 RAW 必须统一来自 DART 定期报告: "
                        f"{report_quarter} source={source or '<empty>'}"
                    )
                if not source_url.startswith(SK_HYNIX_DART_URL_PREFIX):
                    raise ValueError(
                        "SK 海力士 RAW 的 source_url 必须为 DART 报告页: "
                        f"{report_quarter} source_url={source_url or '<empty>'}"
                    )

            # 双轨折算为百万美元
            inv_usd_m, cogs_usd_m = convert_krw_to_usd_million(
                inv_raw,
                cogs_raw,
                report_quarter,
                unit=unit,
                runtime=runtime,
            )

            spot_rate, avg_rate = get_krw_usd_rates(report_quarter, runtime=runtime)
            release_date_str = (row.get("release_date") or "").strip()
            release_date = date.fromisoformat(release_date_str) if release_date_str else None
            source_period_end_str = (row.get("source_period_end") or "").strip()
            source_period_end = (
                date.fromisoformat(source_period_end_str) if source_period_end_str else trade_date
            )

            derivation_tags = [
                f"krw_fx_converted(spot={spot_rate},avg={avg_rate})",
                f"unit={unit}",
            ]
            source_derivation = (row.get("cost_of_revenue_derivation") or "").strip()
            if source_derivation:
                derivation_tags.insert(0, source_derivation)
            cost_source = (row.get("cost_of_revenue_source") or "").strip()
            inventory_scope = (row.get("inventory_scope") or "").strip()
            memory_inventory_status = (row.get("memory_inventory_status") or "").strip()
            if symbol == "005930.KS_DS":
                derivation_tags.append("ds_segment_extracted")
                derivation_tags.append(
                    "ds_inventory_source=business_report_c_inventory_by_division"
                )
                inventory_scope = inventory_scope or "ds_division"
                derivation_tags.append(f"inventory_scope={inventory_scope}")
                memory_inventory_status = memory_inventory_status or "not_disclosed"
                derivation_tags.append(f"memory_inventory_status={memory_inventory_status}")
                cost_source = cost_source or "proxy_ds_revenue_minus_ds_operating_profit"
                derivation_tags.append(f"cost_source={cost_source}")
            elif not cost_source:
                cost_source = "official_consolidated_cost_of_revenue"

            records.append(
                SemiconductorInventoryRecord(
                    symbol=symbol,
                    report_quarter=report_quarter,
                    trade_date=trade_date,
                    inventory_usd_million=inv_usd_m,
                    cost_of_revenue_usd_million=cogs_usd_m,
                    subsector="memory",
                    unit=unit,
                    source=source or SK_HYNIX_DART_SOURCE,
                    source_url=source_url or SK_HYNIX_DART_URL_PREFIX,
                    release_date=release_date,
                    data_status="actual",
                    collected_at=(row.get("collected_at") or "").strip(),
                    inventory_usd_raw=inv_raw_str,
                    cost_of_revenue_usd_raw=cogs_raw_str,
                    source_period_end=source_period_end,
                    fiscal_period=(row.get("fiscal_period_raw") or report_quarter).strip(),
                    raw_content_sha256=(row.get("raw_content_sha256") or "").strip(),
                    raw_snapshot_path=(row.get("raw_snapshot_path") or "").strip(),
                    cost_of_revenue_annual_raw=(row.get("cost_of_revenue_annual_raw") or "").strip()
                    or None,
                    cost_of_revenue_derivation=";".join(derivation_tags),
                    ds_revenue_krw_raw=(row.get("ds_revenue_krw") or "").strip() or None,
                    ds_operating_profit_krw_raw=(row.get("ds_operating_profit_krw") or "").strip()
                    or None,
                    cost_of_revenue_source=cost_source,
                    inventory_scope=inventory_scope,
                    memory_inventory_status=memory_inventory_status,
                )
            )

    return records
