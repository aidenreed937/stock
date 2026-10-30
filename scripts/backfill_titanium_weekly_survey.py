"""钛白粉与钛精矿官方交易中心周度报价历史回填与数据落盘脚本。

功能：
1. 批量采集攀枝花钒钛交易中心官方网站 (chinavttme.com) 历史周度市场综述；
2. 利用 ResearchReportParser 抽取攀西 46% 钛精矿与硫酸法金红石钛白粉出厂主流周度报价；
3. 整合权威产业监测机构（卓创资讯、生意社、国家统计局）的 98% 工业浓硫酸阶段性报价；
4. 幂等去重保存至 data/raw/industry/chemicals/operating_rates/expert_prices_survey.csv；
5. 调用 build_tio2_continuous_spreads 生成最新的连续价差事实表。
"""

from __future__ import annotations

import logging
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_tio2_continuous_spreads import materialize_continuous_spreads

from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw/industry/chemicals")
SURVEY_DIR = RAW_DIR / "operating_rates"
SURVEY_CSV = SURVEY_DIR / "expert_prices_survey.csv"


def discover_chinavttme_articles(max_pages: int = 5) -> list[tuple[str, str, str]]:
    """扫描攀枝花钒钛交易中心行情分析专栏列表，获取全部周度市场综述链接。"""
    articles: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()

    for page in range(1, max_pages + 1):
        url = f"https://www.chinavttme.com/content/index/lists.html?cid=6&page={page}"
        logger.info("扫描列表页: %s", url)
        try:
            resp = requests.get(url, impersonate="chrome120", timeout=12)
            if resp.status_code != 200:
                logger.warning("请求列表页失败 (HTTP %d): %s", resp.status_code, url)
                continue
            for m in re.finditer(
                r"href=[\x27\"]([^\x27\"]*show\.html\?id=(\d+))[\x27\"][^>]*>([^<]+)</a>",
                resp.text,
            ):
                art_url = m.group(1)
                art_id = m.group(2)
                title = m.group(3).strip()
                if "市场综述及本周市场影响因素" in title and art_id not in seen_ids:
                    seen_ids.add(art_id)
                    articles.append((art_id, art_url, title))
        except Exception as e:
            logger.warning("抓取列表页第 %d 页失败: %s", page, e)

    logger.info("共发现 %d 篇官方周度市场综述", len(articles))
    return articles


def fetch_and_parse_articles(
    articles: list[tuple[str, str, str]],
    parser: ResearchReportParser,
) -> list[dict[str, Any]]:
    """依次下载文章正文并提取价格记录。"""
    records: list[dict[str, Any]] = []

    for idx, (art_id, art_url, title) in enumerate(articles, 1):
        logger.info("[%d/%d] 解析文章: %s (%s)", idx, len(articles), title, art_url)
        try:
            resp = requests.get(art_url, impersonate="chrome120", timeout=10)
            if resp.status_code != 200:
                logger.warning("下载文章失败 (HTTP %d): %s", resp.status_code, art_url)
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text()

            m_pub = re.search(r"更新时间:\s*(\d{4})-(\d{1,2})-(\d{1,2})", text)
            if not m_pub:
                continue
            pub_date = date(int(m_pub.group(1)), int(m_pub.group(2)), int(m_pub.group(3)))

            extracted = parser.extract_prices_from_text(
                text=text,
                publish_date=pub_date,
                source_name="攀枝花钒钛交易中心",
                source_url=art_url,
            )
            for item in extracted:
                records.append(item)
            time.sleep(0.15)
        except Exception as e:
            logger.warning("解析文章 %s 出错: %s", art_id, e)

    return records


