"""IRENA 可再生能源容量数据解析器 (IrenaParser)。"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.energy.common import now_utc_iso
from stock_data.fetcher.energy.irena.constants import IRENA_TECH_MAPPING
from stock_data.fetcher.energy.models import GlobalRenewableCapacityRecord
from stock_data.fetcher.energy.taxonomy import (
    DataStatus,
    convert_capacity_to_gw,
    normalize_geo_code,
)

logger = logging.getLogger(__name__)


def parse_irena_value_and_status(raw_str: str | None) -> tuple[float | None, str]:
    """从 IRENA 数值字符串中解析装机容量 (MW) 与数据质量状态标志 (o/u/e)。

    规则:
        "1234 o" -> (1234.0, "actual") (官方核定)
        "567 u"  -> (567.0, "provisional") (行业非官方/初步报告)
        "890 e"  -> (890.0, "estimated") (IRENA 估算)
        "1234"   -> (1234.0, "actual")
        ".." / "-" / "" -> (None, "actual")
    """
    if not raw_str:
        return None, DataStatus.ACTUAL

    cleaned = raw_str.strip()
    if cleaned in ("..", "-", "--", "/", "—", "NaN", "null"):
        return None, DataStatus.ACTUAL

    # 提取末尾标志位
    status = DataStatus.ACTUAL
    if cleaned.endswith(" o") or cleaned.endswith("o"):
        status = DataStatus.ACTUAL
        cleaned = cleaned.rstrip(" o").rstrip("o").strip()
    elif cleaned.endswith(" u") or cleaned.endswith("u"):
        status = DataStatus.PROVISIONAL
        cleaned = cleaned.rstrip(" u").rstrip("u").strip()
    elif cleaned.endswith(" e") or cleaned.endswith("e"):
        status = DataStatus.ESTIMATED
        cleaned = cleaned.rstrip(" e").rstrip("e").strip()

    # 清洗千分位逗号与空格
    cleaned = cleaned.replace(",", "").replace(" ", "")
    try:
        val = float(cleaned)
        return val, status
    except ValueError:
        return None, status


class IrenaParser:
    """IRENA 全球新能源装机容量数据集解析器。"""

    @classmethod
    def parse_csv(cls, csv_source: str | Path | io.StringIO) -> list[GlobalRenewableCapacityRecord]:
        """解析 IRENA 官方 CSV 长表数据。

        支持列名:
            Country/area (或 Country, ISO3), Technology, Year, Value (MW)
        """
        if isinstance(csv_source, Path):
            if not csv_source.exists():
                return []
            content = csv_source.read_text(encoding="utf-8-sig")
            reader = csv.DictReader(io.StringIO(content))
        elif isinstance(csv_source, str):
            reader = csv.DictReader(io.StringIO(csv_source))
        else:
            reader = csv.DictReader(csv_source)

        raw_records: list[dict[str, Any]] = []
        for row in reader:
            # 兼容不同大小写的表头
            country_raw = (
                row.get("Country/area")
                or row.get("Country")
                or row.get("country")
                or row.get("Area")
            )
            tech_raw = row.get("Technology") or row.get("technology") or row.get("tech")
            year_raw = row.get("Year") or row.get("year")
            val_raw = (
                row.get("Value")
                or row.get("value")
                or row.get("MW")
                or row.get("Electricity capacity statistics")
                or list(row.values())[-1]
            )

            if not country_raw or not tech_raw or not year_raw or val_raw is None:
                continue

            tech_enum = IRENA_TECH_MAPPING.get(tech_raw.strip())
            if not tech_enum:
                continue

            try:
                year = int(str(year_raw).strip())
            except ValueError:
                continue

            geo_code = normalize_geo_code(country_raw.strip())
            val_mw, status = parse_irena_value_and_status(str(val_raw))
            if val_mw is None or val_mw < 0:
                continue

            cap_gw = convert_capacity_to_gw(val_mw, "MW")
            raw_records.append(
                {
                    "geo_code": geo_code,
                    "year": year,
                    "technology": tech_enum,
                    "capacity_gw": cap_gw,
                    "data_status": status,
                }
            )

        # 按 (geo_code, technology, year) 聚合 OnGrid + OffGrid 总装机
        aggregated: dict[tuple[str, str, int], dict[str, Any]] = {}
        for r in raw_records:
            agg_key = (r["geo_code"], r["technology"], r["year"])
            if agg_key not in aggregated:
                aggregated[agg_key] = {
                    "geo_code": r["geo_code"],
                    "technology": r["technology"],
                    "year": r["year"],
                    "capacity_gw": r["capacity_gw"],
                    "data_status": r["data_status"],
                }
            else:
                aggregated[agg_key]["capacity_gw"] += r["capacity_gw"]
                # 状态优先级: actual > provisional > estimated
                if r["data_status"] == DataStatus.ACTUAL:
                    aggregated[agg_key]["data_status"] = DataStatus.ACTUAL

        # 按 (geo_code, technology) 分组并按年份升序计算新增装机与同比增速
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for (geo, tech, _year), agg_item in aggregated.items():
            grouped.setdefault((geo, tech), []).append(agg_item)

        final_records: list[GlobalRenewableCapacityRecord] = []
        collected_now = now_utc_iso()

        for (geo, tech), items in grouped.items():
            items.sort(key=lambda x: x["year"])
            prev_cap: float | None = None

            for item in items:
                year = item["year"]
                cum_gw = item["capacity_gw"]
                status = item["data_status"]

                new_added_gw: float | None = None
                yoy_growth: float | None = None

                if prev_cap is not None:
                    diff = cum_gw - prev_cap
                    new_added_gw = round(max(diff, 0.0), 4)
                    if prev_cap > 0:
                        yoy_growth = round(diff / prev_cap, 4)

                prev_cap = cum_gw

                final_records.append(
                    GlobalRenewableCapacityRecord(
                        geo_code=geo,
                        year=year,
                        technology=tech,
                        capacity_gw=cum_gw,
                        new_added_gw=new_added_gw,
                        unit="gw",
                        yoy_growth=yoy_growth,
                        source="IRENA",
                        data_status=status,
                        release_date=date(year + 1, 3, 31),
                        collected_at=collected_now,
                    )
                )

        final_records.sort(key=lambda r: (r.year, r.geo_code, r.technology))
        return final_records
