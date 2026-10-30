"""钛白粉 (TiO2) Mysteel 周度开工率与产量文章链接自动化发现与配置同步工具。

功能:
1. 动态扫描 Mysteel 钛白粉专区首页 (https://nenghua.mysteel.com/breed/taibaifen/) 获取最新周评/日评/生产动态；
2. 整合跨越 2024~2026 年（约 2.5 年，100+ 周）的历史高频文章链接；
3. 规范化提取 report_date，剔除冗余修饰与移动端 URL 污染；
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

TAIBAIFEN_BREED_URL = "https://nenghua.mysteel.com/breed/taibaifen/"
CSV_PATH = Path("config/data_sources/chemicals_weekly_sources.csv")
SCRATCH_JSON = Path(
    "/Users/mac/.gemini/antigravity/brain/9d96a9c5-5e92-4d24-a510-a351967ea787/scratch/tio2_articles.json"
)


def clean_mysteel_url(url: str) -> str:
    """清理并标准化 Mysteel 文章 URL。"""
    u = url.strip()
    u = re.sub(r"https?://nenghua\.m\.mysteel\.com", "https://nenghua.mysteel.com", u)
    u = re.sub(r"_abc\.html", ".html", u)
    if u.startswith("//"):
        u = "https:" + u
    return u


def scan_taibaifen_breed_page() -> list[dict[str, str]]:
    """扫描钛白粉专区首页获取最新文章链接。"""
    logger.info("扫描 Mysteel 钛白粉专区首页: %s", TAIBAIFEN_BREED_URL)
    discovered: list[dict[str, str]] = []
    try:
        resp = requests.get(
            TAIBAIFEN_BREED_URL, headers=HEADERS, impersonate="chrome120", timeout=15
        )
        if resp.status_code != 200:
            logger.warning("专区首页响应非 200 (HTTP %d)", resp.status_code)
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        seen_urls: set[str] = set()
        for a in soup.find_all(
            "a", href=re.compile(r"/a/(\d{2})(\d{2})(\d{2})\d{2}/[A-F0-9a-zA-Z_]+\.html")
        ):
            title = a.get_text().strip()
            href = clean_mysteel_url(a["href"])
            m = re.search(r"/a/(\d{2})(\d{2})(\d{2})\d{2}/", href)
            if not m:
                continue
            d_str = f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"
            if any(
                k in title
                for k in [
                    "周评",
                    "日评",
                    "产能利用率",
                    "开工",
                    "产量",
                    "聚焦",
                    "钛白粉市场",
                    "动态",
                ]
            ):
                if href not in seen_urls:
                    seen_urls.add(href)
                    discovered.append(
                        {
                            "product_name": "钛白粉",
                            "symbol": "TIO2",
                            "report_date": d_str,
                            "source_url": href,
                            "title": title,
                        }
                    )
        logger.info("专区首页扫描完成，发现 %d 篇相关文章", len(discovered))
    except Exception as exc:
        logger.warning("扫描专区异常: %s", exc)
    return discovered


def load_historical_articles() -> list[dict[str, str]]:
    """加载历史跨度（2024-2026）的已验证文章清单。"""
    articles: list[dict[str, str]] = []
    if SCRATCH_JSON.exists():
        try:
            data = json.loads(SCRATCH_JSON.read_text(encoding="utf-8"))
            for item in data:
                u = clean_mysteel_url(item["url"])
                articles.append(
                    {
                        "product_name": "钛白粉",
                        "symbol": "TIO2",
                        "report_date": item["report_date"],
                        "source_url": u,
                        "title": item.get("title", "钛白粉市场动态"),
                    }
                )
            logger.info("从历史缓存清单成功加载 %d 篇历史钛白粉文章", len(articles))
        except Exception as exc:
            logger.warning("加载历史缓存清单失败: %s", exc)
    return articles


def sync_to_sources_csv(items: list[dict[str, str]], csv_path: Path = CSV_PATH) -> int:
    """增量幂等合并写入 chemicals_weekly_sources.csv。"""
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

    logger.info(
        "已向 %s 增量写入 %d 条 TiO2 新周报配置，总配置数: %d", csv_path, added_count, len(rows)
    )
    return added_count


def main():
    logger.info("=== 开始发现与同步钛白粉 (TiO2) 2.5 年高频周报链接 ===")
    breed_items = scan_taibaifen_breed_page()
    hist_items = load_historical_articles()

    # 去重合并
    all_items: dict[str, dict[str, str]] = {}
    for item in hist_items + breed_items:
        u = item["source_url"]
        if u not in all_items:
            all_items[u] = item

    added = sync_to_sources_csv(list(all_items.values()))
    logger.info("=== TiO2 周报发现与配置同步完成！本次新增: %d ===", added)


if __name__ == "__main__":
    main()
