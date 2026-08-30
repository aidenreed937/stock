"""乘联会 (CPCA) / 中汽协 (CAAM) 新能源汽车月度产销与渗透率官方采集器 (NevCollector)。"""

from __future__ import annotations

import csv
import gzip
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.models import NevMonthlyRecord

logger = logging.getLogger(__name__)


class NevCollector:
    """乘联会 CPCA 新能源汽车月度大盘指标采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.cpca_dir = self.raw_dir / "cpca"

    def collect(self) -> list[NevMonthlyRecord]:
        """执行新能源汽车数据采集: 优先从 RAW 快照读取，缺失时调取乘联会官方接口。"""
        self.cpca_dir.mkdir(parents=True, exist_ok=True)
        for candidate in ["nev_sales_real.csv", "nev_monthly_sales.csv"]:
            raw_csv = self.cpca_dir / candidate
            if raw_csv.exists():
                return self.load_from_raw_csv(raw_csv)

        # 在线调用乘联会实时接口
        records = self.fetch_from_adapter()
        if records:
            return records

        return []

    def fetch_from_adapter(self) -> list[NevMonthlyRecord]:
        """通过 AkShare 在线抓取乘联会官方新能源产销与渗透率数据。"""
        try:
            import akshare as ak
        except ImportError:
            logger.error("未安装 akshare，跳过乘联会数据抓取")
            return []

        logger.info("正在调用乘联会官方新能源汽车与大盘产销接口...")
        try:
            df_fuel = ak.car_market_fuel_cpca()
            df_tot = ak.car_market_total_cpca()
        except Exception as e:
            logger.warning("调用乘联会接口异常: %s", e)
            return []

        if df_fuel is None or df_fuel.empty or df_tot is None or df_tot.empty:
            logger.warning("乘联会接口返回空数据")
            return []

        # 解析宽表数据为标准月度时序 (提取所有形如 '2025年', '2026年' 的年份列)
        nev_map: dict[str, float] = {}
        tot_map: dict[str, float] = {}

        for df, target_map in [(df_fuel, nev_map), (df_tot, tot_map)]:
            year_cols = [c for c in df.columns if "年" in str(c)]
            for _, row in df.iterrows():
                mo_raw = str(row["月份"]).strip().replace("月", "")
                try:
                    mo_int = int(mo_raw)
                except ValueError:
                    continue

                for yr_col in year_cols:
                    yr_int = int(str(yr_col).replace("年", ""))
                    val = row[yr_col]
                    if val is not None and str(val).strip() not in ("", "nan", "None"):
                        try:
                            f_val = float(val)
                            if f_val > 0:
                                target_map[f"{yr_int}-{mo_int:02d}"] = round(f_val, 4)
                        except (ValueError, TypeError):
                            continue

        if not nev_map:
            return []

        records: list[NevMonthlyRecord] = []
        now_iso = now_utc_iso()
        all_months = sorted(nev_map.keys())

        # 压缩保存 RAW 快照
        cache_data: list[dict[str, Any]] = []
        for m_str in all_months:
            nev_vol = nev_map[m_str]
            tot_vol = tot_map.get(m_str)
            pen_rate = round(nev_vol / tot_vol, 4) if tot_vol and tot_vol > 0 else None
            yr, mo = parse_month_string(m_str)
            t_date = get_month_end_date(yr, mo)
            rel_year = yr if mo < 12 else yr + 1
            rel_month = mo + 1 if mo < 12 else 1
            rel_date = date(rel_year, rel_month, 10)

            rec = NevMonthlyRecord(
                report_month=m_str,
                trade_date=t_date,
                wholesale_volume_ten_thousand=nev_vol,
                retail_volume_ten_thousand=None,
                export_volume_ten_thousand=None,
                penetration_rate=pen_rate,
                battery_installation_gwh=None,
                yoy_growth=None,  # transform 层计算
                unit="ten_thousand_units",
                source="CPCA",
                source_url="http://www.cpcaauto.com/",
                release_date=rel_date,
                data_status="actual",
                collected_at=now_iso,
            )
            records.append(rec)
            cache_data.append(
                {
                    "report_month": m_str,
                    "trade_date": t_date.isoformat(),
                    "wholesale_volume_ten_thousand": nev_vol,
                    "total_car_volume_ten_thousand": tot_vol,
                    "penetration_rate": pen_rate,
                    "source": "CPCA",
                    "collected_at": now_iso,
                }
            )

        records.sort(key=lambda r: r.trade_date)
        snapshot_file = self.cpca_dir / "nev_sales_live.json.gz"
        try:
            with gzip.open(snapshot_file, "wt", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.info("已保存乘联会官方实时快照: %s (共 %d 月)", snapshot_file, len(records))
        except Exception as e:
            logger.error("保存乘联会快照异常: %s", e)

        return records

    def load_from_raw_csv(self, file_path: Path | str) -> list[NevMonthlyRecord]:
        """从 CPCA RAW 快照 CSV 中读取并标准化。"""
        p = Path(file_path)
        if not p.exists():
            return []

        def _safe_float(val: str | None) -> float | None:
            if not val or not val.strip():
                return None
            try:
                return float(val.strip())
            except (ValueError, TypeError):
                return None

        records: list[NevMonthlyRecord] = []
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                month_str = row["report_month"].strip()
                year, month = parse_month_string(month_str)
                t_date = get_month_end_date(year, month)
                records.append(
                    NevMonthlyRecord(
                        report_month=month_str,
                        trade_date=t_date,
                        wholesale_volume_ten_thousand=float(row["wholesale_volume_ten_thousand"]),
                        retail_volume_ten_thousand=_safe_float(
                            row.get("retail_volume_ten_thousand")
                        ),
                        export_volume_ten_thousand=_safe_float(
                            row.get("export_volume_ten_thousand")
                        ),
                        penetration_rate=_safe_float(row.get("penetration_rate")),
                        battery_installation_gwh=_safe_float(row.get("battery_installation_gwh")),
                        yoy_growth=None,
                        unit=row.get("unit") or "ten_thousand_units",
                        source=row.get("source") or "CPCA",
                        source_url=row.get("source_url") or "http://www.cpcaauto.com/",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        return records
