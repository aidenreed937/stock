"""10年大周期化工行业官方产能利用率与实物产量大底座 (ChemicalCapacityUtilization10Y)。

数据属性与 10 年跨周期架构:
1. 真实分子: 国家统计局 (NBS) 官方公布的 120 个月真实实物月度产量 (2016-09 ~ 2026-08);
2. 真实分母: 中国纯碱工业协会 / 石化联合会 (CPCIF) 历年行业有效产能年鉴数据;
3. 统计局 1-2 月惯例处理: 国家统计局每年 1-2 月合并统计，自动采用 2 月累计值 / 2 平滑填充 1 月与 2 月当期值;
4. 计算指标:
   - actual_output_w_tons: 官方实物月度产量 (万吨);
   - annual_capacity_w_tons: 当年行业有效年化总产能 (万吨);
   - implied_capacity_utilization_pct: 官方隐含月度产能利用率 (%);
   - yoy_growth_pct: 官方产量同比增速 (%);
5. 覆盖周期: 2016-09 至 2026-08 (120 个月, 覆盖 2016-2018 供给侧改革、2019-2021 供需紧平衡、2022-2026 天然碱超级产能投放三轮完整大周期);
6. 存储位置: data/curated/industry/chemical_capacity_utilization_10y.parquet。
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

# 中国纯碱工业协会历年行业有效年产能 (单位: 万吨/年)
SODA_ASH_ANNUAL_CAPACITY: dict[int, float] = {
    2016: 2960.0,
    2017: 2990.0,
    2018: 3030.0,
    2019: 3150.0,
    2020: 3320.0,
    2021: 3410.0,
    2022: 3450.0,
    2023: 3800.0,  # 远兴能源阿拉善一期投产
    2024: 4100.0,  # 远兴一期达产，金山扩产
    2025: 4600.0,  # 阿拉善二期点火
    2026: 4900.0,  # 阿拉善二期全面达产
}


class ChemicalCapacityUtilization10Y:
    """10年大周期产能利用率构建器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.nbs_dir = self.raw_dir / "chemicals" / "nbs"

    def build_10y_utilization(self) -> pl.DataFrame:
        """从已落盘的 120 个月 NBS 官方事实表中构建 10 年产能利用率序列。"""
        nbs_csv = self.nbs_dir / "nbs_soda_ash_monthly.csv"
        if not nbs_csv.exists():
            logger.warning(f"NBS 10年产量事实表不存在: {nbs_csv}")
            return pl.DataFrame()

        rows: list[dict[str, str]] = []
        with nbs_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)

        now_iso = now_utc_iso()
        records: list[dict[str, Any]] = []

        # 遍历处理 120 个月
        for i, r in enumerate(rows):
            m_str = r["report_month"].strip()
            yr, mo = int(m_str.split("-")[0]), int(m_str.split("-")[1])
            r_d = date(yr, mo, 1)

            val_str = r.get("output_current", "").strip()
            cum_str = r.get("output_cumulative", "").strip()
            yoy_str = r.get("output_yoy", "").strip()

            val_w_tons: float | None = None
            if val_str:
                val_w_tons = float(val_str)
            elif mo == 1:
                # 1月取2月累计值/2
                if i + 1 < len(rows) and rows[i + 1].get("output_cumulative"):
                    val_w_tons = round(float(rows[i + 1]["output_cumulative"]) / 2.0, 1)
            elif mo == 2 and cum_str:
                # 2月取累计值/2
                val_w_tons = round(float(cum_str) / 2.0, 1)

            if val_w_tons is None:
                continue

            cap_annual = SODA_ASH_ANNUAL_CAPACITY.get(yr, 4900.0)
            days_in_month = 30
            if mo in [1, 3, 5, 7, 8, 10, 12]:
                days_in_month = 31
            elif mo == 2:
                days_in_month = 29 if yr % 4 == 0 else 28

            monthly_cap = cap_annual * (days_in_month / 365.0)
            implied_util = round((val_w_tons / monthly_cap) * 100.0, 2) if monthly_cap > 0 else None
            yoy_val = round(float(yoy_str) / 100.0, 4) if yoy_str else None

            records.append(
                {
                    "trade_date": r_d,
                    "report_date": r_d,
                    "year": yr,
                    "month": mo,
                    "product_name": "纯碱",
                    "symbol": "SA",
                    "actual_output_w_tons": val_w_tons,
                    "annual_capacity_w_tons": cap_annual,
                    "monthly_capacity_w_tons": round(monthly_cap, 2),
                    "implied_capacity_utilization_pct": implied_util,
                    "yoy_growth": yoy_val,
                    "source": "NBS_Official_10Y",
                    "release_date": r_d,
                    "collected_at": now_iso,
                }
            )

        df_out = pl.DataFrame(records).sort("report_date")
        return df_out
