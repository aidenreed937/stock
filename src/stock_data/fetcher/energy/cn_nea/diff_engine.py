"""国家能源局累计统计数据月度差分与平滑引擎。"""

from __future__ import annotations

import logging
from typing import Any

from stock_data.fetcher.energy.taxonomy import DataStatus

logger = logging.getLogger(__name__)


class NeaDiffEngine:
    """国家能源局月度累计数据差分与平滑计算引擎。"""

    @classmethod
    def calculate_monthly_diff(
        cls,
        parsed_bulletins: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """对解析后的月度通报序列执行时间序列差分，计算单月新增装机与单月投资额。

        Args:
            parsed_bulletins: 已经按 period (YYYY-MM) 升序排列的通报解析结果列表

        Returns:
            list[dict[str, Any]]: 包含单月增量与标准化单位的记录列表
        """
        # 按年份组织月度数据
        year_groups: dict[int, list[dict[str, Any]]] = {}
        for b in parsed_bulletins:
            period_str = b["period"]
            year = int(period_str.split("-")[0])
            year_groups.setdefault(year, []).append(b)

        processed_results: list[dict[str, Any]] = []

        for year, bulletins in year_groups.items():
            # 确保当年按月份升序
            bulletins.sort(key=lambda x: x["period"])
            prev_cum_map: dict[str, float] = {}

            for b in bulletins:
                period_str = b["period"]
                month = int(period_str.split("-")[1])
                indicators = b.get("indicators", {})
                monthly_diff_map: dict[str, float] = {}

                is_combined_jan_feb = month == 2 and 1 not in [
                    int(item["period"].split("-")[1]) for item in bulletins
                ]
                data_status = DataStatus.PROVISIONAL if is_combined_jan_feb else DataStatus.ACTUAL

                for ind_name, ind_data in indicators.items():
                    cum_val = ind_data.get("cumulative_value")
                    if cum_val is None:
                        continue

                    # 1. 装机容量差分计算 (万千瓦 -> GW)
                    if ind_name in (
                        "全国发电装机容量",
                        "太阳能发电",
                        "风电",
                        "水电",
                        "火电",
                        "核电",
                    ):
                        prev = prev_cum_map.get(ind_name)
                        if month == 1 or prev is None:
                            # 1月份累计即当年新增基期估算或初始累计
                            diff_val = cum_val if cum_val < 50000 else cum_val * 0.05
                        else:
                            diff = cum_val - prev
                            diff_val = max(diff, 0.0)

                        prev_cum_map[ind_name] = cum_val
                        # 转为标准 GW
                        monthly_diff_map[f"{ind_name}_new_gw"] = round(diff_val * 0.01, 4)
                        monthly_diff_map[f"{ind_name}_cum_gw"] = round(cum_val * 0.01, 4)

                    # 2. 投资完成额差分计算 (亿元)
                    elif ind_name in ("电源工程投资完成", "电网工程投资完成"):
                        prev = prev_cum_map.get(ind_name)
                        if month == 1 or prev is None:
                            diff_val = cum_val
                        else:
                            diff = cum_val - prev
                            diff_val = max(diff, 0.0)

                        prev_cum_map[ind_name] = cum_val
                        monthly_diff_map[f"{ind_name}_monthly_billion_cny"] = round(diff_val, 2)
                        monthly_diff_map[f"{ind_name}_cum_billion_cny"] = round(cum_val, 2)

                    # 3. 设备利用小时数 (累计小时)
                    elif "利用小时" in ind_name:
                        monthly_diff_map[f"{ind_name}_cum_hours"] = cum_val

                processed_results.append(
                    {
                        "period": period_str,
                        "year": year,
                        "month": month,
                        "release_date": b.get("release_date"),
                        "source_url": b.get("source_url", ""),
                        "data_status": data_status,
                        "indicators": indicators,
                        "computed_metrics": monthly_diff_map,
                    }
                )

        return processed_results
