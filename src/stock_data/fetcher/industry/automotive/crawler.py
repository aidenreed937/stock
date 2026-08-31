"""中国汽车动力电池产业创新联盟 (CABIA) 与乘联会 (CPCA) 官方通报轻量解析器与爬虫。"""

from __future__ import annotations

import csv
import gzip
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    read_raw_text,
)
from stock_data.fetcher.industry.models import NevMonthlyRecord

logger = logging.getLogger(__name__)

CABIA_BASE_URL = "http://www.cabr-ac.com"
CPCA_BASE_URL = "http://www.cpcaauto.com"


def parse_matrix_file(p: Path) -> dict[str, float]:
    """从 CPCA 二维宽表矩阵 (行: 月份, 列: 年份) 中解析月度时序字典。"""
    res: dict[str, float] = {}
    if not p.exists():
        return res
    with p.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        year_cols = [
            c
            for c in (reader.fieldnames or [])
            if c != "month" and c.strip().replace("年", "").isdigit()
        ]
        for row in reader:
            mo_raw = str(row["month"]).strip().replace("月", "")
            try:
                mo_int = int(mo_raw)
            except ValueError:
                continue
            for yr_col in year_cols:
                yr_int = int(yr_col.replace("年", ""))
                val = row.get(yr_col)
                if val is not None and str(val).strip() not in ("", "nan", "None"):
                    try:
                        f_val = float(str(val).strip())
                        if f_val > 0:
                            res[f"{yr_int:04d}-{mo_int:02d}"] = round(f_val, 4)
                    except (ValueError, TypeError):
                        continue
    return res


def parse_cabia_battery_article(text: str, source_url: str = "") -> dict[str, Any] | None:
    """从 CABIA / 动力电池产业联盟官方通报正文中提取所属月份、发布日期与动力电池装车量 (GWh)。"""
    clean_text = text.replace(" ", "").replace("\r", "")
    if "动力电池" not in clean_text and "装车量" not in clean_text and "GWh" not in clean_text:
        return None

    month_m = re.search(
        r"(20\d\d)\s*年\s*(?:1-)?(\d{1,2})\s*月(?:份)?(?!\s*\d{1,2}\s*日)", clean_text
    )
    if not month_m:
        return None
    year = int(month_m.group(1))
    month = int(month_m.group(2))
    report_month = f"{year:04d}-{month:02d}"

    rel_date = None
    date_m = re.search(r"(20\d\d)[年\-/](\d{1,2})[月\-/](\d{1,2})", clean_text)
    if date_m:
        ry, rm, rd = int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3))
        try:
            rel_date = date(ry, rm, rd)
        except ValueError:
            pass

    battery_gwh: float | None = None
    bat_m = re.search(
        r"(?:我国)?动力(?:和储能)?电池装车量(?:共计|达到|为)?\s*(\d+\.?\d*)\s*(?:GWh|吉瓦时|gwh)",
        clean_text,
    )
    if not bat_m:
        bat_m = re.search(r"装车量(?:共计|达到|为)?\s*(\d+\.?\d*)\s*(?:GWh|吉瓦时|gwh)", clean_text)
    if bat_m:
        battery_gwh = round(float(bat_m.group(1)), 2)

    yoy_val: float | None = None
    yoy_m = re.search(
        r"装车量[^\d]*\d+\.?\d*\s*GWh[^\d%]*[，,]同比增长(?:约)?(\d+\.?\d*)%",
        clean_text,
    )
    if yoy_m:
        yoy_val = round(float(yoy_m.group(1)) / 100.0, 4)

    if battery_gwh is None:
        return None

    return {
        "report_month": report_month,
        "release_date": rel_date,
        "battery_installation_gwh": battery_gwh,
        "yoy_growth": yoy_val,
        "source": "CABIA",
        "source_url": source_url or "http://www.cabr-ac.com/",
        "collected_at": now_utc_iso(),
    }


