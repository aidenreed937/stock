"""Mysteel 大宗化工核心品种（纯碱、PTA、乙二醇、甲醇、PVC）高频周度数据文章链接多轨自动化发现工具。

功能:
1. 扫描四大专区首页 (breed 专区): 自动获取最新 2~3 个月的周度利用率、周产量、库存与周评文章;
2. 提取并整合历史会话转录缓存与搜索引擎发现的历史周评/周数据分析文章;
3. 规范提取 report_date 与产品信息;
4. 幂等增量合并写入 config/data_sources/chemicals_weekly_sources.csv。
"""

from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BREED_TARGETS = [
    ("纯碱", "SA", "https://nenghua.mysteel.com/breed/chunjian/"),
    ("PTA", "TA", "https://nenghua.mysteel.com/breed/pta/"),
    ("乙二醇", "MEG", "https://nenghua.mysteel.com/breed/hxyl/"),
    ("甲醇", "MA", "https://nenghua.mysteel.com/breed/jcjxy/"),
    ("PVC", "V", "https://www.mysteel.com/oilchem/pvczq/"),
]


def extract_date_from_text_or_url(text: str, url: str) -> str | None:
    """从标题或 URL 中精准解析 ISO 格式日期 (YYYY-MM-DD)。"""
    # 1. 优先匹配 (202\d{5}) 或 (202\d-\d{2}-\d{2})
    m = re.search(r"[（\(](202\d)(\d{2})(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    m_iso = re.search(r"(202\d)[-/.](\d{2})[-/.](\d{2})", text)
    if m_iso:
        return f"{m_iso.group(1)}-{m_iso.group(2)}-{m_iso.group(3)}"

    # 2. 从 URL 中的 /a/YYMMDDHH/ 结构提取
    m_url = re.search(r"/a/(\d{2})(\d{2})(\d{2})\d{2}/", url)
    if m_url:
        return f"20{m_url.group(1)}-{m_url.group(2)}-{m_url.group(3)}"

    return None


def scan_breed_pages() -> list[dict[str, str]]:
    """扫描专区首页中包含的全部高频周度数据文章链接。"""
    discovered: list[dict[str, str]] = []
    for p_name, sym, url in BREED_TARGETS:
        logger.info("扫描专区首页 [%s-%s]: %s", p_name, sym, url)
        try:
            resp = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=15)
            if resp.status_code != 200:
                logger.warning("专区首页响应非 200 (HTTP %d): %s", resp.status_code, url)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=re.compile(r"/a/\d+/[A-F0-9a-zA-Z_]+\.html")):
                title = a.get_text().strip()
                href = a["href"].strip()
                if not href.startswith("http"):
                    if href.startswith("//"):
                        href = "https:" + href
                    else:
                        base = (
                            "https://www.mysteel.com"
                            if "oilchem" in href
                            else "https://nenghua.mysteel.com"
                        )
                        href = base + ("" if href.startswith("/") else "/") + href

                d_str = extract_date_from_text_or_url(title, href)
                if not d_str:
                    continue

                # 严格判断是否为该品种周度高频指标相关文章
                is_relevant = False
                if (
                    (
                        sym == "SA"
                        and (
                            "纯碱" in title
                            and any(
                                k in title for k in ["周数据", "产能利用率", "产量", "厂家库存"]
                            )
                        )
                    )
                    or (
                        sym == "TA"
                        and any(
                            k in title
                            for k in [
                                "PTA周评",
                                "PTA样本产量",
                                "PTA生产厂库",
                                "PTA产能利用率",
                                "PTA行业本周看点",
                            ]
                        )
                    )
                    or (
                        sym == "MEG"
                        and any(
                            k in title
                            for k in [
                                "乙二醇周评",
                                "乙二醇企业产能利用率",
                                "乙二醇行业本周看点",
                                "乙二醇装置产能利用率",
                            ]
                        )
                    )
                    or (
                        sym == "MA"
                        and any(
                            k in title
                            for k in [
                                "甲醇产量及产能利用率",
                                "甲醇样本生产企业库存",
                                "甲醇港口库存",
                                "甲醇装置产能利用率",
                            ]
                        )
                    )
                    or (
                        sym == "V"
                        and any(
                            k in title
                            for k in [
                                "PVC产能利用率",
                                "PVC样本第三方库存",
                                "PVC生产企业厂库库存",
                                "PVC周评",
                                "PVC社会库存",
                            ]
                        )
                    )
                ):
                    is_relevant = True

                if is_relevant:
                    discovered.append(
                        {
                            "product_name": p_name,
                            "symbol": sym,
                            "report_date": d_str,
                            "source_url": href,
                            "title": title,
                        }
                    )
        except Exception as exc:
            logger.warning("扫描专区 %s 异常: %s", url, exc)

    logger.info("专区首页扫描完成，发现 %d 篇高频周度文章", len(discovered))
    return discovered


