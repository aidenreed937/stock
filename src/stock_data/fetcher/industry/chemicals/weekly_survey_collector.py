"""全品种化工高频周度产业调查快讯采集器 (ChemicalWeeklySurveyCollector)。

数据属性与多源 2-Tier ETL 架构:
1. 覆盖 4 大核心链主大宗化工品种:
   - 纯碱 (SA): 36 家样本综合产能利用率、实物产量、厂家总库存、出货率;
   - 烧碱 (SH): 113 家样本企业 (4429 万吨有效产能) 平均产能利用率、厂家库存、氧化铝开工率;
   - PTA (TA): 27 家样本企业 (9330 万吨有效产能) 周度产能利用率、周产量、聚酯开工率、社会库存;
   - 甲醇 (MA): 183 家样本企业周度产能利用率、周产量、下游 MTO 烯烃开工率;
2. 真实来源:
   - 生意社 (100ppi): 官方商品情报站与每周四快报;
   - 隆众资讯 (Longzhong / Mysteel 能化): 官方一手统计周报;
3. 2-Tier 存储: 物理 RAW CSV 保存在 data/raw/industry/chemicals/operating_rates/weekly_survey.csv;
4. 消除前视偏差: release_date 为文章官方发布日 (工作日每周四/周五生效);
5. 双周提取机制: 充分利用周报中同时披露的【当周真实值】与【上周真实值】。
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import requests
from bs4 import BeautifulSoup

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

WEEKLY_SURVEY_SCHEMA = {
    "trade_date": pl.Date,
    "report_date": pl.Date,
    "product_name": pl.String,
    "symbol": pl.String,
    "operating_rate_pct": pl.Float64,
    "weekly_output_w_tons": pl.Float64,
    "factory_inventory_w_tons": pl.Float64,
    "shipment_rate_pct": pl.Float64,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "collected_at": pl.String,
}

# 隆众/Mysteel 官方周报 URL 真实池 (纯碱 SA、烧碱 SH、PTA TA、甲醇 MA)
MYSTEEL_WEEKLY_URLS: list[tuple[str, str, str, str]] = [
    # ---------------- 1. 纯碱 (SA) ----------------
    ("纯碱", "SA", "2026-08-06", "https://nenghua.mysteel.com/a/26080615/90DB16F780E1BA89.html"),
    ("纯碱", "SA", "2026-07-09", "https://nenghua.mysteel.com/a/26070915/7E6E44026D7BBE3F.html"),
    ("纯碱", "SA", "2026-06-25", "https://nenghua.mysteel.com/a/26062516/BC3E856CCCE80399.html"),
    ("纯碱", "SA", "2026-05-28", "https://nenghua.mysteel.com/a/26052816/6717008311C016C7.html"),
    ("纯碱", "SA", "2026-04-23", "https://nenghua.mysteel.com/a/26042315/07F4CB5EE1E1AD5F.html"),
    ("纯碱", "SA", "2026-03-12", "https://nenghua.mysteel.com/a/26031217/66856A10ED66D3E6.html"),
    ("纯碱", "SA", "2026-03-05", "https://nenghua.mysteel.com/a/26030516/E2D83E809E961FC6.html"),
    ("纯碱", "SA", "2025-12-04", "https://nenghua.mysteel.com/a/25120515/B838FA5845F7413D.html"),
    ("纯碱", "SA", "2025-11-06", "https://nenghua.mysteel.com/a/25110711/101644FD37BA123E.html"),
    ("纯碱", "SA", "2025-09-18", "https://nenghua.mysteel.com/a/25091914/D4A1B5749038850D.html"),
    (
        "纯碱",
        "SA",
        "2025-08-21",
        "https://nenghua.mysteel.com/a/25082209/522C519A03EC2DEB_abc.html",
    ),
    ("纯碱", "SA", "2025-06-05", "https://nenghua.mysteel.com/a/25060517/CA60EDA067DCFED4.html"),
    ("纯碱", "SA", "2025-02-20", "https://nenghua.mysteel.com/a/25022017/8A4AF575DCC2097D.html"),
    # ---------------- 2. 烧碱 (SH) ----------------
    ("烧碱", "SH", "2026-07-23", "https://nenghua.mysteel.com/a/26072311/68558E5B6E5D96D8.html"),
    ("烧碱", "SH", "2026-03-09", "https://nenghua.mysteel.com/a/26030908/7DA1C994C268AD75.html"),
    ("烧碱", "SH", "2026-02-05", "https://nenghua.mysteel.com/a/26020615/A1D52FC8191415F6.html"),
    ("烧碱", "SH", "2025-12-18", "https://nenghua.mysteel.com/a/25121814/FD2769E6B896EDB1.html"),
    ("烧碱", "SH", "2025-11-06", "https://nenghua.mysteel.com/a/25110611/8AD9963827815113.html"),
    # ---------------- 3. PTA (TA) ----------------
    ("PTA", "TA", "2026-07-02", "https://nenghua.mysteel.com/a/26070217/E435857A054BE2FC.html"),
    ("PTA", "TA", "2026-06-26", "https://nenghua.mysteel.com/a/26062617/9A8E4E106715A019.html"),
    ("PTA", "TA", "2026-05-12", "https://nenghua.mysteel.com/a/26051213/FCD5AFFCBD473FF6.html"),
    # ---------------- 4. 甲醇 (MA) ----------------
    ("甲醇", "MA", "2025-08-28", "https://nenghua.mysteel.com/a/25082814/FD9A8B94C116058B.html"),
]


class ChemicalWeeklySurveyCollector:
    """全品种周度化工高频产业调查快讯采集器 (支持 纯碱/烧碱/PTA/甲醇 多源并行)。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.survey_dir = self.raw_dir / "chemicals" / "operating_rates"
        self.survey_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/128.0.0.0",
        }

    def _fetch_html_with_cookie_bypass(self, url: str) -> str:
        try:
            r1 = self.session.get(url, headers=self.headers, timeout=10)
            m = re.search(r'var _0x2 = "([a-f0-9]+)";', r1.text)
            if m:
                token = m.group(1)
                self.session.cookies.set("HW_CHECK", token, domain="100ppi.com")
                r2 = self.session.get(url, headers=self.headers, timeout=10)
                r2.encoding = "utf-8"
                return r2.text
            r1.encoding = "utf-8"
            return r1.text
        except Exception as e:
            logger.warning(f"请求失败 [{url}]: {e}")
            return ""

    def _load_raw_csv(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        return load_weekly_survey_raw_csv(self.survey_dir)

    def _save_raw_csv(self, records: dict[tuple[str, str, str], dict[str, Any]]) -> None:
        save_weekly_survey_raw_csv(self.survey_dir, records)

    def collect(self, current_year: int = 2026) -> pl.DataFrame:
        """执行全品种周度快讯解析与 2-Tier Upsert (纯碱/烧碱/PTA/甲醇)。"""
        records = self._load_raw_csv()
        now_iso = now_utc_iso()

        collect_100ppi_weekly_records(
            records,
            fetch_html=self._fetch_html_with_cookie_bypass,
            current_year=current_year,
            now_iso=now_iso,
        )

        # =========================================================================
        # 通道 2: 隆众资讯 (Longzhong / Mysteel) 全品种周报 (纯碱/烧碱/PTA/甲醇)
        # =========================================================================
        for prod_name, sym, d_str, url_lz in MYSTEEL_WEEKLY_URLS:
            try:
                r_lz = self.session.get(url_lz, headers=self.headers, timeout=10)
                if r_lz.status_code == 200:
                    r_lz.encoding = "utf-8"
                    t_lz = r_lz.text

                    # 1. 提取【当周】核心数据
                    # 通用开工率/利用率模式
                    pat_util = re.search(
                        r"(?:产能利用率|平均利用率|开工率|开工|负荷|利用率)[^\d%]{0,30}?(?:为|至|在|达)?\s*([4-9]\d(?:\.\d+)?)%",
                        t_lz,
                    )
                    pat_out = re.search(r"(?:产量)[^\d]{0,10}?([\d\.]+)\s*万吨", t_lz)
                    pat_inv_match = re.search(
                        r"(?:库存|厂家总库存|社会库存|企业库存)[^\d]{0,20}?([\d\.]+)\s*万吨", t_lz
                    )

                    r_d = date.fromisoformat(d_str)
                    key = (prod_name, d_str, "Longzhong_Oilchem")
                    rec = records.get(
                        key,
                        {
                            "trade_date": r_d,
                            "report_date": r_d,
                            "product_name": prod_name,
                            "symbol": sym,
                            "operating_rate_pct": None,
                            "weekly_output_w_tons": None,
                            "factory_inventory_w_tons": None,
                            "shipment_rate_pct": None,
                            "source": "Longzhong_Oilchem",
                            "source_url": url_lz,
                            "release_date": r_d,
                            "collected_at": now_iso,
                        },
                    )
                    if pat_util:
                        rec["operating_rate_pct"] = float(pat_util.group(1))
                    if pat_out:
                        rec["weekly_output_w_tons"] = float(pat_out.group(1))
                    if pat_inv_match:
                        rec["factory_inventory_w_tons"] = float(pat_inv_match.group(1))
                    records[key] = rec

                    # 2. 提取【上周】核心数据
                    pat_last_util = re.search(r"上周\s*([4-9]\d(?:\.\d+)?)%", t_lz)
                    if pat_last_util:
                        prev_d = r_d - timedelta(days=7)
                        prev_d_str = prev_d.isoformat()
                        prev_key = (prod_name, prev_d_str, "Longzhong_Oilchem")
                        prev_rec = records.get(
                            prev_key,
                            {
                                "trade_date": prev_d,
                                "report_date": prev_d,
                                "product_name": prod_name,
                                "symbol": sym,
                                "operating_rate_pct": float(pat_last_util.group(1)),
                                "weekly_output_w_tons": None,
                                "factory_inventory_w_tons": None,
                                "shipment_rate_pct": None,
                                "source": "Longzhong_Oilchem",
                                "source_url": url_lz,
                                "release_date": r_d,
                                "collected_at": now_iso,
                            },
                        )
                        prev_rec["operating_rate_pct"] = float(pat_last_util.group(1))
                        records[prev_key] = prev_rec
            except Exception as e:
                logger.warning(f"隆众周报解析失败 [{url_lz}]: {e}")

        if records:
            self._save_raw_csv(records)

        if not records:
            return pl.DataFrame(schema=WEEKLY_SURVEY_SCHEMA)

        df = pl.DataFrame(list(records.values()), schema=WEEKLY_SURVEY_SCHEMA).sort(
            ["product_name", "report_date", "source"]
        )
        return df


def load_weekly_survey_raw_csv(survey_dir: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    """读取周度化工调查 RAW CSV。"""
    csv_file = survey_dir / "weekly_survey.csv"
    if not csv_file.exists():
        return {}

    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    with csv_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d_str = row["report_date"].strip()
            prod = row["product_name"].strip()
            src = row.get("source", "100ppi_Weekly").strip()
            records[(prod, d_str, src)] = {
                "trade_date": date.fromisoformat(d_str),
                "report_date": date.fromisoformat(d_str),
                "product_name": prod,
                "symbol": row.get("symbol") or "SA",
                "operating_rate_pct": _float_from_row("operating_rate_pct", row),
                "weekly_output_w_tons": _float_from_row("weekly_output_w_tons", row),
                "factory_inventory_w_tons": _float_from_row("factory_inventory_w_tons", row),
                "shipment_rate_pct": _float_from_row("shipment_rate_pct", row),
                "source": src,
                "source_url": row.get("source_url") or "",
                "release_date": date.fromisoformat(row["release_date"].strip())
                if row.get("release_date")
                else date.fromisoformat(d_str),
                "collected_at": row.get("collected_at") or now_utc_iso(),
            }
    return records


def save_weekly_survey_raw_csv(
    survey_dir: Path, records: dict[tuple[str, str, str], dict[str, Any]]
) -> None:
    """保存周度化工调查 RAW CSV。"""
    csv_file = survey_dir / "weekly_survey.csv"
    rows = sorted(
        records.values(), key=lambda r: (r["product_name"], r["report_date"], r["source"])
    )
    fieldnames = [
        "trade_date",
        "report_date",
        "product_name",
        "symbol",
        "operating_rate_pct",
        "weekly_output_w_tons",
        "factory_inventory_w_tons",
        "shipment_rate_pct",
        "source",
        "source_url",
        "release_date",
        "collected_at",
    ]
    with csv_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(_weekly_survey_row_to_csv(r))


def collect_100ppi_weekly_records(
    records: dict[tuple[str, str, str], dict[str, Any]],
    fetch_html: Callable[[str], str],
    current_year: int,
    now_iso: str,
) -> None:
    """解析生意社官方纯碱情报站周度开工、库存与出货率。"""
    soda_qb_url = "https://www.100ppi.com/qb/?pid=533"
    html_100ppi = fetch_html(soda_qb_url)
    if not html_100ppi:
        return

    text = BeautifulSoup(html_100ppi, "html.parser").get_text()
    pat_rate = re.findall(
        r"(\d{1,2})月(\d{1,2})日(?:当周)?[，,\s]*纯碱(?:装置)?开工率[为\s]*([\d\.]+)%(?:[，,\s]*较上周[增加减少]+[\d\.]+%[；;])?(?:[，,\s]*纯碱产量[为\s]*([\d\.]+)万吨)?",
        text,
    )
    for mo_s, da_s, rate_s, out_s in pat_rate:
        rec = _get_100ppi_record(records, current_year, int(mo_s), int(da_s), soda_qb_url, now_iso)
        rec["operating_rate_pct"] = float(rate_s)
        if out_s:
            rec["weekly_output_w_tons"] = float(out_s)

    pat_inv = re.findall(
        r"(\d{1,2})月(\d{1,2})日[，,\s]*(?:周初|本周)?国内纯碱(?:库存|厂家总库存)[为\s]*([\d\.]+)万吨",
        text,
    )
    for mo_s, da_s, inv_s in pat_inv:
        rec = _get_100ppi_record(records, current_year, int(mo_s), int(da_s), soda_qb_url, now_iso)
        rec["factory_inventory_w_tons"] = float(inv_s)

    pat_ship = re.findall(
        r"(\d{1,2})月(\d{1,2})日[，,\s]*本周中国纯碱企业出货量[为\s]*([\d\.]+)万吨[^\n]*?纯碱(?:整体)?出货率在[为\s]*([\d\.]+)%",
        text,
    )
    for mo_s, da_s, _out_s, ship_s in pat_ship:
        rec = _get_100ppi_record(records, current_year, int(mo_s), int(da_s), soda_qb_url, now_iso)
        rec["shipment_rate_pct"] = float(ship_s)


def _get_100ppi_record(
    records: dict[tuple[str, str, str], dict[str, Any]],
    current_year: int,
    month: int,
    day: int,
    source_url: str,
    now_iso: str,
) -> dict[str, Any]:
    r_d = date(current_year, month, day)
    d_str = r_d.isoformat()
    key = ("纯碱", d_str, "100ppi_Weekly")
    rec = records.get(
        key,
        {
            "trade_date": r_d,
            "report_date": r_d,
            "product_name": "纯碱",
            "symbol": "SA",
            "operating_rate_pct": None,
            "weekly_output_w_tons": None,
            "factory_inventory_w_tons": None,
            "shipment_rate_pct": None,
            "source": "100ppi_Weekly",
            "source_url": source_url,
            "release_date": r_d,
            "collected_at": now_iso,
        },
    )
    records[key] = rec
    return rec


def _float_from_row(k: str, r: dict[str, str]) -> float | None:
    v = r.get(k)
    return float(v) if v and v.strip() else None


def _weekly_survey_row_to_csv(r: dict[str, Any]) -> dict[str, object]:
    return {
        "trade_date": r["trade_date"].isoformat(),
        "report_date": r["report_date"].isoformat(),
        "product_name": r["product_name"],
        "symbol": r["symbol"],
        "operating_rate_pct": r["operating_rate_pct"]
        if r["operating_rate_pct"] is not None
        else "",
        "weekly_output_w_tons": r["weekly_output_w_tons"]
        if r["weekly_output_w_tons"] is not None
        else "",
        "factory_inventory_w_tons": r["factory_inventory_w_tons"]
        if r["factory_inventory_w_tons"] is not None
        else "",
        "shipment_rate_pct": r["shipment_rate_pct"] if r["shipment_rate_pct"] is not None else "",
        "source": r["source"],
        "source_url": r["source_url"],
        "release_date": r["release_date"].isoformat(),
        "collected_at": r["collected_at"],
    }
