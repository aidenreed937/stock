"""芯片交付周期的 Mouser 兼容采集器 (ChipLeadTimeCollector)。

芯片交期是半导体产业物理世界最敏感的供需先行指标 (领先公司财报 2~4 个季度)。
正式 ``chip_lead_time`` 行业端点使用 ``SusquehannaLeadTimeCollector``；本类保留
Mouser 在线 API 与历史 RAW 重放能力，供旧调用方兼容使用。本采集器为纯真实数据驱动与配置化设计:
1. 配置驱动: 从 config/industry/chip_lead_time.yaml 加载标杆 SKU 篮子、品类权重与状态判定阈值；
2. 在线实时模式: 轮询 Mouser API 获取标杆芯片 SKU 的原厂货期 (Lead Time)，并归档至 RAW 快照；
3. 本地 RAW 重放模式: 离线重放调用方传入的 RAW 根目录下的 Mouser JSON 快照。
无任何写死/模拟数据。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import requests
import yaml

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_content_bytes,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.semiconductor.models import ChipLeadTimeRecord
from stock_data.fetcher.industry.semiconductor.parsers.lead_time_raw import (
    aggregate_category_lead_times,
    archive_lead_time_raw_snapshot,
    determine_lead_time_status,
    extract_lead_time_release_date,
    load_lead_time_raw_records,
    parse_lead_time_string_to_weeks,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/industry/chip_lead_time.yaml")


def load_chip_lead_time_config(config_path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """加载芯片交付周期监控配置 (支持动态自定义 SKU 篮子、品类权重与状态阈值)。"""
    p = Path(config_path)
    if not p.exists():
        return {
            "categories": {
                "mcu": {
                    "weight": 0.25,
                    "skus": ["STM32F103C8T6", "ATMEGA328P-PU", "PIC16F877A-I/P"],
                },
                "analog": {
                    "weight": 0.30,
                    "skus": ["LM358N", "NE555P", "LM317T", "INA219AIDR"],
                },
                "discrete": {
                    "weight": 0.20,
                    "skus": ["2N7002", "BSS138", "1N4148", "IRF540N"],
                },
                "compute": {
                    "weight": 0.25,
                    "skus": ["XC7Z020-1CLG400C", "EP4CE6E22C8N", "STM32MP157AAC3"],
                },
            },
            "thresholds": {"overheating": 26.0, "tight": 18.0, "normal": 13.0, "easing": 0.0},
        }
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class ChipLeadTimeCollector:
    """全球芯片交付周期先导指标采集器 (配置驱动 + 纯真实数据与 RAW 快照架构)。"""

    def __init__(
        self,
        raw_dir: Path | str,
        config_path: Path | str = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.lead_time_raw_dir = self.paths.lead_time_dir
        self.config = load_chip_lead_time_config(config_path)
        self.categories = self.config.get("categories", {})
        self.thresholds = self.config.get("thresholds", {})

    def collect(self) -> list[ChipLeadTimeRecord]:
        """执行芯片交付周期采集。优先在线轮询真实分销商 API，若无 Key 则从本地 RAW 快照加载。"""
        # 1. 尝试在线抓取
        live_records = self._fetch_live_distributor_data()
        if live_records:
            return live_records

        # 2. 回退读取本地已归档 RAW 快照
        raw_records = self.load_from_raw_snapshots()
        if raw_records:
            logger.info("从本地 RAW 快照加载到 %d 条芯片交付周期记录", len(raw_records))
            return raw_records

        logger.warning(
            "未配置 MOUSER_SEARCH_API_KEY 且本地未发现 RAW 快照，跳过芯片交付周期采集。"
            "请配置 MOUSER_SEARCH_API_KEY 环境变量以启用实时采集。"
        )
        return []

    def _fetch_live_distributor_data(self) -> list[ChipLeadTimeRecord]:
        """从 Mouser API 在线轮询标杆芯片交期并构建当前月度记录。"""
        from stock_data.core.settings import data_settings

        api_key = (
            data_settings.mouser_search_api_key
            or data_settings.mouser_api_key
            or os.getenv("MOUSER_SEARCH_API_KEY")
            or os.getenv("MOUSER_API_KEY")
        )
        if not api_key:
            return []

        sku_details: dict[str, dict[str, Any]] = {}
        missing_release_skus: list[str] = []

        for cat, cat_cfg in self.categories.items():
            skus = cat_cfg.get("skus", [])
            for sku in skus:
                try:
                    url = f"https://api.mouser.com/api/v1/search/partnumber?apiKey={api_key}"
                    payload = {
                        "SearchByPartRequest": {
                            "mouserPartNumber": sku,
                            "partSearchOptions": "string",
                        }
                    }
                    resp = requests.post(url, json=payload, timeout=10)
                    if resp.status_code == 200:
                        res_json = resp.json()
                        parts = res_json.get("SearchResults", {}).get("Parts", [])
                        if parts:
                            lt_str = parts[0].get("LeadTime", "")
                            w = parse_lead_time_string_to_weeks(lt_str)
                            release_date = extract_lead_time_release_date(res_json)
                            if release_date is None:
                                missing_release_skus.append(sku)
                            sku_details[sku] = {
                                "category": cat,
                                "lead_time_raw": lt_str,
                                "lead_time_weeks": w,
                                "manufacturer": parts[0].get("Manufacturer", ""),
                                "release_date": (
                                    release_date.isoformat() if release_date is not None else None
                                ),
                            }
                except Exception as e:
                    logger.debug("Mouser API 查询 SKU [%s] 异常: %s", sku, e)

        if not sku_details:
            logger.warning("未能从 Mouser API 获取到任何标杆芯片交期数据")
            return []
        if missing_release_skus:
            logger.warning(
                "Mouser 交期响应缺少真实 release_date，拒绝生成 RAW: %s",
                ", ".join(missing_release_skus),
            )
            return []

        release_dates = [
            date.fromisoformat(str(detail["release_date"]))
            for detail in sku_details.values()
            if detail.get("release_date")
        ]
        if not release_dates:
            logger.warning("Mouser 交期响应未提供真实 release_date，拒绝生成 RAW")
            return []

        # 计算加权均值（0 天缺货标记与 >=52 周封顶值不参与聚合）
        cat_averages, avg_val, excluded = aggregate_category_lead_times(
            sku_details, self.categories
        )
        if not cat_averages or avg_val is None:
            logger.warning("清洗后无有效 SKU 交期可聚合，拒绝生成 RAW")
            return []
        if excluded:
            logger.warning("剔除无效交期 SKU（0 天/封顶）: %s", ", ".join(excluded))

        today = date.today()
        release_date = max(release_dates)
        m_key = f"{today.year:04d}-{today.month:02d}"

        record = ChipLeadTimeRecord(
            report_month=m_key,
            trade_date=today,
            avg_lead_time_weeks=avg_val,
            mcu_lead_time_weeks=cat_averages.get("mcu"),
            analog_lead_time_weeks=cat_averages.get("analog"),
            discrete_lead_time_weeks=cat_averages.get("discrete"),
            compute_lead_time_weeks=cat_averages.get("compute"),
            lead_time_yoy_weeks=None,
            lead_time_mom_weeks=None,
            lead_time_status=determine_lead_time_status(avg_val, self.thresholds),
            unit="weeks",
            source="Mouser/Distributor",
            source_url="https://api.mouser.com",
            release_date=release_date,
            data_status="actual",
            collected_at=now_utc_iso(),
            lead_time_raw=json.dumps(
                {
                    sku: detail.get("lead_time_raw")
                    for sku, detail in sorted(sku_details.items())
                    if detail.get("lead_time_raw")
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            sku_details_raw=json.dumps(sku_details, ensure_ascii=False, sort_keys=True),
        )

        # 归档 RAW 快照
        snapshot_path = archive_lead_time_raw_snapshot(
            raw_dir=self.paths.raw_root,
            month_key=m_key,
            record=record,
            cat_averages=cat_averages,
            sku_details=sku_details,
            excluded_skus=excluded,
        )
        record = replace(
            record,
            raw_content_sha256=raw_content_sha256(raw_snapshot_content_bytes(snapshot_path)),
            raw_snapshot_path=raw_snapshot_path_value(snapshot_path, self.paths.raw_root),
        )

        logger.info(
            "成功通过 Mouser API 采集并归档实时芯片交期: %.2f 周 (%s)", avg_val, cat_averages
        )
        return [record]

    def load_from_raw_snapshots(self) -> list[ChipLeadTimeRecord]:
        """从本地 RAW 快照目录加载所有历史月度 JSON 快照。"""
        return load_lead_time_raw_records(
            self.lead_time_raw_dir, self.thresholds, categories=self.categories
        )