def extract_from_step_cache(step_files: list[Path]) -> list[dict[str, str]]:
    """从缓存的会话转录步骤输出中提取周报链接。"""
    discovered: list[dict[str, str]] = []
    for p in step_files:
        if not p.exists():
            continue
        try:
            raw_text = p.read_text(encoding="utf-8", errors="ignore")
            try:
                content = json.loads(raw_text).get("content", "")
            except Exception:
                content = raw_text

            matches = re.findall(
                r"\[+(.*?)\]+\((https?://nenghua\.mysteel\.com/a/\d+/[A-F0-9a-zA-Z_]+\.html)\)",
                content,
            )
            for title, url in matches:
                title = title.strip()
                d_str = extract_date_from_text_or_url(title, url)
                if not d_str:
                    continue
                if "PTA周评" in title:
                    discovered.append(
                        {
                            "product_name": "PTA",
                            "symbol": "TA",
                            "report_date": d_str,
                            "source_url": url,
                            "title": title,
                        }
                    )
        except Exception as exc:
            logger.warning("解析步输出 %s 异常: %s", p, exc)

    logger.info("从步骤缓存中提取到 %d 篇周报", len(discovered))
    return discovered


# 已通过搜索引擎/调研确认的核心历史周度文章静态补全表
CURATED_HISTORICAL_ARTICLES: list[dict[str, str]] = [
    # PTA (TA)
    {
        "product_name": "PTA",
        "symbol": "TA",
        "report_date": "2024-07-27",
        "source_url": "https://nenghua.mysteel.com/a/24072710/0344363671994264.html",
        "title": "[PTA周评]：宏观弱势拖累市场下跌",
    },
    # 乙二醇 (MEG)
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2024-01-11",
        "source_url": "https://nenghua.mysteel.com/a/24072716/F8A87F68884B2FA2.html",
        "title": "[乙二醇周评]：逢高出货意愿增强 乙二醇本周冲高回落",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2024-01-25",
        "source_url": "https://nenghua.mysteel.com/a/24072715/3A2C6D1E05736B2E.html",
        "title": "[乙二醇周评]：主港库存大幅下降 乙二醇延续上涨走势",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2024-02-08",
        "source_url": "https://nenghua.mysteel.com/a/24072715/8A8523B20614998A.html",
        "title": "[乙二醇周评]：节日气氛浓厚 乙二醇无量下行",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2024-04-25",
        "source_url": "https://nenghua.mysteel.com/a/24071120/96B58A52649DF16B.html",
        "title": "[乙二醇周评]：供应预期悲观 市场破位下跌",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2025-03-06",
        "source_url": "https://nenghua.mysteel.com/a/25030616/B07196104F3CA71A.html",
        "title": "[乙二醇周评]：原油煤炭双跌 乙二醇跌势扩大",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2025-03-20",
        "source_url": "https://nenghua.mysteel.com/a/25032016/014D5029D32E5D8D.html",
        "title": "[乙二醇周评]：供需预期悲观 乙二醇延续下跌",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2025-10-11",
        "source_url": "https://nenghua.mysteel.com/a/25101116/CABC9B02090A803A.html",
        "title": "[乙二醇周评]：成本下移供需转弱 节后市场跌势扩大",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2026-04-09",
        "source_url": "https://nenghua.mysteel.com/a/26040919/CEEAC0DE06FF3AD3.html",
        "title": "[乙二醇周评]：地缘政治反转 乙二醇周内创年内新高后回落",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2026-06-11",
        "source_url": "https://nenghua.mysteel.com/a/26061116/4E47C237AC76BC17.html",
        "title": "[乙二醇周评]：地缘政治再度紧张 乙二醇延续反弹",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2026-07-09",
        "source_url": "https://nenghua.mysteel.com/a/26070916/ABA6A3413E3D94D6.html",
        "title": "[乙二醇周评]：地缘政治再度紧张 乙二醇顺势反弹",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2026-09-10",
        "source_url": "https://nenghua.mysteel.com/a/26091016/A9DB30720F8302BB.html",
        "title": "[乙二醇周评]：供需预期紧张，乙二醇保持强势",
    },
    {
        "product_name": "乙二醇",
        "symbol": "MEG",
        "report_date": "2026-09-17",
        "source_url": "https://nenghua.mysteel.com/a/26091716/0FE4517A6F43FB06.html",
        "title": "[乙二醇周评]：地缘政治紧张 乙二醇继续上涨",
    },
    # 甲醇 (MA)
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2024-06-13",
        "source_url": "https://nenghua.mysteel.com/a/24070420/DA9CA9392503CE8B.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20240607-0613）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2024-07-18",
        "source_url": "https://nenghua.mysteel.com/a/24071814/A62739F441CD7D37.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20240712-0718）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2024-08-22",
        "source_url": "https://nenghua.mysteel.com/a/24082215/25161E7CD004F9BD.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20240816-0822）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2024-08-29",
        "source_url": "https://nenghua.mysteel.com/a/24082914/A4F8A8AFE84170AD.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20240823-0829）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2024-11-21",
        "source_url": "https://nenghua.mysteel.com/a/24112114/1E3DE4975647BD13.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20241115-1121）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2025-02-06",
        "source_url": "https://nenghua.mysteel.com/a/25020615/8E46A4817051F833.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20250131-0206）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2025-07-10",
        "source_url": "https://nenghua.mysteel.com/a/25071014/C0CCA773E38CFD3A.html",
        "title": "[产量/产能利用率]：中国甲醇产量及产能利用率周数据统计 (20250704-0710)",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2025-08-28",
        "source_url": "https://nenghua.mysteel.com/a/25082814/FD9A8B94C116058B.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20250822-0828）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2025-10-16",
        "source_url": "https://nenghua.mysteel.com/a/25101614/A3E3A96AAF9C38B5.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20251010-1016）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2025-10-23",
        "source_url": "https://nenghua.mysteel.com/a/25102315/D2FEAFF484A463BD.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20251017-1023）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2025-11-06",
        "source_url": "https://nenghua.mysteel.com/a/25110614/C88027299A4C07B8.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20251031-1106）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2025-11-27",
        "source_url": "https://nenghua.mysteel.com/a/25112715/2CF3C8C3CA81FCD0.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20251121-1127）",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "report_date": "2025-12-31",
        "source_url": "https://nenghua.mysteel.com/a/25123115/745FF529EE4F044B.html",
        "title": "[数据分析]：中国甲醇产量及产能利用率周数据分析(20251226-20260101）",
    },
    # PVC (V)
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2024-09-27",
        "source_url": "https://nenghua.mysteel.com/a/24092708/DB400FC8979DF368.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20240921-20240927）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2024-12-06",
        "source_url": "https://nenghua.mysteel.com/a/24120610/FB92082E2CE86C86.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20241130-20241206）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-04-25",
        "source_url": "https://nenghua.mysteel.com/a/25042509/4CC58342557185F7.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20250419-20250425）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-05-02",
        "source_url": "https://www.mysteel.com/oilchem/a/25050208/AE69DE1ADFB0F1CC.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20250426-20250502）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-05-30",
        "source_url": "https://nenghua.mysteel.com/a/25053009/FB18BEDEDC2A9A3C.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20250524-20250530）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-06-20",
        "source_url": "https://nenghua.mysteel.com/a/25062009/DBC2BFFE813155D0.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20250614-20250620）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-08-01",
        "source_url": "https://nenghua.mysteel.com/a/25080109/58466C2E40D8343B.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20250726-20250801）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-09-12",
        "source_url": "https://nenghua.mysteel.com/a/25091209/72A0914AFA7EE6F2.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20250906-20250912）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-10-10",
        "source_url": "https://nenghua.mysteel.com/a/25101009/3761B7F100B4768A.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20251004-20251010）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-10-17",
        "source_url": "https://nenghua.mysteel.com/a/25101709/7AE2BE1AABC1DCF4.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20251011-20251017）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-10-31",
        "source_url": "https://nenghua.mysteel.com/a/25103109/0A9A91A68BD3158F.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20251025-20251031）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-11-28",
        "source_url": "https://nenghua.mysteel.com/a/25112809/4CBCAB3D93BF9316.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20251122-20251128）",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "report_date": "2025-12-26",
        "source_url": "https://nenghua.mysteel.com/a/25122609/824A26F7A8B67F85.html",
        "title": "[数据分析]：中国PVC产能利用率周数据分析（20251220-20251226）",
    },
]


