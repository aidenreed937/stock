"""纯碱重大产能事件巨潮资讯自动同步与对齐工具。

用法:
    # 1. 试运行模式 (仅预览识别出的公告与待更新项，不改写 YAML):
    uv run python scripts/sync_soda_ash_capacity_cninfo.py --dry-run

    # 2. 正式应用模式 (回写 config/industry/chemicals/soda_ash/capacity_projects.yaml 并重新生成研报):
    uv run python scripts/sync_soda_ash_capacity_cninfo.py --apply
"""

from __future__ import annotations

import argparse
import logging
import sys

from stock_data.fetcher.industry.chemicals.capacity_updater import (
    DEFAULT_CONFIG_PATH,
    CapacityProjectUpdater,
)
from stock_data.fetcher.industry.chemicals.collectors.cninfo_announcement import (
    DEFAULT_KEYWORDS,
    CninfoAnnouncementCollector,
)
from stock_data.fetcher.industry.chemicals.parsers.capacity_announcement import (
    CapacityAnnouncementParser,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sync_soda_ash_capacity")


def main() -> int:
    parser = argparse.ArgumentParser(description="纯碱重大产能事件巨潮资讯自动同步工具")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="正式应用变更并回写 YAML (默认仅 dry-run 预览)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="预览模式，不修改任何文件",
    )
    parser.add_argument(
        "--start-date",
        default="2023-01-01",
        help="公告起始检索日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="公告截止检索日期 (YYYY-MM-DD，默认今天)",
    )
    parser.add_argument(
        "--keywords",
        default=DEFAULT_KEYWORDS,
        help="公告搜索关键词",
    )
    parser.add_argument(
        "--config-path",
        default=str(DEFAULT_CONFIG_PATH),
        help="产能配置文件路径",
    )

    args = parser.parse_args()
    is_dry_run = not args.apply

    logger.info(
        "=== 开始纯碱产能事件巨潮资讯同步 (模式: %s) ===",
        "DRY-RUN 预览" if is_dry_run else "正式写入",
    )

    collector = CninfoAnnouncementCollector()
    announcements = collector.fetch_all_soda_ash_announcements(
        keywords=args.keywords,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    logger.info("共抓取到 %d 条巨潮资讯原始公告", len(announcements))

    parser_tool = CapacityAnnouncementParser()
    parsed_events = []
    for item in announcements:
        evt = parser_tool.parse_announcement(item)
        if evt:
            parsed_events.append(evt)

    logger.info("成功结构化识别出 %d 笔产能相关重大事件", len(parsed_events))
    for i, e in enumerate(parsed_events[:10], 1):
        logger.info(
            "  [%d] %s: %s (%s) - 状态=%s, 投料=%s, 达产=%s",
            i,
            e["company"],
            e["plant_name"],
            e["project_id"],
            e["status"],
            e.get("actual_start"),
            e.get("full_capacity_date"),
        )

    updater = CapacityProjectUpdater(config_path=args.config_path)
    _, change_log = updater.merge_events(parsed_events, dry_run=is_dry_run)

    print("\n" + "=" * 60)
    print(f"产能变更对账结果 (共 {len(change_log)} 处变动):")
    print("=" * 60)
    if change_log:
        for log_item in change_log:
            print(f"  • {log_item}")
    else:
        print("  • 暂无新变动 (现有种子库与抓取公告已对齐)")
    print("=" * 60 + "\n")

    if not is_dry_run and change_log:
        logger.info("正在重新触发纯碱全景管线以更新研报...")
        try:
            from stock_analytics.pipelines.soda_ash import run_soda_ash_pipeline

            run_soda_ash_pipeline()
            logger.info("纯碱全景基本面研报已同步刷新完成！")
        except Exception as exc:
            logger.error("刷新研报失败: %s", exc)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
