"""芯片交付周期 (Chip Lead Time / 货期) 月度先导指标采集器 (ChipLeadTimeCollector)。

芯片交期是半导体产业物理世界最敏感的供需先行指标 (领先公司财报 2~4 个季度)。
本采集器为纯真实数据驱动与配置化设计:
1. 配置驱动: 从 config/industry/chip_lead_time.yaml 加载标杆 SKU 篮子、品类权重与状态判定阈值；
2. 在线实时模式: 轮询 Mouser API 获取标杆芯片 SKU 的原厂货期 (Lead Time)，并归档至 RAW 快照；
3. 本地 RAW 重放模式: 离线重放 data/raw/industry/lead_time/ 目录下的真实快照 (支持 *.json 与 *.csv)。
无任何写死/模拟数据。
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

import requests
import yaml

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
)
from stock_data.fetcher.industry.models import ChipLeadTimeRecord
from stock_data.fetcher.industry.semiconductor.lead_time_raw import (
    archive_lead_time_raw_snapshot,
    determine_lead_time_status,
    load_lead_time_raw_records,
)

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


def _parse_lead_time_string_to_weeks(lead_time_str: str) -> float | None:
    """将分销商返回的 '18 Weeks'、'280 天数' 或 '120 Days' 字符串解析为标准周数。"""
    if not lead_time_str:
        return None
    match_weeks = re.search(r"(\d+(?:\.\d+)?)\s*(?:weeks?|周数|周)", lead_time_str, re.IGNORECASE)
    if match_weeks:
        return float(match_weeks.group(1))
    match_days = re.search(r"(\d+(?:\.\d+)?)\s*(?:days?|天数|天)", lead_time_str, re.IGNORECASE)
    if match_days:
        return round(float(match_days.group(1)) / 7.0, 1)
    return None


class ChipLeadTimeCollector:
    """全球芯片交付周期先导指标采集器 (配置驱动 + 纯真实数据与 RAW 快照架构)。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        config_path: Path | str = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.lead_time_raw_dir = self.raw_dir / "lead_time"
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

        cat_averages: dict[str, float] = {}
        sku_details: dict[str, dict[str, Any]] = {}

        for cat, cat_cfg in self.categories.items():
            skus = cat_cfg.get("skus", [])
            cat_leads: list[float] = []
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
                            w = _parse_lead_time_string_to_weeks(lt_str)
                            if w is not None:
                                cat_leads.append(w)
                                sku_details[sku] = {
                                    "category": cat,
                                    "lead_time_raw": lt_str,
                                    "lead_time_weeks": w,
                                    "manufacturer": parts[0].get("Manufacturer", ""),
                                }
                except Exception as e:
                    logger.debug("Mouser API 查询 SKU [%s] 异常: %s", sku, e)

            if cat_leads:
                cat_averages[cat] = round(sum(cat_leads) / len(cat_leads), 1)

        if not cat_averages:
            logger.warning("未能从 Mouser API 获取到任何有效标杆芯片交期数据")
            return []

        # 计算加权均值
        weights = {c: float(self.categories.get(c, {}).get("weight", 1.0)) for c in cat_averages}
        total_weight = sum(weights.values()) or 1.0
        avg_val = round(
            sum(cat_averages[c] * weights[c] for c in cat_averages) / total_weight,
            2,
        )

        today = date.today()
        m_key = f"{today.year:04d}-{today.month:02d}"
        trade_d = get_month_end_date(today.year, today.month)

        record = ChipLeadTimeRecord(
            report_month=m_key,
            trade_date=trade_d,
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
            release_date=today,
            data_status="actual",
            collected_at=now_utc_iso(),
        )

        # 归档 RAW 快照
        archive_lead_time_raw_snapshot(
            raw_dir=self.raw_dir,
            month_key=m_key,
            record=record,
            cat_averages=cat_averages,
            sku_details=sku_details,
        )

        logger.info(
            "成功通过 Mouser API 采集并归档实时芯片交期: %.2f 周 (%s)", avg_val, cat_averages
        )
        return [record]

    def load_from_raw_snapshots(self) -> list[ChipLeadTimeRecord]:
        """从本地 RAW 快照目录加载所有历史月度快照 (支持 JSON 快照与 CSV 原始文件)。"""
        return load_lead_time_raw_records(self.lead_time_raw_dir, self.thresholds)
