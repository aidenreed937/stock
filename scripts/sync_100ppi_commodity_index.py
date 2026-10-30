#!/usr/bin/env python3
"""生意社大宗商品定基指数 (Commodity Index) 每日增量同步脚本。

用法:
    uv run python scripts/sync_100ppi_commodity_index.py
    uv run python scripts/sync_100ppi_commodity_index.py --symbols PX,POY,MDI_poly,TiO2 --force
    uv run python scripts/sync_100ppi_commodity_index.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 确保项目根路径在 sys.path 中
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from stock_data.fetcher.industry.chemicals.collectors.commodity_index import (  # noqa: E402
    DEFAULT_COMMODITY_CONFIG,
    CommodityIndexCollector,
)
from stock_data.fetcher.industry.chemicals.transforms.commodity_index import (  # noqa: E402
    materialize_commodity_index_to_curated,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_100ppi_ci")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生意社商品定基指数 (cindex/ptrade) 每日增量同步与黄金表沉淀"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="待采集的商品代码列表 (逗号分隔，例如 'PX,POY,MDI_poly,TiO2')，默认采集全部预设品种",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制网络重新下载 RAW 网页快照，忽略本地缓存",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅抓取解析并展示统计，不写入 Curated 事实表",
    )
    parser.add_argument(
        "--raw-dir",
        type=str,
        default="data/raw/industry/chemicals",
        help="RAW 网页快照缓存根目录",
    )
    parser.add_argument(
        "--curated-dir",
        type=str,
        default="data/curated/industry",
        help="Curated 黄金事实表输出目录",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # 确定目标品类池
    if args.symbols:
        req_syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
        pool = {s: DEFAULT_COMMODITY_CONFIG[s] for s in req_syms if s in DEFAULT_COMMODITY_CONFIG}
        missing = [s for s in req_syms if s not in DEFAULT_COMMODITY_CONFIG]
        if missing:
            logger.warning(f"以下 symbol 未在预设配置中找到: {missing}")
    else:
        pool = DEFAULT_COMMODITY_CONFIG

    if not pool:
        logger.error("未指定有效的品类池，退出")
        return 1

    logger.info(f"开始同步生意社商品定基指数，目标品类数: {len(pool)}: {list(pool.keys())}")

    collector = CommodityIndexCollector(raw_dir=args.raw_dir)
    all_records = collector.collect_all(commodities=pool, force=args.force)

    if not all_records:
        logger.warning("未解析到任何商品定基指数记录")
        return 0

    logger.info(f"所有品类解析完成，累计提取 {len(all_records)} 条日频点位记录")

    if args.dry_run:
        logger.info("[Dry Run] 跳过 Curated 事实表写入")
        return 0

    net_added, total = materialize_commodity_index_to_curated(
        records=all_records,
        curated_dir=args.curated_dir,
    )
    logger.info(
        f"Curated chemical_commodity_index.parquet 写入完毕: 净增/更新 {net_added} 行, 总记录数 {total} 行"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
