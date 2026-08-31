"""国家能源局 (NEA) 电力与新能源数据统一采集与标准化门面 (CnNeaCollector)。"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.energy.base import EnergyFetcherBase
from stock_data.fetcher.energy.cn_nea.crawler import CnNeaCrawler
from stock_data.fetcher.energy.cn_nea.diff_engine import NeaDiffEngine
from stock_data.fetcher.energy.cn_nea.parser import NeaPowerTableParser
from stock_data.fetcher.energy.common import (
    DEFAULT_CURATED_ENERGY_DIR,
    DEFAULT_RAW_ENERGY_DIR,
    get_month_end_date,
    now_utc_iso,
    save_curated_energy_fact,
)
from stock_data.fetcher.energy.models import (
    GlobalPowerGenerationRecord,
    GlobalRenewableCapacityRecord,
    records_to_power_generation_frame,
    records_to_renewable_capacity_frame,
)
from stock_data.fetcher.energy.taxonomy import EnergyProduct

logger = logging.getLogger(__name__)


class CnNeaCollector(EnergyFetcherBase):
    """国家能源局 (NEA) 电力统计数据统一采集门面。"""

    source_name: str = "cn_nea"

    def __init__(
        self,
        raw_dir: Path | str = DEFAULT_RAW_ENERGY_DIR,
        curated_dir: Path | str = DEFAULT_CURATED_ENERGY_DIR,
    ) -> None:
        super().__init__(raw_dir=raw_dir, curated_dir=curated_dir)
        self.crawler = CnNeaCrawler(raw_dir=self.raw_dir)

    def collect(self) -> dict[str, list[Any]]:
        """执行端到端采集与差分计算，返回标准化记录。

        Returns:
            dict[str, list[Any]]:
                "capacity": list[GlobalRenewableCapacityRecord]
                "generation": list[GlobalPowerGenerationRecord]
        """
        # 1. 抓取或加载本地 RAW HTML 快照
        bulletins_raw = self.crawler.fetch_bulletins()
        if not bulletins_raw:
            logger.info("未发现国家能源局通报数据")
            return {"capacity": [], "generation": []}

        # 2. 双模解析通报
        parsed_list: list[dict[str, Any]] = []
        for item in bulletins_raw:
            html = item.get("html_content", "")
            url = item.get("url", "")
            parsed = NeaPowerTableParser.parse_html(html, source_url=url)
            if parsed:
                parsed["collected_at"] = item.get("collected_at") or now_utc_iso()
                parsed_list.append(parsed)

        parsed_list.sort(key=lambda x: x["period"])

        # 3. 差分与平滑计算
        diff_results = NeaDiffEngine.calculate_monthly_diff(parsed_list)

        # 4. 组装 Curated 黄金表标准模型
        capacity_records: list[GlobalRenewableCapacityRecord] = []
        generation_records: list[GlobalPowerGenerationRecord] = []

        tech_map = {
            "太阳能发电": EnergyProduct.SOLAR_PV,
            "并网太阳能发电": EnergyProduct.SOLAR_PV,
            "风电": EnergyProduct.WIND_TOTAL,
            "并网风电": EnergyProduct.WIND_TOTAL,
            "水电": EnergyProduct.HYDRO,
            "其中：水电": EnergyProduct.HYDRO,
            "其中:水 电": EnergyProduct.HYDRO,
            "火电": EnergyProduct.THERMAL_POWER,
            "其中:火 电": EnergyProduct.THERMAL_POWER,
            "核电": EnergyProduct.NUCLEAR,
            "其中:核 电": EnergyProduct.NUCLEAR,
            "全国发电装机容量": EnergyProduct.TOTAL_ELECTRICITY,
            "全口径发电设备容量": EnergyProduct.TOTAL_ELECTRICITY,
        }

        for item in diff_results:
            period_str = item["period"]
            year = item["year"]
            month = item["month"]
            t_date = get_month_end_date(year, month)
            release_d: date | None = item.get("release_date")
            data_status: str = item.get("data_status", "actual")
            computed = item.get("computed_metrics", {})
            indicators = item.get("indicators", {})

            for ch_name, tech_code in tech_map.items():
                cum_gw = computed.get(f"{ch_name}_cum_gw")
                new_gw = computed.get(f"{ch_name}_new_gw")
                ind_meta = indicators.get(ch_name, {})
                yoy = ind_meta.get("yoy_growth")

                if cum_gw is not None:
                    capacity_records.append(
                        GlobalRenewableCapacityRecord(
                            geo_code="CHN",
                            year=year,
                            technology=tech_code,
                            capacity_gw=cum_gw,
                            new_added_gw=new_gw,
                            yoy_growth=yoy,
                            source="NEA",
                            data_status=data_status,
                            release_date=release_d,
                            collected_at=now_utc_iso(),
                        )
                    )

            # 发电设备利用小时数与发电量推算
            utilization_map = {
                "全国发电设备累计平均利用小时": (
                    EnergyProduct.TOTAL_ELECTRICITY,
                    "全国发电装机容量",
                ),
                "发电设备累计平均利用小时": (
                    EnergyProduct.TOTAL_ELECTRICITY,
                    "全国发电装机容量",
                ),
                "6000千瓦及以上电厂发电设备利用小时": (
                    EnergyProduct.TOTAL_ELECTRICITY,
                    "全国发电装机容量",
                ),
                "其中：水电": (EnergyProduct.HYDRO, "水电"),
                "水电": (EnergyProduct.HYDRO, "水电"),
                "火电": (EnergyProduct.THERMAL_POWER, "火电"),
                "核电": (EnergyProduct.NUCLEAR, "核电"),
                "风电": (EnergyProduct.WIND_TOTAL, "风电"),
                "太阳能发电": (EnergyProduct.SOLAR_PV, "太阳能发电"),
            }

            for u_name, (tech_code, cap_name) in utilization_map.items():
                hours_val = computed.get(f"{u_name}_cum_hours")
                cap_gw = (
                    computed.get(f"{cap_name}_cum_gw")
                    or computed.get("全国发电装机容量_cum_gw")
                    or computed.get("全口径发电设备容量_cum_gw")
                )
                if hours_val is not None and cap_gw:
                    # 推算发电量: 利用小时 * 累计装机 (GW * h * 10^-3 -> TWh)
                    est_twh = round(cap_gw * hours_val * 0.001, 3)
                    generation_records.append(
                        GlobalPowerGenerationRecord(
                            geo_code="CHN",
                            trade_date=t_date,
                            period=period_str,
                            period_type="monthly",
                            technology=tech_code,
                            generation_twh=est_twh,
                            source="NEA",
                            data_status=data_status,
                            release_date=release_d,
                            collected_at=now_utc_iso(),
                        )
                    )

        return {
            "capacity": capacity_records,
            "generation": generation_records,
        }

    def collect_and_save(self) -> dict[str, int]:
        """执行端到端采集并将事实增量落盘至 Curated 黄金表。"""
        records_dict = self.collect()
        cap_records: list[GlobalRenewableCapacityRecord] = records_dict.get("capacity", [])
        gen_records: list[GlobalPowerGenerationRecord] = records_dict.get("generation", [])

        results: dict[str, int] = {}
        if cap_records:
            df_cap = records_to_renewable_capacity_frame(cap_records)
            count_cap = save_curated_energy_fact(
                new_df=df_cap,
                target_parquet_path=self.curated_dir / "global_renewable_capacity.parquet",
                primary_keys=["geo_code", "year", "technology", "source"],
                sort_keys=["year", "technology"],
            )
            results["global_renewable_capacity"] = count_cap

        if gen_records:
            df_gen = records_to_power_generation_frame(gen_records)
            count_gen = save_curated_energy_fact(
                new_df=df_gen,
                target_parquet_path=self.curated_dir / "global_power_generation.parquet",
                primary_keys=["geo_code", "period", "technology", "source"],
                sort_keys=["trade_date", "technology"],
            )
            results["global_power_generation"] = count_gen

        return results
