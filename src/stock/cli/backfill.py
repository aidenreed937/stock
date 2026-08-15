"""历史数据全量与断点续传回填 CLI 入口模块。

负责接收用户命令行参数、加载配置、委托 BackfillPlanner 进行任务规划，并驱动 HistoricalBackfiller。
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from stock.config.loader import load_data_config
from stock.data.planner import BackfillPlanner, BackfillTask
from stock.utils.logger import logger


def _build_argument_parser() -> argparse.ArgumentParser:
    """构建回填 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(description="A 股全市场历史数据回填与断点续传引擎")
    parser.add_argument(
        "--start", "--start-date", dest="start_date", help="起始日期 (YYYY-MM-DD 或 today-N)"
    )
    parser.add_argument(
        "--end", "--end-date", dest="end_date", help="截止日期 (YYYY-MM-DD 或 today)"
    )
    parser.add_argument(
        "--source",
        "--data-source",
        dest="data_source",
        help="数据源 (tushare/yfinance/fred/lixinger)",
    )
    parser.add_argument("--endpoint", dest="endpoint", help="接口名称 (逗号分隔)")
    parser.add_argument(
        "--symbol", dest="symbol", help="股票/指数/基金代码 (逗号分隔或 'watchlist')"
    )
    parser.add_argument("--config", dest="config", help="回填 YAML 配置文件路径")
    parser.add_argument("--universe", dest="universe", help="股票池配置名称")
    parser.add_argument(
        "--force-refresh", action="store_true", help="是否强制拉取并覆盖本地已有数据"
    )
    parser.add_argument("--max-workers", type=int, help="并发 Worker 数量")
    return parser


def _parse_date(d_str: str | None) -> date | None:
    """解析多样化日期格式字符串。"""
    if not d_str:
        return None
    d_clean = d_str.strip().lower()
    if d_clean == "today":
        return date.today()
    if "today-" in d_clean:
        import re

        m = re.search(r"today-(\d+)", d_clean)
        if m:
            return date.today() - timedelta(days=int(m.group(1)))
    d_clean = d_clean.replace("-", "")
    return datetime.strptime(d_clean, "%Y%m%d").date()


def _format_summary_table(summaries: list[dict[str, Any]]) -> None:
    """打印回填摘要统计表。"""
    logger.info("=" * 105)
    logger.info("历史数据回填任务执行摘要汇总:")
    logger.info(
        f"{'数据源':<10} | {'接口/数据集':<22} | {'标的':<14} | {'总日历日':<8} | "
        f"{'交易日':<8} | {'已同步':<8} | {'已跳过':<8} | {'失败':<6}"
    )
    logger.info("-" * 105)
    for s in summaries:
        logger.info(
            f"{s.get('data_source', '')!s: <10} | {s.get('endpoint', '')!s: <22} | "
            f"{s.get('symbol', '')!s: <14} | {s.get('total_days', 0): <8} | "
            f"{s.get('open_days', 0): <8} | {s.get('synced_days', 0): <8} | "
            f"{s.get('skipped_days', 0): <8} | {s.get('failed_days', 0): <6}"
        )
    logger.info("=" * 105)


def _execute_planned_tasks(
    tasks: list[BackfillTask], *, force_refresh: bool, workers: int
) -> list[dict[str, Any]]:
    """以攒批事务模式驱动执行规划任务。"""
    import stock.data.backfill as backfill_module

    summaries: list[dict[str, Any]] = []
    batch_contexts: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        for idx, task in enumerate(tasks, 1):
            context_key = (task.data_source, task.endpoint)
            batch_context = batch_contexts.get(context_key)
            if batch_context is None:
                backfiller = _create_backfiller(backfill_module, task)
                batch_context = _create_batch_context(backfiller)
                batch_contexts[context_key] = batch_context
            else:
                batch_context["task_count"] += 1
                backfiller = _create_backfiller(
                    backfill_module,
                    task,
                    pipeline=batch_context["pipeline"],
                    fetcher=batch_context["fetcher"],
                )
            summaries.append(
                _execute_one_task(
                    backfiller,
                    task,
                    task_position=(idx, len(tasks)),
                    force_refresh=force_refresh,
                    workers=workers,
                )
            )
    finally:
        _commit_batch_contexts(batch_contexts)
    return summaries


def _create_backfiller(
    backfill_module: Any,
    task: BackfillTask,
    *,
    pipeline: Any | None = None,
    fetcher: Any | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "data_source": task.data_source,
        "endpoint": task.endpoint,
        "symbol": task.symbol,
    }
    if pipeline is not None:
        kwargs["pipeline"] = pipeline
    if fetcher is not None:
        kwargs["fetcher"] = fetcher
    return backfill_module.HistoricalBackfiller(**kwargs)


def _create_batch_context(backfiller: Any) -> dict[str, Any]:
    return {
        "pipeline": getattr(backfiller, "pipeline", None),
        "fetcher": getattr(backfiller, "fetcher", None),
        "batch_targets": _enable_pipeline_batch_mode(backfiller),
        "task_count": 1,
    }


