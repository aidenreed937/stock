"""重放 data/raw/industry 全部 RAW 数据到 Curated 黄金表 (离线, 不触发网络采集)。

背景: 各产业端点按自身来源使用在线采集或人工导入；GACC 由人工从官网导出 CSV，
先通过 `gacc-import` 生成带 manifest 的规范 RAW 快照，再由本脚本直接从现有
RAW 快照 (CSV / WSTS Excel / SEC EDGAR JSON / UN Comtrade JSON / GACC manifest) 重建/合并
产业黄金事实表, 供手工回放或审计对账使用。

重放护栏: 落盘前会把「即将写入的新帧」与「现有 Curated」逐列对比, 报告
**非空→空** 与 **值变化** 的列级行数。RAW 中无法复现的既成事实会在重放时被
静默抹掉, 该报告用于把这种改写暴露出来。
默认仅告警; 加 ``--strict-drift`` 则在出现改写时中止。
典型实例: `foundry_capacity_utilization` 的 TSMC 利用率历史基线曾被整体抹掉;
该基线现已落成受版本管理的 `config/industry/semiconductor/tsmc_utilization_baseline.yaml`
(加载与校验见 `semiconductor/baseline.py`), live 与重放同源, 护栏对该表已不再报「非空→空」。

用法:
    uv run python scripts/replay_industry_raw.py                # 全量重放
    uv run python scripts/replay_industry_raw.py --metric coal_market   # 单指标
    uv run python scripts/replay_industry_raw.py --dry-run      # 只预览不落盘
    uv run python scripts/replay_industry_raw.py --strict-drift # 改写既有事实即中止
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.agriculture.replay import build_agriculture_replay_plan
from stock_data.fetcher.industry.automotive.replay import build_automotive_replay_plan
from stock_data.fetcher.industry.chemicals.replay import build_chemicals_replay_plan
from stock_data.fetcher.industry.cloud.replay import build_cloud_replay_plan
from stock_data.fetcher.industry.coal.replay import build_coal_replay_plan
from stock_data.fetcher.industry.common import (
    save_curated_fact,
)
from stock_data.fetcher.industry.consumer.replay import build_consumer_replay_plan
from stock_data.fetcher.industry.customs.replay import build_customs_replay_plan
from stock_data.fetcher.industry.electronics.replay import build_electronics_replay_plan
from stock_data.fetcher.industry.machinery.replay import build_machinery_replay_plan
from stock_data.fetcher.industry.metals.replay import build_metals_replay_plan
from stock_data.fetcher.industry.pharma.replay import build_pharma_replay_plan
from stock_data.fetcher.industry.power.replay import (
    POWER_REPLAY_ORDER,
    build_power_replay_plan,
)
from stock_data.fetcher.industry.semiconductor.replay import (
    build_semiconductor_replay_plan,
)
from stock_data.fetcher.industry.shipping.replay import build_shipping_replay_plan

logger = logging.getLogger(__name__)

RAW_ROOT = Path("data/raw/industry")
CURATED_ROOT = Path("data/curated/industry")
# POWER_REPLAY_ORDER 由 power 包自持并在此沿用（见模块顶部导入）

# 逐行元数据, 每次重放都会刷新, 不参与改写判定
_DRIFT_META_COLUMNS = frozenset({"collected_at", "updated_at"})


class ReplayDriftError(RuntimeError):
    """重放将破坏性改写既有 Curated 事实（仅 ``--strict-drift`` 下抛出）。"""


def _regression_report(
    existing: pl.DataFrame,
    incoming: pl.DataFrame,
    primary_keys: list[str] | None,
) -> tuple[dict[str, int], dict[str, int]]:
    """对比现有 Curated 与待写入帧, 返回 ``(非空→空, 值变化)`` 的列级行数。

    ``save_curated_fact`` 使用 ``keep="last"``, 新值覆盖旧值, 故以新帧为准逐列比对
    交集主键上的行。仅统计「旧值非空」的情形, 新增行不会计入。
    """
    keys = [
        key for key in (primary_keys or []) if key in existing.columns and key in incoming.columns
    ]
    if not keys:
        for candidate in ("report_quarter", "report_month", "trade_date"):
            if candidate in existing.columns and candidate in incoming.columns:
                keys = [candidate]
                break
    if not keys:
        logger.debug("重放回归对比跳过: 未找到可用主键")
        return {}, {}

    common = [
        column
        for column in existing.columns
        if column in incoming.columns and column not in _DRIFT_META_COLUMNS and column not in keys
    ]
    if not common:
        return {}, {}

    for key in keys:
        existing_dtype = existing.schema[key]
        incoming_dtype = incoming.schema[key]
        if existing_dtype == pl.String and incoming_dtype == pl.Date:
            existing = existing.with_columns(pl.col(key).str.to_date(strict=False).alias(key))
        elif existing_dtype == pl.Date and incoming_dtype == pl.String:
            incoming = incoming.with_columns(pl.col(key).str.to_date(strict=False).alias(key))

    joined = existing.select(keys + common).join(
        incoming.select(keys + common), on=keys, how="inner", suffix="_new"
    )
    if joined.is_empty():
        return {}, {}

    to_null: dict[str, int] = {}
    changed: dict[str, int] = {}
    for column in common:
        old = joined[column]
        new = joined[f"{column}_new"]
        try:
            became_null = int((old.is_not_null() & new.is_null()).sum())
            value_changed = int((old.is_not_null() & new.is_not_null() & (old != new)).sum())
        except Exception as exc:  # noqa: BLE001 - 不可比类型直接跳过
            logger.debug("重放回归对比跳过列 [%s]: %s", column, exc)
            continue
        if became_null:
            to_null[column] = became_null
        if value_changed:
            changed[column] = value_changed
    return to_null, changed


def _format_drift(metric: str, to_null: dict[str, int], changed: dict[str, int]) -> str:
    lines = [f"[{metric}] 重放将改写既有 Curated 事实:"]
    if to_null:
        detail = ", ".join(f"{name}={count}" for name, count in sorted(to_null.items()))
        lines.append(f"  非空→空: {detail}")
    if changed:
        detail = ", ".join(f"{name}={count}" for name, count in sorted(changed.items()))
        lines.append(f"  值变化: {detail}")
    lines.append("  请确认这些列可由当前 RAW 复现; 上游带外补充的基线值会在重放时被抹掉。")
    return "\n".join(lines)


def _build_metric_plan() -> dict[str, dict[str, Any]]:
    """汇总各产业自持的离线重放计划（metric -> 执行计划）。

    每个产业包在自己的 ``<pkg>/replay.py`` 中提供 ``build_<pkg>_replay_plan()``，
    Curated/RAW 路径由该产业 registry 的 ``target_file`` / ``raw_subdir`` 推导，
    本函数只做合并，不再承载任何产业的 loader 或路径硬编码。
    """
    plan: dict[str, dict[str, Any]] = {}
    for build_plan in (
        build_semiconductor_replay_plan,
        build_agriculture_replay_plan,
        build_automotive_replay_plan,
        build_chemicals_replay_plan,
        build_cloud_replay_plan,
        build_coal_replay_plan,
        build_consumer_replay_plan,
        build_customs_replay_plan,
        build_electronics_replay_plan,
        build_machinery_replay_plan,
        build_metals_replay_plan,
        build_pharma_replay_plan,
        build_power_replay_plan,
        build_shipping_replay_plan,
    ):
        plan.update(build_plan())
    return plan


def replay_metric(
    metric: str,
    plan: dict[str, Any],
    raw_root: Path,
    curated_root: Path,
    dry_run: bool = False,
    strict_drift: bool = False,
) -> int:
    """重放单个指标: 读 RAW -> transform -> 合并落盘 Curated, 返回处理记录数。"""
    loader = plan["loader"]
    to_frame = plan["to_frame"]
    curated_file = curated_root / plan["curated"]

    records = (
        loader(raw_root, curated_root) if plan.get("loader_uses_curated") else loader(raw_root)
    )
    is_empty = records.is_empty() if isinstance(records, pl.DataFrame) else not bool(records)
    if is_empty:
        logger.info("[%s] RAW 无数据, 跳过", metric)
        return 0

    df = to_frame(records)
    rec_count = records.height if isinstance(records, pl.DataFrame) else len(records)
    if dry_run:
        logger.info(
            "[%s] dry-run: RAW %d 条 -> 目标 %s (去重后 %d 行)",
            metric,
            rec_count,
            plan["curated"],
            df.height,
        )
        post = plan.get("post_process")
        if post is not None:
            post(curated_root, curated_root / plan["curated"], dry_run=True)
        return rec_count

    if curated_file.exists() and not df.is_empty():
        try:
            to_null, changed = _regression_report(
                pl.read_parquet(curated_file), df, plan.get("primary_keys")
            )
        except Exception as exc:  # noqa: BLE001 - 对比失败不应阻断重放
            logger.debug("[%s] 重放回归对比跳过: %s", metric, exc)
        else:
            if to_null or changed:
                message = _format_drift(metric, to_null, changed)
                if strict_drift:
                    raise ReplayDriftError(message)
                logger.warning(message)

    raw_to_frame = plan.get("raw_to_frame")
    if raw_to_frame is not None:
        raw_df = raw_to_frame(records)
        if not raw_df.is_empty():
            raw_path = (
                raw_root / plan.get("raw_subdir", "semiconductor") / Path(plan["curated"]).name
            )
            save_curated_fact(
                raw_df,
                raw_path,
                primary_keys=plan["primary_keys"],
            )

    curated_root.mkdir(parents=True, exist_ok=True)
    total = save_curated_fact(df, curated_file, primary_keys=plan["primary_keys"])
    logger.info(
        "[%s] 重放完成: RAW %d 条 -> %s 共 %d 行", metric, rec_count, plan["curated"], total
    )

    # 后处理钩子
    post = plan.get("post_process")
    if post is not None:
        post(curated_root, curated_file, dry_run=False)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="重放 data/raw/industry RAW 数据到 Curated 黄金表")
    parser.add_argument("--metric", help="只重放指定指标 (默认全量)")
    parser.add_argument("--dry-run", action="store_true", help="只预览处理数量, 不落盘")
    parser.add_argument("--raw-root", default=str(RAW_ROOT), help="RAW 根目录")
    parser.add_argument("--curated-root", default=str(CURATED_ROOT), help="Curated 根目录")
    parser.add_argument(
        "--strict-drift",
        action="store_true",
        help="重放将改写既有 Curated 事实时中止 (默认仅告警)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    plan = _build_metric_plan()
    if args.metric:
        if args.metric not in plan:
            logger.error("未知指标: %s (可选: %s)", args.metric, ", ".join(sorted(plan)))
            raise SystemExit(1)
        plan = {args.metric: plan[args.metric]}

    raw_root = Path(args.raw_root)
    curated_root = Path(args.curated_root)
    total_records = 0
    ordered = [metric for metric in sorted(plan) if metric not in POWER_REPLAY_ORDER]
    ordered.extend(metric for metric in POWER_REPLAY_ORDER if metric in plan)
    for metric in ordered:
        try:
            total_records += replay_metric(
                metric,
                plan[metric],
                raw_root,
                curated_root,
                args.dry_run,
                args.strict_drift,
            )
        except ReplayDriftError as exc:
            logger.error("%s", exc)
            raise SystemExit(1) from exc

    mode = "dry-run 预览" if args.dry_run else "重放"
    logger.info("全部完成: %s %d 个指标, 共处理 %d 条 RAW 记录", mode, len(plan), total_records)


if __name__ == "__main__":
    main()
