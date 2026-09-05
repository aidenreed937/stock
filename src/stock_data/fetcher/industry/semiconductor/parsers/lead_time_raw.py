"""芯片交付周期 RAW 快照文件加载与归档工具。"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import save_raw_snapshot
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_content_bytes,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.semiconductor.models import ChipLeadTimeRecord

logger = logging.getLogger(__name__)


def parse_lead_time_string_to_weeks(lead_time_str: str) -> float | None:
    """将分销商返回的交期字符串解析为标准周数。"""
    if not lead_time_str:
        return None
    match_weeks = re.search(r"(\d+(?:\.\d+)?)\s*(?:weeks?|周数|周)", lead_time_str, re.IGNORECASE)
    if match_weeks:
        return float(match_weeks.group(1))
    match_days = re.search(r"(\d+(?:\.\d+)?)\s*(?:days?|天数|天)", lead_time_str, re.IGNORECASE)
    if match_days:
        return round(float(match_days.group(1)) / 7.0, 1)
    return None


# Mouser 对缺货/停产 SKU 的封顶显示为 364/365 天 (>=52 周)，不是真实交期；
# "0 天" 同样是无货标记而非 0 周交期。两者均不应计入篮子均值。
LEAD_TIME_CAP_WEEKS = 52.0


def is_valid_lead_time_weeks(weeks: float | None) -> bool:
    """判断 SKU 交期是否为可用于聚合的有效真实值。"""
    return weeks is not None and 0.0 < weeks < LEAD_TIME_CAP_WEEKS


def aggregate_category_lead_times(
    sku_details: dict[str, Any],
    categories: dict[str, Any] | None = None,
) -> tuple[dict[str, float], float | None, dict[str, str]]:
    """从 SKU 明细聚合清洗后的品类均值、加权均值与排除列表。

    0 天(缺货标记)与 >=52 周(封顶显示)的 SKU 被排除且不参与加权；
    返回 (category_averages, avg_lead_time_weeks, excluded)。
    """
    categories = categories or {}
    cat_leads: dict[str, list[float]] = {}
    excluded: dict[str, str] = {}
    for sku, detail in sku_details.items():
        if not isinstance(detail, dict):
            continue
        cat = detail.get("category")
        weeks = detail.get("lead_time_weeks")
        if not is_valid_lead_time_weeks(weeks):
            excluded[sku] = str(detail.get("lead_time_raw") or weeks)
            continue
        if cat is None or weeks is None:
            excluded[sku] = str(detail.get("lead_time_raw") or weeks)
            continue
        cat_leads.setdefault(str(cat), []).append(float(weeks))

    cat_averages = {
        cat: round(sum(weeks_list) / len(weeks_list), 1)
        for cat, weeks_list in cat_leads.items()
        if weeks_list
    }
    if not cat_averages:
        return {}, None, excluded
    weights = {cat: float(categories.get(cat, {}).get("weight", 1.0)) for cat in cat_averages}
    total_weight = sum(weights.values()) or 1.0
    avg_val = round(
        sum(cat_averages[cat] * weights[cat] for cat in cat_averages) / total_weight,
        2,
    )
    return cat_averages, avg_val, excluded


def extract_lead_time_release_date(payload: object) -> date | None:
    """读取交期源响应中明确标注的发布日期/更新时间。

    Mouser 响应若不提供这些字段，不能用请求时间或交易日冒充发布日期。
    """
    if isinstance(payload, dict):
        accepted_keys = {
            "releasedate",
            "publicationdate",
            "publisheddate",
            "lastupdated",
            "lastupdatedate",
            "updatedate",
            "dataasofdate",
        }
        for key, value in payload.items():
            if str(key).replace("_", "").lower() in accepted_keys:
                parsed = _parse_iso_date(value)
                if parsed is not None:
                    return parsed
        for value in payload.values():
            parsed = extract_lead_time_release_date(value)
            if parsed is not None:
                return parsed
    elif isinstance(payload, list):
        for value in payload:
            parsed = extract_lead_time_release_date(value)
            if parsed is not None:
                return parsed
    return None


def determine_lead_time_status(avg_weeks: float, thresholds: dict[str, float] | None = None) -> str:
    """根据交付周期周数及配置阈值判定供需紧张状态。"""
    th = thresholds or {"overheating": 26.0, "tight": 18.0, "normal": 13.0}
    if avg_weeks >= th.get("overheating", 26.0):
        return "overheating"
    if avg_weeks >= th.get("tight", 18.0):
        return "tight"
    if avg_weeks >= th.get("normal", 13.0):
        return "normal"
    return "easing"


def archive_lead_time_raw_snapshot(
    raw_dir: Path,
    month_key: str,
    record: ChipLeadTimeRecord,
    cat_averages: dict[str, float],
    sku_details: dict[str, Any],
    excluded_skus: dict[str, str] | None = None,
) -> Path:
    """将实时采集结果归档到 RAW 目录。"""
    if record.release_date is None:
        raise ValueError("芯片交期 RAW 快照缺少真实 release_date，拒绝归档")
    content = {
        "report_month": month_key,
        "trade_date": record.trade_date.isoformat(),
        "avg_lead_time_weeks": record.avg_lead_time_weeks,
        "category_averages": cat_averages,
        "sku_details": sku_details,
        "excluded_skus": excluded_skus or {},
        "source": record.source,
        "source_url": record.source_url,
        "release_date": record.release_date.isoformat() if record.release_date else None,
        "data_status": record.data_status,
        "collected_at": record.collected_at,
    }
    return save_raw_snapshot(
        source_name="lead_time",
        snapshot_filename=f"chip_lead_time_{month_key}.json",
        content=content,
        base_dir=raw_dir,
    )


def load_lead_time_raw_records(
    lead_time_raw_dir: Path,
    thresholds: dict[str, float] | None = None,
    categories: dict[str, Any] | None = None,
) -> list[ChipLeadTimeRecord]:
    """从本地 RAW 目录加载芯片交期结构化快照。"""
    if not lead_time_raw_dir.exists():
        return []

    records_map: dict[str, ChipLeadTimeRecord] = {}
    raw_root = lead_time_raw_dir.parent

    for json_file in sorted(lead_time_raw_dir.glob("*.json")):
        try:
            metadata_bytes = raw_snapshot_content_bytes(json_file)
            data = json.loads(metadata_bytes.decode("utf-8"))
            m_key = data.get("report_month")
            if not m_key or "avg_lead_time_weeks" not in data:
                continue

            trade_d = _parse_iso_date(data.get("trade_date"))
            if trade_d is None:
                continue
            release_d = _parse_iso_date(data.get("release_date"))
            if release_d is None:
                logger.warning("跳过缺少真实 release_date 的芯片交期快照: %s", json_file.name)
                continue
            avg_val = float(data["avg_lead_time_weeks"])
            cat_avg = data.get("category_averages", {})
            sku_details = data.get("sku_details", {})
            # 含 SKU 明细的快照按清洗逻辑重算，保证在线采集与离线重放口径一致
            if isinstance(sku_details, dict) and sku_details:
                recomputed_cat, recomputed_avg, _ = aggregate_category_lead_times(
                    sku_details, categories
                )
                if recomputed_cat and recomputed_avg is not None:
                    cat_avg = recomputed_cat
                    avg_val = recomputed_avg
            lead_time_raw = None
            sku_details_raw = None
            if isinstance(sku_details, dict) and sku_details:
                lead_time_raw = json.dumps(
                    {
                        sku: detail.get("lead_time_raw")
                        for sku, detail in sorted(sku_details.items())
                        if isinstance(detail, dict) and detail.get("lead_time_raw")
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                sku_details_raw = json.dumps(sku_details, ensure_ascii=False, sort_keys=True)

            source_snapshot = _resolve_source_snapshot_path(
                data.get("raw_snapshot_path"), lead_time_raw_dir, raw_root
            )
            if source_snapshot is not None and source_snapshot.exists():
                source_bytes = raw_snapshot_content_bytes(source_snapshot)
                content_hash = raw_content_sha256(source_bytes)
                snapshot_path = raw_snapshot_path_value(source_snapshot, raw_root)
            else:
                content_hash = str(data.get("raw_content_sha256") or "")
                if not content_hash:
                    content_hash = raw_content_sha256(metadata_bytes)
                snapshot_path = raw_snapshot_path_value(json_file, raw_root)

            if lead_time_raw is None and data.get("lead_time_raw") is not None:
                lead_time_raw = str(data["lead_time_raw"])
            cat_avg = cat_avg if isinstance(cat_avg, dict) else {}

            records_map[m_key] = ChipLeadTimeRecord(
                report_month=m_key,
                trade_date=trade_d,
                avg_lead_time_weeks=avg_val,
                mcu_lead_time_weeks=cat_avg.get("mcu"),
                analog_lead_time_weeks=cat_avg.get("analog"),
                discrete_lead_time_weeks=cat_avg.get("discrete"),
                compute_lead_time_weeks=cat_avg.get("compute"),
                lead_time_yoy_weeks=None,
                lead_time_mom_weeks=None,
                lead_time_status=determine_lead_time_status(avg_val, thresholds),
                unit="weeks",
                source=data.get("source", "Mouser/Distributor"),
                source_url=data.get("source_url", "https://api.mouser.com"),
                release_date=release_d,
                data_status=data.get("data_status", "actual"),
                collected_at=str(data.get("collected_at") or ""),
                raw_content_sha256=content_hash,
                raw_snapshot_path=snapshot_path,
                lead_time_raw=lead_time_raw,
                sku_details_raw=sku_details_raw,
            )
        except Exception as e:
            logger.warning("解析芯片交期 RAW JSON 快照 [%s] 失败: %s", json_file.name, e)

    records = list(records_map.values())
    records.sort(key=lambda r: r.trade_date)
    return records


def _resolve_source_snapshot_path(
    value: object,
    lead_time_raw_dir: Path,
    raw_root: Path,
) -> Path | None:
    """解析元数据中的相对源文件路径，兼容旧快照。"""
    if not value:
        return None
    candidate = Path(str(value))
    if candidate.is_absolute():
        return candidate
    root_candidate = raw_root / candidate
    if root_candidate.exists():
        return root_candidate
    return lead_time_raw_dir / candidate


def _parse_iso_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None
