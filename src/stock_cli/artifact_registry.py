"""CLI 入口：分析管线产物元数据、指标、血统与生命周期治理 (SQLite 控制面)。

用法:
    # 1. 扫描磁盘存量产物并一键同步到 SQLite
    uv run python -m stock_cli.artifact_registry --sync-fs

    # 2. 多维查询产物运行列表
    uv run python -m stock_cli.artifact_registry --list --pipeline market_temperature

    # 3. 查看单个产物详情 (含指标快照、上游水位与文件清单)
    uv run python -m stock_cli.artifact_registry --show --run-id <run_id>

    # 4. 横向比对两个 Run 之间的指标差异 (Run Diff)
    uv run python -m stock_cli.artifact_registry --diff <run_id_a> <run_id_b>

    # 5. 上游数据变更时反查过时产物
    uv run python -m stock_cli.artifact_registry --find-stale --dataset daily_bars --watermark 2026-08-15

    # 6. 锁定保护 / 解除锁定
    uv run python -m stock_cli.artifact_registry --pin <run_id>
    uv run python -m stock_cli.artifact_registry --unpin <run_id>

    # 7. 查看可安全清理的历史产物候选
    uv run python -m stock_cli.artifact_registry --prune-candidates --older-than-days 30
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stock_analytics.pipelines.artifacts import ArtifactRegistryRepository
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="分析管线产物元数据、数据血统、指标时序与生命周期治理工具 (SQLite 控制面)",
    )
    parser.add_argument(
        "--sync-fs", action="store_true", help="扫描 data/analytics 存量产物并同步至 SQLite"
    )
    parser.add_argument("--list", action="store_true", help="列出产物运行记录")
    parser.add_argument(
        "--pipeline", type=str, default=None, help="按管线名称筛选 (如: market_temperature)"
    )
    parser.add_argument("--date", type=str, default=None, help="按业务日期筛选 (YYYY-MM-DD)")
    parser.add_argument(
        "--run-class", type=str, default=None, help="按运行分类筛选 (official/backfill/experiment)"
    )
    parser.add_argument("--limit", type=int, default=30, help="返回记录数量上限 (默认: 30)")

    parser.add_argument("--show", action="store_true", help="查看单个产物详情")
    parser.add_argument("--run-id", type=str, default=None, help="运行唯一标识 (run_id)")

    # 指标横向对比
    parser.add_argument(
        "--diff", nargs=2, metavar=("RUN_A", "RUN_B"), help="对比两个 Run 的指标差异"
    )

    # 上游失效反查
    parser.add_argument(
        "--find-stale", action="store_true", help="反查受上游数据变更影响的过时产物"
    )
    parser.add_argument("--dataset", type=str, default=None, help="上游数据集名称 (如: daily_bars)")
    parser.add_argument("--watermark", type=str, default=None, help="上游水位日期 (YYYY-MM-DD)")

    # 锁定保护与清理
    parser.add_argument("--pin", type=str, default=None, help="锁定保护指定产物 (防止被自动清理)")
    parser.add_argument("--unpin", type=str, default=None, help="解除指定产物的锁定保护")
    parser.add_argument(
        "--prune-candidates", action="store_true", help="列出符合安全清理条件的产物候选"
    )
    parser.add_argument(
        "--older-than-days", type=float, default=30.0, help="清理保留天数阈值 (默认: 30天)"
    )

    return parser


def _sync_filesystem_runs(repo: ArtifactRegistryRepository, root_dir: Path) -> int:
    """扫描 data/analytics 下的所有 manifest.json 并同步入库。"""
    count = 0
    if not root_dir.is_dir():
        return 0
    for manifest_path in root_dir.glob("**/runs/as_of=*/run_*/manifest.json"):
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            run_dir = manifest_path.parent
            repo.record_run(manifest=manifest_data, run_dir=run_dir, is_latest=False)
            count += 1
        except Exception as exc:
            logger.warning("同步产物 [%s] 失败: %s", manifest_path, exc)
    return count


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    repo = ArtifactRegistryRepository()

    # 1. 存量扫描同步
    if args.sync_fs:
        analytics_root = Path("data/analytics")
        n = _sync_filesystem_runs(repo, analytics_root)
        print(f"✅ 成功从 {analytics_root} 扫描并同步 {n} 个历史产物运行至 SQLite 控制面！")
        return

    # 2. 列表查询
    if args.list:
        runs = repo.list_runs(
            pipeline_name=args.pipeline,
            as_of_date=args.date,
            run_class=args.run_class,
            limit=args.limit,
        )
        if not runs:
            print("未找到匹配的产物运行记录。")
            return
        print(f"=== 分析产物运行列表 (共 {len(runs)} 条) ===")
        print(
            f"{'运行 ID':<35} {'管线名称':<20} {'业务日期':<12} {'分类':<10} {'状态':<10} {'Latest':<8} {'Pinned':<8}"
        )
        print("-" * 105)
        for r in runs:
            latest_str = "⭐ 是" if r["is_latest"] else "否"
            pinned_str = "🔒 是" if r["is_pinned"] else "否"
            print(
                f"{r['run_id']:<35} {r['pipeline_name']:<20} {r['as_of_date']:<12} "
                f"{r['run_class']:<10} {r['status']:<10} {latest_str:<8} {pinned_str:<8}"
            )
        return

    # 3. 查看单个产物详情
    if args.show:
        if not args.run_id:
            logger.error("查看详情必须指定 --run-id")
            sys.exit(1)
        detail = repo.get_run(args.run_id)
        if not detail:
            print(f"未找到 run_id 为 [{args.run_id}] 的产物记录。")
            return
        print("==================================================================")
        print(f" 产物运行详情: {detail['run_id']}")
        print(f" 所属管线:     {detail['pipeline_name']} ({detail['run_class']})")
        print(f" 业务日期:     {detail['as_of_date']} | 生成时间: {detail['generated_at']}")
        print(f" 运行状态:     {detail['status']} | 耗时: {detail['duration_ms']} ms")
        print(f" Latest 指向:  {'⭐ 是' if detail['is_latest'] else '否'}")
        print(f" 锁定保护:     {'🔒 是' if detail['is_pinned'] else '否'}")
        print(f" 物理路径:     {detail['artifact_root']}")
        print("------------------------------------------------------------------")
        print(f" [核心量化指标] ({len(detail['metrics'])} 个):")
        for k, v in sorted(detail["metrics"].items()):
            print(f"   • {k:<30} = {v}")
        print("------------------------------------------------------------------")
        print(f" [上游数据血统] ({len(detail['watermarks'])} 个上游源):")
        for w in detail["watermarks"]:
            print(
                f"   • {w['data_source']}.{w['dataset_name']:<20} 水位: {w['upstream_watermark'] or 'N/A'}"
            )
        print("------------------------------------------------------------------")
        print(f" [产物文件清单] ({len(detail['files'])} 个文件):")
        for f in detail["files"]:
            print(
                f"   • [{f['file_type']:<14}] {f['rel_path']:<25} ({f['file_size_bytes']:,} bytes)"
            )
        print("==================================================================")
        return

    # 4. 指标横向对比 (Diff)
    if args.diff:
        r_a, r_b = args.diff
        diff_res = repo.diff_runs(r_a, r_b)
        metrics = diff_res["metrics"]
        if not metrics:
            print(f"在运行 [{r_a}] 与 [{r_b}] 之间未找到共同或可对比的指标。")
            return
        print(f"=== 产物指标横向对比: [{r_a}] vs [{r_b}] ===")
        print(f"{'指标名称':<35} {'Run A':<15} {'Run B':<15} {'差异 (B - A)':<15}")
        print("-" * 80)
        for m in metrics:
            va_str = f"{m['val_a']:.4f}" if m["val_a"] is not None else "N/A"
            vb_str = f"{m['val_b']:.4f}" if m["val_b"] is not None else "N/A"
            d_str = f"{m['delta']:+.4f}" if m["delta"] is not None else "N/A"
            print(f"{m['metric_key']:<35} {va_str:<15} {vb_str:<15} {d_str:<15}")
        return

    # 5. 上游失效反查
    if args.find_stale:
        if not args.dataset or not args.watermark:
            logger.error("反查失效产物必须提供 --dataset 和 --watermark")
            sys.exit(1)
        stale_runs = repo.find_stale_runs(args.dataset, args.watermark)
        if not stale_runs:
            print(f"未发现受 [{args.dataset} @ {args.watermark}] 影响的历史产物。")
            return
        print(f"🚨 发现受上游数据变更影响的下游产物 ({len(stale_runs)} 个):")
        print(f"{'运行 ID':<35} {'管线名称':<20} {'业务日期':<12} {'上游数据源':<15}")
        print("-" * 85)
        for r in stale_runs:
            print(
                f"{r['run_id']:<35} {r['pipeline_name']:<20} {r['as_of_date']:<12} {r['data_source']:<15}"
            )
        return

    # 6. 锁定与解锁
    if args.pin:
        ok = repo.set_pinned(args.pin, True)
        print(f"{'🔒 已锁定保护产物' if ok else '❌ 未找到产物'}: {args.pin}")
        return

    if args.unpin:
        ok = repo.set_pinned(args.unpin, False)
        print(f"{'🔓 已解除产物保护' if ok else '❌ 未找到产物'}: {args.unpin}")
        return

    # 7. 清理候选
    if args.prune_candidates:
        candidates = repo.collect_pruning_candidates(
            pipeline_name=args.pipeline,
            older_than_days=args.older_than_days,
            run_class=args.run_class,
        )
        if not candidates:
            print(f"未发现超过 {args.older_than_days} 天且可安全清理的产物。")
            return
        print(f"=== 可安全清理的历史产物候选 ({len(candidates)} 个) ===")
        print(f"{'运行 ID':<35} {'管线名称':<20} {'业务日期':<12} {'生成时间':<20}")
        print("-" * 90)
        for c in candidates:
            print(
                f"{c['run_id']:<35} {c['pipeline_name']:<20} {c['as_of_date']:<12} {c['generated_at']:<20}"
            )
        return

    parser.print_help()


if __name__ == "__main__":
    main()
