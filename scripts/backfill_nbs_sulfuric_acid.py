"""回填国家统计局 (NBS) 旬度《流通领域重要生产资料市场价格变动情况》工业浓硫酸 (98%) 价格时序。"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.chemicals.parsers.nbs_production_materials import (
    extract_nbs_commodity_prices,
    save_nbs_prices_to_survey_csv,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("backfill_nbs_sulfuric_acid")

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_SURVEY_CSV = (
    REPO_ROOT
    / "data"
    / "raw"
    / "industry"
    / "chemicals"
    / "operating_rates"
    / "expert_prices_survey.csv"
)

NBS_BASE_URL = "https://www.stats.gov.cn/sj/zxfb/"


def discover_report_urls(
    max_pages: int = 30,
    session: requests.Session | None = None,
) -> list[tuple[str, str]]:
    """在统计局数据发布列表中检索《流通领域重要生产资料市场价格变动情况》报告。"""
    s = session or requests.Session()
    reports: list[tuple[str, str]] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    # 优先通过官方 RSS Feed 发现公报（覆盖近 2.5 年，单次请求极速稳定无 JS 挑战）
    rss_url = f"{NBS_BASE_URL}rss.xml"
    try:
        logger.info("尝试从国家统计局 RSS 源检索最新公报: %s", rss_url)
        rss_resp = s.get(rss_url, impersonate="chrome120", headers=headers, timeout=12)
        if rss_resp.status_code == 200 and b"<rss" in rss_resp.content:
            import xml.etree.ElementTree as ET  # noqa: S314

            root = ET.fromstring(rss_resp.content)  # noqa: S314
            for item in root.findall(".//item"):
                title_node = item.find("title")
                link_node = item.find("link")
                raw_t = (
                    title_node.text.strip() if title_node is not None and title_node.text else ""
                )
                raw_u = link_node.text.strip() if link_node is not None and link_node.text else ""
                if "流通领域重要生产资料市场价格变动情况" in raw_t and raw_u:
                    reports.append((raw_t, raw_u))

            logger.info("从 RSS 源成功发现 %d 篇流通领域公报", len(reports))
            if len(reports) >= 10:
                # 去重后返回
                seen_u: set[str] = set()
                res: list[tuple[str, str]] = []
                for t, u in reports:
                    if u not in seen_u:
                        seen_u.add(u)
                        res.append((t, u))
                return res
    except Exception as exc:
        logger.warning("通过 RSS 检索失败，回退至网页列表翻页: %s", exc)

    logger.info("开始扫描国家统计局数据发布列表 (0 ~ %d 页)...", max_pages - 1)
    for page in range(max_pages):
        page_url = f"{NBS_BASE_URL}index.html" if page == 0 else f"{NBS_BASE_URL}index_{page}.html"
        try:
            resp = s.get(page_url, impersonate="chrome120", headers=headers, timeout=12)
            if resp.status_code != 200:
                logger.warning("第 %d 页返回状态码 %d，提前终止翻页", page, resp.status_code)
                break

            # 匹配包含流通领域重要生产资料的链接
            matches = re.findall(
                r'<a[^>]+href=[\'"]([^\'"]+)[\'"][^>]*title=[\'"]([^\'"]*流通领域重要生产资料市场价格变动情况[^\'"]*)[\'"]',
                resp.text,
            )
            # 部分页面结构 title 在前 href 在后
            if not matches:
                matches = re.findall(
                    r'<a[^>]+title=[\'"]([^\'"]*流通领域重要生产资料市场价格变动情况[^\'"]*)[\'"][^>]*href=[\'"]([^\'"]+)[\'"]',
                    resp.text,
                )
                matches = [(m[1], m[0]) for m in matches]

            for raw_href, raw_title in matches:
                clean_title = raw_title.strip()
                clean_href = raw_href.strip()
                if not clean_href.startswith("http"):
                    if clean_href.startswith("./"):
                        clean_href = NBS_BASE_URL + clean_href[2:]
                    elif clean_href.startswith("/"):
                        clean_href = "https://www.stats.gov.cn" + clean_href
                    else:
                        clean_href = NBS_BASE_URL + clean_href
                reports.append((clean_title, clean_href))

        except Exception as exc:
            logger.error("抓取第 %d 页失败: %s", page, exc)
            break

    # 去重
    seen: set[str] = set()
    unique_reports: list[tuple[str, str]] = []
    for t, u in reports:
        if u not in seen:
            seen.add(u)
            unique_reports.append((t, u))

    logger.info("共发现 %d 篇流通领域重要生产资料公报", len(unique_reports))
    return unique_reports


def backfill_sulfuric_acid_quotes(
    max_pages: int = 30,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """批量抓取并提取国家统计局 98% 工业浓硫酸旬度报价。"""
    s = requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    report_list = discover_report_urls(max_pages=max_pages, session=s)
    all_records: list[dict[str, Any]] = []

    for idx, (title, url) in enumerate(report_list, 1):
        try:
            resp = s.get(url, impersonate="chrome120", headers=headers, timeout=12)
            if resp.status_code != 200:
                logger.warning(
                    "[%d/%d] 抓取失败 HTTP %d: %s", idx, len(report_list), resp.status_code, url
                )
                continue

            records = extract_nbs_commodity_prices(
                resp.text, source_url=url, target_symbols=["H2SO4"]
            )
            if records:
                for rec in records:
                    all_records.append(rec)
                    logger.info(
                        "[%d/%d] 提取成功: %s -> %s = %.1f %s (发布: %s)",
                        idx,
                        len(report_list),
                        rec["trade_date"],
                        rec["product_name"],
                        rec["spot_price_cny"],
                        rec["unit"],
                        rec["release_date"],
                    )
            else:
                logger.debug(
                    "[%d/%d] 未在报告中匹配到 98%% 硫酸价格: %s", idx, len(report_list), title
                )

            time.sleep(0.2)
        except Exception as exc:
            logger.error("[%d/%d] 处理报告异常 %s: %s", idx, len(report_list), url, exc)

    logger.info("数据抓取完成，共提取到 %d 条 98%% 浓硫酸旬度报价", len(all_records))

    if not dry_run and all_records:
        saved_path = save_nbs_prices_to_survey_csv(all_records, RAW_SURVEY_CSV)
        logger.info("已将 %d 条记录更新写入: %s", len(all_records), saved_path)

    return all_records


def main() -> None:
    parser = argparse.ArgumentParser(description="回填国家统计局旬度 98% 工业硫酸价格")
    parser.add_argument(
        "--max-pages", type=int, default=30, help="扫描统计局发布列表最大页数 (默认 30)"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅抓取不落地 CSV")
    parser.add_argument("--no-rebuild", action="store_true", help="不重新构建连续价差 Parquet")
    args = parser.parse_args()

    records = backfill_sulfuric_acid_quotes(max_pages=args.max_pages, dry_run=args.dry_run)

    if not args.dry_run and not args.no_rebuild and records:
        logger.info("触发重新构建钛白粉动态价差...")
        import subprocess

        cmd = [sys.executable, str(REPO_ROOT / "scripts" / "build_tio2_continuous_spreads.py")]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        print(res.stdout)
        if res.returncode != 0:
            logger.error("构建价差失败:\n%s", res.stderr)
            sys.exit(res.returncode)


if __name__ == "__main__":
    main()
