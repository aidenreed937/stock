"""垂直产业景气指标 2-Tier ETL 统一同步管道。"""

import logging
from pathlib import Path

from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.nev import NevCollector
from stock_data.fetcher.industry.nev_sales import records_to_nev_frame
from stock_data.fetcher.industry.semiconductor import SemiconductorCollector
from stock_data.fetcher.industry.semiconductor_sales import records_to_semiconductor_frame
from stock_data.fetcher.industry.solar import SolarCollector
from stock_data.fetcher.industry.solar_capacity import records_to_solar_frame

logger = logging.getLogger(__name__)


def sync_all_industry_metrics(
    raw_dir: Path | str = "data/raw/industry",
    curated_dir: Path | str = "data/curated/industry",
) -> dict[str, int]:
    """统一同步并落盘三大垂直产业黄金事实表。

    调度:
    1. SemiconductorCollector -> semiconductor_sales.parquet
    2. NevCollector -> nev_monthly_sales.parquet
    3. SolarCollector -> solar_capacity.parquet
    """
    raw_path = Path(raw_dir)
    curated_path = Path(curated_dir)
    curated_path.mkdir(parents=True, exist_ok=True)
    results: dict[str, int] = {}

    # 1. 全球半导体销售额
    semi_collector = SemiconductorCollector(raw_dir=raw_path)
    semi_records = semi_collector.collect()
    if semi_records:
        df_semi = records_to_semiconductor_frame(semi_records)
        count = save_curated_fact(df_semi, curated_path / "semiconductor_sales.parquet")
        results["semiconductor_sales"] = count

    # 2. 新能源汽车产销与渗透率
    nev_collector = NevCollector(raw_dir=raw_path)
    nev_records = nev_collector.collect()
    if nev_records:
        df_nev = records_to_nev_frame(nev_records)
        count = save_curated_fact(df_nev, curated_path / "nev_monthly_sales.parquet")
        results["nev_monthly_sales"] = count

    # 3. 全国光伏装机容量
    solar_collector = SolarCollector(raw_dir=raw_path)
    solar_records = solar_collector.collect()
    if solar_records:
        df_solar = records_to_solar_frame(solar_records)
        count = save_curated_fact(df_solar, curated_path / "solar_capacity.parquet")
        results["solar_capacity"] = count

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="垂直产业景气指标 (半导体/新能源车/光伏) 采集与 2-Tier ETL 落盘工具"
    )
    parser.add_argument("--raw-dir", default="data/raw/industry", help="RAW 原始快照目录")
    parser.add_argument(
        "--curated-dir", default="data/curated/industry", help="Curated 黄金事实表输出目录"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s - %(message)s"
    )
    print(f"🚀 开始采集垂直产业景气指标 (RAW: {args.raw_dir} -> Curated: {args.curated_dir})...")
    res = sync_all_industry_metrics(raw_dir=args.raw_dir, curated_dir=args.curated_dir)
    print("\n✅ 采集与落盘执行完成:")
    for metric_name, row_count in res.items():
        print(f"  - {metric_name}: {row_count} 行有效数据")
