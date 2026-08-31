"""乘联会 (CPCA) / 中汽协 (CAAM) / 动力电池创新联盟 (CABIA) 新能源汽车官方采集器 (NevCollector)。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.automotive.crawler import (
    CabiaCrawler,
    CpcaBulletinCrawler,
    fetch_cpca_akshare_records,
    parse_matrix_file,
)
from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.models import NevMonthlyRecord

logger = logging.getLogger(__name__)


class NevCollector:
    """新能源汽车月度产销、出口与动力电池装机大盘指标采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.cpca_dir = self.raw_dir / "cpca"
        self.cabia_crawler = CabiaCrawler(raw_dir=self.raw_dir)
        self.cpca_crawler = CpcaBulletinCrawler(raw_dir=self.raw_dir)

    def collect(self) -> list[NevMonthlyRecord]:
        """执行新能源汽车数据采集: 检查 RAW 快照 -> 在线通报增量合并 -> 落盘输出。"""
        self.cpca_dir.mkdir(parents=True, exist_ok=True)
        records_map: dict[str, NevMonthlyRecord] = {}

        # 1. 优先加载本地真实 RAW CSV 底表
        for candidate in ["nev_sales_real.csv", "nev_monthly_sales.csv"]:
            raw_csv = self.cpca_dir / candidate
            if raw_csv.exists():
                for rec in self.load_from_raw_csv(raw_csv):
                    records_map[rec.report_month] = rec
                break

        # 2. 若无 RAW CSV，尝试从 RAW 二维宽表矩阵还原
        if not records_map:
            nev_mat = self.cpca_dir / "cpca_nev_wholesale_matrix.csv"
            tot_mat = self.cpca_dir / "cpca_total_wholesale_matrix.csv"
            if nev_mat.exists() and tot_mat.exists():
                for rec in self.load_from_matrix_csvs(nev_mat, tot_mat):
                    records_map[rec.report_month] = rec

        # 3. 在线/快照增量爬取 CABIA 电池装车通报与 CPCA 乘联会月报
        cabia_bulletins = self.cabia_crawler.fetch_latest_bulletins()
        cpca_bulletins = self.cpca_crawler.fetch_latest_bulletins()

        all_months = (
            set(records_map.keys()) | set(cabia_bulletins.keys()) | set(cpca_bulletins.keys())
        )
        now_iso = now_utc_iso()

        for m_str in sorted(all_months):
            yr, mo = parse_month_string(m_str)
            t_date = get_month_end_date(yr, mo)
            existing = records_map.get(m_str)

            cabia_info = cabia_bulletins.get(m_str, {})
            cpca_info = cpca_bulletins.get(m_str, {})

            ws_val: float = 0.0
            if cpca_info.get("wholesale_volume_ten_thousand") is not None:
                ws_val = float(cpca_info["wholesale_volume_ten_thousand"])
            elif existing is not None:
                ws_val = float(existing.wholesale_volume_ten_thousand)

            ret_vol: float | None = None
            if cpca_info.get("retail_volume_ten_thousand") is not None:
                ret_vol = float(cpca_info["retail_volume_ten_thousand"])
            elif existing is not None:
                ret_vol = existing.retail_volume_ten_thousand

            exp_vol: float | None = None
            if cpca_info.get("export_volume_ten_thousand") is not None:
                exp_vol = float(cpca_info["export_volume_ten_thousand"])
            elif existing is not None:
                exp_vol = existing.export_volume_ten_thousand

            pen_rate: float | None = None
            if cpca_info.get("penetration_rate") is not None:
                pen_rate = float(cpca_info["penetration_rate"])
            elif existing is not None:
                pen_rate = existing.penetration_rate

            bat_gwh: float | None = None
            if cabia_info.get("battery_installation_gwh") is not None:
                bat_gwh = float(cabia_info["battery_installation_gwh"])
            elif existing is not None:
                bat_gwh = existing.battery_installation_gwh

            rel_year = yr if mo < 12 else yr + 1
            rel_month = mo + 1 if mo < 12 else 1
            default_rel_date = date(rel_year, rel_month, 10)
            rel_date = (
                cpca_info.get("release_date")
                or cabia_info.get("release_date")
                or (existing.release_date if existing else default_rel_date)
            )

            rec = NevMonthlyRecord(
                report_month=m_str,
                trade_date=t_date,
                wholesale_volume_ten_thousand=ws_val,
                retail_volume_ten_thousand=ret_vol,
                export_volume_ten_thousand=exp_vol,
                penetration_rate=pen_rate,
                battery_installation_gwh=bat_gwh,
                yoy_growth=None,
                unit="ten_thousand_units",
                source=existing.source if existing else "CPCA/CABIA",
                source_url=existing.source_url if existing else "http://www.cpcaauto.com/",
                release_date=rel_date,
                data_status="actual",
                collected_at=existing.collected_at if existing else now_iso,
            )
            records_map[m_str] = rec

        # 4. 若仍无数据，回退尝试在线调用 AkShare 接口
        if not records_map:
            for rec in self.fetch_from_adapter():
                records_map[rec.report_month] = rec

        records = sorted(records_map.values(), key=lambda r: r.trade_date)
        if records:
            self._save_raw_csv(records, self.cpca_dir / "nev_sales_real.csv")
        return records

    def load_from_matrix_csvs(
        self,
        nev_matrix_file: Path | str,
        total_matrix_file: Path | str,
        retail_matrix_file: Path | str | None = None,
        export_matrix_file: Path | str | None = None,
        battery_matrix_file: Path | str | None = None,
    ) -> list[NevMonthlyRecord]:
        """从 CPCA 二维宽表矩阵 (行: 月份, 列: 年份) 中提取并还原为全量月度时序。"""
        p_nev = Path(nev_matrix_file)
        p_tot = Path(total_matrix_file)
        if not p_nev.exists() or not p_tot.exists():
            return []

        nev_map = parse_matrix_file(p_nev)
        tot_map = parse_matrix_file(p_tot)
        ret_map = parse_matrix_file(
            Path(retail_matrix_file or self.cpca_dir / "cpca_nev_retail_matrix.csv")
        )
        exp_map = parse_matrix_file(
            Path(export_matrix_file or self.cpca_dir / "cpca_nev_export_matrix.csv")
        )
        bat_map = parse_matrix_file(
            Path(battery_matrix_file or self.cpca_dir / "cabia_battery_matrix.csv")
        )

        if not nev_map:
            return []

        records: list[NevMonthlyRecord] = []
        now_iso = now_utc_iso()
        all_months = sorted(nev_map.keys())

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
                retail_volume_ten_thousand=ret_map.get(m_str),
                export_volume_ten_thousand=exp_map.get(m_str),
                penetration_rate=pen_rate,
                battery_installation_gwh=bat_map.get(m_str),
                yoy_growth=None,
                unit="ten_thousand_units",
                source="CPCA",
                source_url="http://www.cpcaauto.com/",
                release_date=rel_date,
                data_status="actual",
                collected_at=now_iso,
            )
            records.append(rec)

        records.sort(key=lambda r: r.trade_date)
        return records

    def fetch_from_adapter(self) -> list[NevMonthlyRecord]:
        """通过 AkShare 在线抓取乘联会官方新能源产销与渗透率数据。"""
        return fetch_cpca_akshare_records(self.cpca_dir)

    def load_from_raw_csv(self, file_path: Path | str) -> list[NevMonthlyRecord]:
        """从 CPCA RAW 快照 CSV 中读取并标准化。"""
        p = Path(file_path)
        if not p.exists():
            return []

        def _safe_float(val: str | None) -> float | None:
            if not val or not str(val).strip() or str(val).strip() in ("nan", "None", ""):
                return None
            try:
                return float(str(val).strip())
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
                        yoy_growth=_safe_float(row.get("yoy_growth")),
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

    def _save_raw_csv(self, records: list[NevMonthlyRecord], path: Path) -> None:
        """持久化新能源汽车明细 CSV。"""
        fieldnames = [
            "report_month",
            "trade_date",
            "wholesale_volume_ten_thousand",
            "retail_volume_ten_thousand",
            "export_volume_ten_thousand",
            "penetration_rate",
            "battery_installation_gwh",
            "yoy_growth",
            "unit",
            "source",
            "source_url",
            "release_date",
            "data_status",
            "collected_at",
        ]
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                writer.writerow(
                    {
                        "report_month": r.report_month,
                        "trade_date": r.trade_date.isoformat(),
                        "wholesale_volume_ten_thousand": r.wholesale_volume_ten_thousand,
                        "retail_volume_ten_thousand": r.retail_volume_ten_thousand
                        if r.retail_volume_ten_thousand is not None
                        else "",
                        "export_volume_ten_thousand": r.export_volume_ten_thousand
                        if r.export_volume_ten_thousand is not None
                        else "",
                        "penetration_rate": r.penetration_rate
                        if r.penetration_rate is not None
                        else "",
                        "battery_installation_gwh": r.battery_installation_gwh
                        if r.battery_installation_gwh is not None
                        else "",
                        "yoy_growth": r.yoy_growth if r.yoy_growth is not None else "",
                        "unit": r.unit,
                        "source": r.source,
                        "source_url": r.source_url,
                        "release_date": r.release_date.isoformat() if r.release_date else "",
                        "data_status": r.data_status,
                        "collected_at": r.collected_at,
                    }
                )
        logger.info("已保存新能源汽车 RAW 明细快照: %s (共 %d 行)", path, len(records))