def parse_cpca_bulletin_article(text: str, source_url: str = "") -> dict[str, Any] | None:
    """从乘联会 CPCA 全国乘用车市场分析月报正文中提取新能源零售、出口与批发数据 (万辆)。"""
    clean_text = text.replace(" ", "").replace("\r", "")
    if "新能源" not in clean_text:
        return None

    month_m = re.search(
        r"(20\d\d)\s*年\s*(?:1-)?(\d{1,2})\s*月(?:份)?(?!\s*\d{1,2}\s*日)", clean_text
    )
    if not month_m:
        return None
    year = int(month_m.group(1))
    month = int(month_m.group(2))
    report_month = f"{year:04d}-{month:02d}"

    rel_date = None
    date_m = re.search(r"(20\d\d)[年\-/](\d{1,2})[月\-/](\d{1,2})", clean_text)
    if date_m:
        ry, rm, rd = int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3))
        try:
            rel_date = date(ry, rm, rd)
        except ValueError:
            pass

    wholesale_vol: float | None = None
    ws_m = re.search(r"新能源(?:乘用车)?批发(?:销量)?(?:达到|为)?\s*(\d+\.?\d*)\s*万辆", clean_text)
    if ws_m:
        wholesale_vol = round(float(ws_m.group(1)), 4)

    retail_vol: float | None = None
    ret_m = re.search(
        r"新能源(?:乘用车)?(?:国内)?零售(?:销量)?(?:达到|为)?\s*(\d+\.?\d*)\s*万辆", clean_text
    )
    if ret_m:
        retail_vol = round(float(ret_m.group(1)), 4)

    export_vol: float | None = None
    exp_m = re.search(
        r"新能源(?:乘用车)?出口(?:销量)?(?:达到|为)?\s*(\d+\.?\d*)\s*万辆", clean_text
    )
    if exp_m:
        export_vol = round(float(exp_m.group(1)), 4)

    pen_rate: float | None = None
    pen_m = re.search(r"(?:零售|批发)?渗透率(?:达到|为)?\s*(\d+\.?\d*)%", clean_text)
    if pen_m:
        pen_rate = round(float(pen_m.group(1)) / 100.0, 4)

    if wholesale_vol is None and retail_vol is None and export_vol is None:
        return None

    return {
        "report_month": report_month,
        "release_date": rel_date,
        "wholesale_volume_ten_thousand": wholesale_vol,
        "retail_volume_ten_thousand": retail_vol,
        "export_volume_ten_thousand": export_vol,
        "penetration_rate": pen_rate,
        "source": "CPCA",
        "source_url": source_url or "http://www.cpcaauto.com/",
        "collected_at": now_utc_iso(),
    }


def fetch_cpca_akshare_records(cpca_dir: Path) -> list[NevMonthlyRecord]:
    """通过 AkShare 在线抓取乘联会官方新能源产销与渗透率数据并保存快照。"""
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
    cache_data: list[dict[str, Any]] = []

    for m_str in sorted(nev_map.keys()):
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
            yoy_growth=None,
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
    snapshot_file = cpca_dir / "nev_sales_live.json.gz"
    try:
        with gzip.open(snapshot_file, "wt", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        logger.info("已保存乘联会官方实时快照: %s (共 %d 月)", snapshot_file, len(records))
    except Exception as e:
        logger.error("保存乘联会快照异常: %s", e)

    return records


class CabiaCrawler:
    """中国汽车动力电池产业创新联盟 (CABIA) 月度装机通报采集适配器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.cabia_dir = self.raw_dir / "automotive" / "cabia"

    def fetch_latest_bulletins(self) -> dict[str, dict[str, Any]]:
        """扫描本地快照并解析动力电池月度装车量记录。"""
        self.cabia_dir.mkdir(parents=True, exist_ok=True)
        results: dict[str, dict[str, Any]] = {}

        for ext in ["*.html", "*.txt", "*.json"]:
            for file_p in sorted(self.cabia_dir.glob(ext)):
                content = read_raw_text(file_p)
                if content:
                    parsed = parse_cabia_battery_article(content, source_url=str(file_p))
                    if parsed and "report_month" in parsed:
                        results[parsed["report_month"]] = parsed

        return results


class CpcaBulletinCrawler:
    """乘联会 (CPCA) 全国乘用车市场分析月报采集适配器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.cpca_dir = self.raw_dir / "cpca"

    def fetch_latest_bulletins(self) -> dict[str, dict[str, Any]]:
        """扫描本地快照并解析乘联会零售/出口/批发月度记录。"""
        self.cpca_dir.mkdir(parents=True, exist_ok=True)
        results: dict[str, dict[str, Any]] = {}

        for ext in ["*.html", "*.txt", "*.json"]:
            for file_p in sorted(self.cpca_dir.glob(ext)):
                content = read_raw_text(file_p)
                if content:
                    parsed = parse_cpca_bulletin_article(content, source_url=str(file_p))
                    if parsed and "report_month" in parsed:
                        results[parsed["report_month"]] = parsed

        return results
