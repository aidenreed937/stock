"""国家统计局 (NBS) 流通领域重要生产资料市场价格变动情况解析器。"""

from __future__ import annotations

import calendar
import csv
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

DEFAULT_NBS_COMMODITY_MAPPING: dict[str, dict[str, Any]] = {
    "H2SO4": {
        "pattern": r"硫酸[（(]98%[）)]?",
        "symbol": "H2SO4",
        "product_name": "硫酸",
        "spec": "98%;工业级浓硫酸",
        "unit": "元/吨",
        "min_price": 50.0,
        "max_price": 3500.0,
    },
    "NaOH": {
        "pattern": r"烧碱[（(]液碱[，,]32%[）)]?",
        "symbol": "NaOH",
        "product_name": "烧碱",
        "spec": "液碱;32%",
        "unit": "元/吨",
        "min_price": 200.0,
        "max_price": 3000.0,
    },
    "Methanol": {
        "pattern": r"甲醇[（(]优等品[）)]?",
        "symbol": "Methanol",
        "product_name": "甲醇",
        "spec": "优等品",
        "unit": "元/吨",
        "min_price": 1000.0,
        "max_price": 6000.0,
    },
    "Benzene": {
        "pattern": r"纯苯[（(]石油苯[，,]工业级[）)]?",
        "symbol": "Benzene",
        "product_name": "纯苯",
        "spec": "石油苯;工业级",
        "unit": "元/吨",
        "min_price": 2000.0,
        "max_price": 15000.0,
    },
}


def parse_nbs_report_metadata(soup: BeautifulSoup) -> tuple[str, date | None, date | None]:
    """从 NBS 公报 HTML 抽取报告标题、发布日期与所属旬度基准日期。

    Returns:
        (title, release_date, trade_date)
    """
    title_meta = soup.find("meta", {"name": "ArticleTitle"})
    title = ""
    if title_meta and title_meta.get("content"):
        title = str(title_meta["content"]).strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    pub_meta = soup.find("meta", {"name": "PubDate"})
    release_date: date | None = None
    if pub_meta and pub_meta.get("content"):
        raw_pub = str(pub_meta["content"]).split()[0].replace("/", "-")
        try:
            release_date = date.fromisoformat(raw_pub)
        except ValueError:
            pass

    # 解析旬度: 2026年9月上旬
    trade_date: date | None = None
    m = re.search(r"(\d{4})年(\d{1,2})月(上旬|中旬|下旬)", title)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        tenday = m.group(3)
        if tenday == "上旬":
            day = 10
        elif tenday == "中旬":
            day = 20
        else:
            day = calendar.monthrange(year, month)[1]
        trade_date = date(year, month, day)

    if trade_date and release_date is None:
        release_date = trade_date

    return title, release_date, trade_date


def extract_nbs_commodity_prices(
    html: str,
    source_url: str = "",
    target_symbols: list[str] | None = None,
) -> list[dict[str, Any]]:
    """从 NBS 流通领域重要生产资料公报 HTML 中提取指定大宗商品现货价格。"""
    soup = BeautifulSoup(html, "html.parser")
    title, release_date, trade_date = parse_nbs_report_metadata(soup)

    if not trade_date:
        logger.warning("未能从标题中提取旬度日期: %s", title)
        return []

    target_configs = {
        k: v
        for k, v in DEFAULT_NBS_COMMODITY_MAPPING.items()
        if target_symbols is None or k in target_symbols
    }

    now_iso = now_utc_iso()
    records: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()

    for tr in soup.find_all("tr"):
        row_text = tr.get_text(separator=" ", strip=True)
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) < 3:
            continue

        for sym, cfg in target_configs.items():
            if sym in seen_symbols:
                continue
            if not re.search(cfg["pattern"], tds[0]) and not re.search(cfg["pattern"], row_text):
                continue

            # 遍历后续单元格寻找合理价格数值
            price_val: float | None = None
            for cell in tds[1:]:
                clean_cell = cell.replace(",", "").strip()
                try:
                    v = float(clean_cell)
                    if cfg["min_price"] <= v <= cfg["max_price"]:
                        price_val = v
                        break
                except ValueError:
                    continue

            if price_val is not None:
                seen_symbols.add(sym)
                records.append(
                    {
                        "trade_date": trade_date.isoformat(),
                        "report_date": trade_date.isoformat(),
                        "product_name": cfg["product_name"],
                        "symbol": cfg["symbol"],
                        "spec": cfg["spec"],
                        "spot_price_cny": price_val,
                        "unit": cfg["unit"],
                        "source": "NBS_流通领域重要生产资料",
                        "source_url": source_url,
                        "release_date": release_date.isoformat()
                        if release_date
                        else trade_date.isoformat(),
                        "data_status": "verified_industry_report",
                        "collected_at": now_iso,
                    }
                )

    return records


def save_nbs_prices_to_survey_csv(
    records: list[dict[str, Any]],
    csv_path: Path | str,
) -> Path:
    """原子更新/追加价格记录至 expert_prices_survey.csv，按 (symbol, trade_date) 幂等去重。"""
    target = Path(csv_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trade_date",
        "report_date",
        "product_name",
        "symbol",
        "spec",
        "spot_price_cny",
        "unit",
        "source",
        "source_url",
        "release_date",
        "data_status",
        "collected_at",
    ]

    existing_rows: dict[tuple[str, str], dict[str, Any]] = {}
    if target.exists():
        with target.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = str(row.get("symbol") or "")
                d_str = str(row.get("trade_date") or "")
                existing_rows[(sym, d_str)] = row

    for rec in records:
        sym = str(rec.get("symbol") or "")
        d_str = str(rec.get("trade_date") or "")
        existing_rows[(sym, d_str)] = rec

    sorted_rows = sorted(
        existing_rows.values(),
        key=lambda item: (
            str(item.get("product_name") or ""),
            str(item.get("trade_date") or ""),
        ),
    )

    with target.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted_rows)

    return target
