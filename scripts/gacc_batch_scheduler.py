"""GACC 海关历史数据半年度回填计划调度器。

读取 .agents/skills/customs-gacc-automation/plans/backfill_plan_2018_2026.yaml，
支持状态巡检、下一批次自动调度与指定批次按计划执行。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import polars as pl
import yaml

# 确保项目根目录在 sys.path 中
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.cdp.gacc_cdp_automation import run_automation  # noqa: E402

logger = logging.getLogger("gacc_scheduler")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

DEFAULT_PLAN_FILE = Path(
    ".agents/skills/customs-gacc-automation/plans/backfill_plan_2018_2026.yaml"
)
DEFAULT_PARQUET_FILE = Path("data/curated/industry/customs_trade_gacc.parquet")


def load_plan(plan_path: Path = DEFAULT_PLAN_FILE) -> dict[str, Any]:
    """加载 YAML 排期计划文件。"""
    if not plan_path.exists():
        raise FileNotFoundError(f"排期计划文件不存在: {plan_path}")
    with open(plan_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return dict(data) if isinstance(data, dict) else {}


def save_plan(plan: dict[str, Any], plan_path: Path = DEFAULT_PLAN_FILE) -> None:
    """持久化更新排期计划文件。"""
    with open(plan_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(plan, f, allow_unicode=True, sort_keys=False)


def inspect_curated_status(
    parquet_path: Path = DEFAULT_PARQUET_FILE,
) -> dict[str, int]:
    """统计当前 Curated 黄金表中各年月的记录行数。"""
    if not parquet_path.exists():
        return {}
    try:
        df = pl.read_parquet(parquet_path)
        if "report_month" not in df.columns:
            return {}
        agg = df.group_by("report_month").len()
        return {row["report_month"]: int(row["len"]) for row in agg.iter_rows(named=True)}
    except Exception as exc:
        logger.debug("读取黄金表月份统计失败: %s", exc)
        return {}


def show_plan_status(
    plan_path: Path = DEFAULT_PLAN_FILE,
    parquet_path: Path = DEFAULT_PARQUET_FILE,
) -> None:
    """在终端打印排期进度与入库状态巡检表。"""
    plan = load_plan(plan_path)
    curated_counts = inspect_curated_status(parquet_path)
    batches = plan.get("batches", [])

    print("\n" + "=" * 80)
    print("      GACC 海关历史数据半年度批量回填计划 (2018 - 2026) 状态巡检表")
    print("=" * 80)
    header = f"{'批次ID':<8} {'年份':<6} {'半年度':<6} {'起始月':<8} {'结束月':<8} {'计划状态':<8} {'黄金表已入库行数':<16} {'说明'}"
    print(header)
    print("-" * 80)

    total_curated_rows = 0
    completed_batches = 0

    for b in batches:
        bid = b.get("id", "")
        year = b.get("year", "")
        half = b.get("half", "")
        s_m = f"{b.get('start_month', 1):02d}"
        e_m = f"{b.get('end_month', 6):02d}"
        status = b.get("status", "pending")
        desc = b.get("description", "")

        # 统计该半年在黄金表中的行数
        start_m_int = int(b.get("start_month", 1))
        end_m_int = int(b.get("end_month", 6))
        batch_rows = sum(
            curated_counts.get(f"{year}-{m:02d}", 0) for m in range(start_m_int, end_m_int + 1)
        )
        total_curated_rows += batch_rows

        # 计划状态
        if status == "completed":
            status_display = "已完成"
            completed_batches += 1
        else:
            status_display = "待回填"

        row_str = f"{batch_rows:,} 行" if batch_rows > 0 else "无数据"
        print(
            f"{bid:<8} {year:<6} {half:<6} {s_m:<8} {e_m:<8} {status_display:<8} {row_str:<16} {desc}"
        )

    print("=" * 80)
    print(
        f"计划进度: 共 {len(batches)} 个半年度批次 | 已全量回填: {completed_batches} 个 | 待回填补齐: {len(batches) - completed_batches} 个"
    )
    print(f"黄金事实表总行数 (2018-2026): {total_curated_rows:,} 行")
    print("=" * 80 + "\n")


def run_batch(
    batch_id: str,
    plan_path: Path = DEFAULT_PLAN_FILE,
    auto_import: bool = True,
) -> int:
    """执行指定的某一个半年度批次。"""
    plan = load_plan(plan_path)
    target_batch = None
    for b in plan.get("batches", []):
        if b.get("id", "").upper() == batch_id.upper():
            target_batch = b
            break

    if not target_batch:
        logger.error("未找到指定的批次 ID: %s", batch_id)
        return 1

    year = int(target_batch["year"])
    start_month = int(target_batch.get("start_month", 1))
    end_month = int(target_batch.get("end_month", 6))

    logger.info(
        "准备按计划执行批次 [%s]: %d 年 %02d 至 %02d 月...", batch_id, year, start_month, end_month
    )
    code = run_automation(
        year=year,
        start_month=start_month,
        end_month=end_month,
        auto_import=auto_import,
    )

    if code == 0:
        logger.info("批次 [%s] 执行成功！正在更新计划状态为 completed...", batch_id)
        target_batch["status"] = "completed"
        save_plan(plan, plan_path)
    return code


def run_next_pending_batch(
    plan_path: Path = DEFAULT_PLAN_FILE,
    auto_import: bool = True,
) -> int:
    """自动找到下一个待采集的批次并启动执行。"""
    plan = load_plan(plan_path)
    batches = plan.get("batches", [])
    next_batch = None
    for b in batches:
        if b.get("status") == "pending":
            next_batch = b
            break

    if not next_batch:
        logger.info("全部 %d 个半年度批次均已完成回填，无需继续执行！", len(batches))
        return 0

    bid = next_batch.get("id", "")
    logger.info("自动调度下一个待回填批次: [%s]", bid)
    return run_batch(bid, plan_path=plan_path, auto_import=auto_import)


def main() -> int:
    """命令行主入口。"""
    parser = argparse.ArgumentParser(description="GACC 历史数据半年度批量回填调度器")
    parser.add_argument("--status", action="store_true", help="查看所有半年度批次的排期与入库状态")
    parser.add_argument("--next", action="store_true", help="自动执行下一个处于 pending 状态的批次")
    parser.add_argument(
        "--batch", type=str, default="", help="指定执行某一个半年度批次 (如 2024H1)"
    )
    parser.add_argument(
        "--plan-file", type=Path, default=DEFAULT_PLAN_FILE, help="自定义排期计划文件路径"
    )
    parser.add_argument("--no-import", action="store_true", help="仅下载，不自动导入 Curated")

    args = parser.parse_args()

    if args.status or (not args.next and not args.batch):
        show_plan_status(args.plan_file)
        return 0

    if args.batch:
        return run_batch(args.batch, plan_path=args.plan_file, auto_import=not args.no_import)

    if args.next:
        return run_next_pending_batch(plan_path=args.plan_file, auto_import=not args.no_import)

    return 0


if __name__ == "__main__":
    sys.exit(main())