def update_chemicals_sources_csv(
    items: list[dict[str, str]],
    csv_path: Path,
) -> int:
    """增量写入 config/data_sources/chemicals_weekly_sources.csv。"""
    existing: dict[tuple[str, str, str], dict[str, str]] = {}
    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                key = (r["product_name"], r["symbol"], r["report_date"])
                existing[key] = r

    added_count = 0
    for item in items:
        p_name = item["product_name"]
        sym = item["symbol"]
        d_str = item["report_date"]
        url = item["source_url"]
        key = (p_name, sym, d_str)
        if key not in existing:
            existing[key] = {
                "product_name": p_name,
                "symbol": sym,
                "report_date": d_str,
                "source_url": url,
            }
            added_count += 1

    rows = list(existing.values())
    rows.sort(key=lambda r: (r["product_name"], r["report_date"]), reverse=True)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["product_name", "symbol", "report_date", "source_url"]
        )
        writer.writeheader()
        writer.writerows(rows)

    logger.info("已向 %s 增量写入 %d 条新记录，总配置数: %d", csv_path, added_count, len(rows))
    return added_count


def main():
    csv_path = Path("config/data_sources/chemicals_weekly_sources.csv")
    step_dir = Path(
        "/Users/mac/.gemini/antigravity/brain/0f8afb4d-e993-4fdb-a3da-637ae266fdb5/.system_generated/steps"
    )
    step_files = [step_dir / f"{s}" / "output.txt" for s in [181, 251]]

    all_discovered: list[dict[str, str]] = []

    # 1. 扫描专区首页
    breed_items = scan_breed_pages()
    all_discovered.extend(breed_items)

    # 2. 提取转录步骤缓存
    step_items = extract_from_step_cache(step_files)
    all_discovered.extend(step_items)

    # 3. 补充静态已确认周报
    all_discovered.extend(CURATED_HISTORICAL_ARTICLES)

    # 4. 增量写入
    added = update_chemicals_sources_csv(all_discovered, csv_path)
    logger.info("Mysteel 周报链接发现与注册完成！新增: %d", added)


if __name__ == "__main__":
    main()
