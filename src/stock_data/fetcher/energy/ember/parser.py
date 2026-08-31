"""Ember 全球发电结构与电力数据集解析器。"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from typing import Any

from stock_data.fetcher.energy.common import now_utc_iso
from stock_data.fetcher.energy.ember.constants import EMBER_TECH_MAPPING
from stock_data.fetcher.energy.models import (
    GlobalPowerGenerationRecord,
    GlobalRenewableCapacityRecord,
)
from stock_data.fetcher.energy.taxonomy import DataStatus, normalize_geo_code

logger = logging.getLogger(__name__)


class EmberParser:
    """Ember Yearly Electricity Data 解析器。"""

    @classmethod
    def parse_yearly_csv(
        cls,
        csv_text_or_path: str,
    ) -> tuple[list[GlobalPowerGenerationRecord], list[GlobalRenewableCapacityRecord]]:
        """解析 Ember yearly_full_release CSV 内容。

        Returns:
            tuple: (发电结构记录列表, 装机容量记录列表)
        """
        if not csv_text_or_path:
            return [], []

        if "\n" in csv_text_or_path:
            text_data = csv_text_or_path
        else:
            from pathlib import Path

            text_data = Path(csv_text_or_path).read_text(encoding="utf-8")

        reader = csv.DictReader(io.StringIO(text_data))
        gen_dict: dict[tuple[str, int, str], dict[str, Any]] = {}
        cap_records: list[GlobalRenewableCapacityRecord] = []
        collected_now = now_utc_iso()

        for row in reader:
            iso_code = row.get("ISO 3 code", "").strip()
            area = row.get("Area", "").strip()
            category = row.get("Category", "").strip()
            variable = row.get("Variable", "").strip()
            unit = row.get("Unit", "").strip()
            year_str = row.get("Year", "").strip()
            val_str = row.get("Value", "").strip()
            yoy_pct_str = row.get("YoY % change", "").strip()
            yoy_abs_str = row.get("YoY absolute change", "").strip()

            if not val_str or not year_str or not variable:
                continue

            try:
                val = float(val_str)
                year = int(year_str)
            except ValueError:
                continue

            geo_code = normalize_geo_code(iso_code if iso_code else area)
            tech_enum = EMBER_TECH_MAPPING.get(variable)
            if not tech_enum:
                continue

            yoy_growth = None
            if yoy_pct_str:
                try:
                    yoy_growth = round(float(yoy_pct_str) / 100.0, 4)
                except ValueError:
                    pass

            # 1. 发电量 (Electricity generation: TWh 或 %)
            if category == "Electricity generation":
                key = (geo_code, year, tech_enum)
                if key not in gen_dict:
                    gen_dict[key] = {
                        "geo_code": geo_code,
                        "year": year,
                        "technology": tech_enum,
                        "generation_twh": 0.0,
                        "share_percent": None,
                        "yoy_growth": yoy_growth,
                    }
                if unit == "TWh":
                    gen_dict[key]["generation_twh"] = round(val, 4)
                elif unit == "%":
                    gen_dict[key]["share_percent"] = round(val, 2)

            # 2. 装机容量 (Capacity: GW)
            elif category == "Capacity" and unit == "GW":
                new_added = None
                if yoy_abs_str:
                    try:
                        new_added = round(float(yoy_abs_str), 4)
                    except ValueError:
                        pass

                cap_records.append(
                    GlobalRenewableCapacityRecord(
                        geo_code=geo_code,
                        year=year,
                        technology=tech_enum,
                        capacity_gw=round(val, 4),
                        new_added_gw=new_added,
                        unit="gw",
                        yoy_growth=yoy_growth,
                        source="EMBER",
                        data_status=DataStatus.ACTUAL,
                        release_date=date(year + 1, 3, 31),
                        collected_at=collected_now,
                    )
                )

        gen_records: list[GlobalPowerGenerationRecord] = []
        for (geo, yr, tech), g in gen_dict.items():
            gen_records.append(
                GlobalPowerGenerationRecord(
                    geo_code=geo,
                    trade_date=date(yr, 12, 31),
                    period=str(yr),
                    period_type="yearly",
                    technology=tech,
                    generation_twh=g["generation_twh"],
                    unit="twh",
                    yoy_growth=g["yoy_growth"],
                    share_percent=g["share_percent"],
                    emissions_mtco2=None,
                    source="EMBER",
                    data_status=DataStatus.ACTUAL,
                    release_date=date(yr + 1, 3, 31),
                    collected_at=collected_now,
                )
            )

        logger.info(
            "Ember 解析完成: 提取发电结构记录 %d 条, 装机容量记录 %d 条",
            len(gen_records),
            len(cap_records),
        )
        return gen_records, cap_records
