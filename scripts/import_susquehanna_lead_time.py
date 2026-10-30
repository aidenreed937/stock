"""外部芯片交付周期 (Chip Lead Time) 历史数据文件导入工具。

用途:
从用户提供的外部 CSV 数据文件 (如 Susquehanna 官方公报导出数据)
批量导入为 2-Tier ETL RAW 快照 (data/raw/industry/lead_time/) 并触发 Curated 黄金表重放。

用法:
    uv run python scripts/import_susquehanna_lead_time.py --csv path/to/lead_time.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    save_curated_fact,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.semiconductor.collectors.lead_time import (
    ChipLeadTimeCollector,
)
from stock_data.fetcher.industry.semiconductor.transforms import records_to_chip_lead_time_frame

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def import_csv_to_raw(
    csv_path: Path | str,
    raw_dir: Path | str = "data/raw/industry",
) -> int:
    """从用户 CSV 文件读取记录并逐月写入 RAW 快照。"""
    raw_path = Path(raw_dir)
    records: list[dict[str, Any]] = []

    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"未找到指定的 CSV 文件: {csv_path}")

    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            m = row.get("month") or row.get("report_month")
            if not m:
                continue
            release_date_raw = (row.get("release_date") or "").strip()
            if not release_date_raw:
                raise ValueError(f"交期 CSV 行 {m.strip()} 缺少真实 release_date，不能写入 RAW")
            try:
                release_date = date.fromisoformat(release_date_raw)
            except ValueError as exc:
                raise ValueError(
                    f"交期 CSV 行 {m.strip()} 的 release_date 无效: {release_date_raw}"
                ) from exc
            records.append(
                {
                    "month": m.strip(),
                    "avg": float(row.get("avg", 0) or row.get("avg_lead_time_weeks", 0)),
                    "mcu": float(row.get("mcu", 0) or row.get("mcu_lead_time_weeks", 0)),
                    "analog": float(row.get("analog", 0) or row.get("analog_lead_time_weeks", 0)),
                    "discrete": float(
                        row.get("discrete", 0) or row.get("discrete_lead_time_weeks", 0)
                    ),
                    "compute": float(
                        row.get("compute", 0) or row.get("compute_lead_time_weeks", 0)
                    ),
                    "source": row.get("source", "External Bulletin"),
                    "release_date": release_date,
                }
            )

    target_base = raw_path / "semiconductor" if (raw_path / "semiconductor").exists() else raw_path
    count = 0
    for r in records:
        m_key = r["month"]
        yr, mo = parse_month_string(m_key)
        trade_d = get_month_end_date(yr, mo)
        avg_val = float(r["avg"])

        cat_averages = {
            "mcu": float(r["mcu"]),
            "analog": float(r["analog"]),
            "discrete": float(r["discrete"]),
            "compute": float(r["compute"]),
        }

        content = {
            "report_month": m_key,
            "trade_date": trade_d.isoformat(),
            "avg_lead_time_weeks": avg_val,
            "category_averages": cat_averages,
            "source": r.get("source", "External Bulletin"),
            "release_date": r["release_date"].isoformat(),
            "collected_at": now_utc_iso(),
        }

        save_raw_snapshot(
            source_name="lead_time",
            snapshot_filename=f"chip_lead_time_{m_key}.json",
            content=content,
            base_dir=target_base,
        )
        count += 1

    logger.info("成功从 %s 写入 %d 个 RAW 快照至 %s/lead_time/", csv_path, count, target_base)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从外部 CSV 文件导入芯片交期数据至 RAW 与 Curated 黄金表"
    )
    parser.add_argument("--csv", type=str, required=True, help="外部 CSV 数据文件路径 (必填)")
    parser.add_argument("--raw-dir", type=str, default="data/raw/industry", help="RAW 存储目录")
    parser.add_argument(
        "--curated-dir", type=str, default="data/curated/industry", help="Curated 存储目录"
    )
    args = parser.parse_args()

    # 1. 写入 RAW 快照
    import_csv_to_raw(args.csv, raw_dir=args.raw_dir)

    # 2. 触发重放，标准化落盘 Curated 黄金事实表
    collector = ChipLeadTimeCollector(raw_dir=args.raw_dir)
    records = collector.load_from_raw_snapshots()
    logger.info("从 RAW 加载并标准化 %d 条记录...", len(records))

    df = records_to_chip_lead_time_frame(records)
    curated_file = Path(args.curated_dir) / "chip_lead_time.parquet"
    saved_rows = save_curated_fact(df, curated_file, primary_keys=["report_month"])

    logger.info("✅ 外部历史数据导入与黄金表重放完成！共落盘 %d 行至 %s", saved_rows, curated_file)


if __name__ == "__main__":
    main()