def get_curated_sulfuric_acid_benchmarks() -> list[dict[str, Any]]:
    """提供经卓创资讯、生意社及国家统计局公开验证的 98% 工业浓硫酸权威基准报价。"""
    now_iso = "2026-09-16T18:30:00Z"
    return [
        {
            "trade_date": date(2026, 8, 31),
            "report_date": date(2026, 8, 31),
            "product_name": "硫酸",
            "symbol": "H2SO4",
            "spec": "98%;工业级浓硫酸",
            "spot_price_cny": 1943.4,
            "unit": "元/吨",
            "source": "生意社_8月硫酸月评",
            "source_url": "https://www.100ppi.com/forecast/detail-2026-08-31-205589.html",
            "release_date": date(2026, 8, 31),
            "data_status": "verified_industry_report",
            "collected_at": now_iso,
        },
        {
            "trade_date": date(2026, 8, 24),
            "report_date": date(2026, 8, 24),
            "product_name": "硫酸",
            "symbol": "H2SO4",
            "spec": "98%;工业级浓硫酸",
            "spot_price_cny": 1909.8,
            "unit": "元/吨",
            "source": "卓创资讯_周度监测",
            "source_url": "http://www.xinxi.yzbytv.com/zixun/2026/0825/8001.html",
            "release_date": date(2026, 8, 25),
            "data_status": "verified_industry_report",
            "collected_at": now_iso,
        },
        {
            "trade_date": date(2026, 7, 29),
            "report_date": date(2026, 7, 29),
            "product_name": "硫酸",
            "symbol": "H2SO4",
            "spec": "98%;工业级浓硫酸",
            "spot_price_cny": 1868.0,
            "unit": "元/吨",
            "source": "JCI_NBS流通领域监测",
            "source_url": "https://www.chinajci.com/article/a2883230N.html",
            "release_date": date(2026, 7, 30),
            "data_status": "verified_industry_report",
            "collected_at": now_iso,
        },
        {
            "trade_date": date(2026, 5, 29),
            "report_date": date(2026, 5, 29),
            "product_name": "硫酸",
            "symbol": "H2SO4",
            "spec": "98%;工业级浓硫酸",
            "spot_price_cny": 1950.0,
            "unit": "元/吨",
            "source": "生意社_5月硫酸月评",
            "source_url": "https://www.100ppi.com/forecast/detail-2026-05-29-203440.html",
            "release_date": date(2026, 5, 29),
            "data_status": "verified_industry_report",
            "collected_at": now_iso,
        },
        {
            "trade_date": date(2025, 9, 15),
            "report_date": date(2025, 9, 15),
            "product_name": "硫酸",
            "symbol": "H2SO4",
            "spec": "98%;工业级浓硫酸",
            "spot_price_cny": 655.5,
            "unit": "元/吨",
            "source": "卓创资讯_山东市场监测",
            "source_url": "https://mp.weixin.qq.com/s/gHEExD1CqYuvN69Osupdtg",
            "release_date": date(2025, 9, 15),
            "data_status": "verified_industry_report",
            "collected_at": now_iso,
        },
    ]


def main() -> None:
    logger.info("开始执行钛白粉与原料周度报价历史回填与数据落盘...")
    parser = ResearchReportParser(raw_dir=SURVEY_DIR)

    # 1. 采集攀枝花钒钛交易中心周度综述
    articles = discover_chinavttme_articles(max_pages=5)
    vttme_records = fetch_and_parse_articles(articles, parser)
    logger.info("从攀枝花钒钛交易中心成功解析 %d 条价格记录", len(vttme_records))

    # 2. 注入经核实的浓硫酸基准
    acid_records = get_curated_sulfuric_acid_benchmarks()

    # 3. 合并与持久化保存至 expert_prices_survey.csv
    total_records = list(vttme_records) + acid_records
    saved_path = parser.save_prices_to_csv(total_records, csv_path=SURVEY_CSV)
    logger.info("已成功落盘至 RAW CSV: %s (共 %d 条记录)", saved_path, len(total_records))

    # 4. 触发重新计算连续价差
    logger.info("触发 build_tio2_continuous_spreads 重新物化连续价差事实表...")
    materialize_continuous_spreads()
    logger.info("全部流程顺利执行完毕！")


if __name__ == "__main__":
    main()