def _execute_one_task(
    backfiller: Any,
    task: BackfillTask,
    *,
    task_position: tuple[int, int],
    force_refresh: bool,
    workers: int,
) -> dict[str, Any]:
    task_index, total_tasks = task_position
    logger.info(
        f"===> [{task_index}/{total_tasks}] 执行任务 [{task.data_source}/{task.endpoint}] "
        f"标的: [{task.symbol or '全市场'}] 区间: [{task.start_date} ~ {task.end_date}]"
    )
    summary = backfiller.backfill_range(
        task.start_date,
        task.end_date,
        force_refresh=force_refresh,
        max_workers=workers,
    )
    summary_data: dict[str, Any] = dict(summary) if isinstance(summary, dict) else {}
    summary_data["data_source"] = task.data_source
    summary_data["endpoint"] = task.endpoint
    summary_data["symbol"] = task.symbol or "全市场"
    return summary_data


def _commit_batch_contexts(batch_contexts: dict[tuple[str, str], dict[str, Any]]) -> None:
    for (data_source, endpoint), batch_context in batch_contexts.items():
        logger.info(
            f"提交任务组 [{data_source}/{endpoint}] 攒批数据，"
            f"共 {batch_context['task_count']} 个任务"
        )
        _commit_batch_targets(batch_context["batch_targets"])


def _enable_pipeline_batch_mode(backfiller: Any) -> list[Any]:
    pipeline = getattr(backfiller, "pipeline", None)
    targets = [
        getattr(pipeline, "store", None),
        getattr(pipeline, "raw_store", None),
    ]
    enabled_targets: list[Any] = []
    for target in targets:
        enable_batch_mode = getattr(target, "enable_batch_mode", None)
        if callable(enable_batch_mode):
            enable_batch_mode()
            enabled_targets.append(target)
    return enabled_targets


def _commit_batch_targets(targets: list[Any]) -> None:
    for target in targets:
        commit = getattr(target, "commit", None)
        if callable(commit):
            commit()


def _resolve_universe_symbols(universe_name: str | None) -> str | None:
    """从 Universe 配置文件中解析标的列表。"""
    if not universe_name:
        return None
    uni_path = Path(f"config/universe/{universe_name}.yaml")
    if not uni_path.exists():
        return None
    try:
        with uni_path.open("r", encoding="utf-8") as f:
            uni_data = yaml.safe_load(f)
            if isinstance(uni_data, dict):
                u_def = uni_data.get("universe", {})
                syms = u_def.get("symbols", []) if isinstance(u_def, dict) else []
                if isinstance(syms, list) and syms:
                    return ",".join(str(s) for s in syms)
    except Exception as err:
        logger.warning(f"加载 Universe 股票池 [{universe_name}] 失败: {err}")
    return None


def main() -> None:
    """CLI 主入口函数。"""
    import stock.data.backfill as backfill_module

    parser = _build_argument_parser()
    args = parser.parse_args()

    yaml_config = (
        backfill_module._load_backfill_yaml_config(args.config)
        if args.config
        else backfill_module._load_backfill_yaml_config()
    )
    data_cfg = load_data_config()

    data_source = (
        args.data_source
        or yaml_config.get("data_source")
        or yaml_config.get("default_data_source", "tushare")
    )
    symbol = (
        args.symbol
        or _resolve_universe_symbols(args.universe)
        or yaml_config.get("symbol")
        or yaml_config.get("default_symbol")
    )
    raw_endpoints = (
        args.endpoint or yaml_config.get("endpoint") or yaml_config.get("default_endpoint")
    )
    endpoint_list = (
        [ep.strip() for ep in raw_endpoints.split(",") if ep.strip()] if raw_endpoints else None
    )
    force_refresh = args.force_refresh or yaml_config.get("force_refresh", False)

    start_specified = bool(
        args.start_date or yaml_config.get("start_date") or yaml_config.get("default_start_date")
    )
    start_d = (
        _parse_date(args.start_date)
        or _parse_date(yaml_config.get("start_date"))
        or _parse_date(yaml_config.get("default_start_date"))
        or date(2024, 1, 1)
    )
    end_d = (
        _parse_date(args.end_date)
        or _parse_date(yaml_config.get("end_date"))
        or _parse_date(yaml_config.get("default_end_date"))
        or date.today()
    )

    workers = args.max_workers or yaml_config.get("max_workers")
    if workers is None and data_cfg:
        workers = getattr(
            data_cfg.concurrency,
            f"{data_source}_max_workers",
            data_cfg.concurrency.default_max_workers,
        )
    workers = workers or 1

    tasks = BackfillPlanner.plan_tasks(
        data_source=data_source,
        endpoints=endpoint_list,
        symbol=symbol,
        start_date=start_d,
        end_date=end_d,
        start_specified=start_specified,
        data_cfg=data_cfg,
    )

    if not tasks:
        logger.warning(f"数据源 [{data_source}] 未规划出任何有效回填任务")
        return

    logger.info(f"[{data_source}] 回填任务规划完成，共生成 {len(tasks)} 个原子回填任务。")
    summaries = _execute_planned_tasks(tasks, force_refresh=force_refresh, workers=workers)
    _format_summary_table(summaries)

    failed_items = [
        item
        for item in summaries
        if isinstance(val := item.get("failed_days"), int | float) and val > 0
    ]
    failed_days = sum(
        int(val) for item in failed_items if isinstance(val := item.get("failed_days"), int | float)
    )
    if failed_days:
        logger.error(
            f"历史数据回填存在失败任务，失败交易日数合计: {failed_days}, 失败项清单: {failed_items}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
