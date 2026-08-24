"""业务管线运行产物索引与清理 CLI。"""

from __future__ import annotations

import argparse
from pathlib import Path
from time import time

from stock_analytics.pipelines.artifact_cleanup import (
    ArtifactRunCandidate,
    collect_run_candidates,
    delete_run_candidates,
)
from stock_analytics.pipelines.artifact_contracts import RUN_CLASSES
from stock_analytics.pipelines.artifact_index import rebuild_run_index


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="索引与清理业务管线运行产物")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="重建运行索引")
    index_parser.add_argument("--root", required=True, help="单条管线产物根目录")

    cleanup_parser = subparsers.add_parser("cleanup", help="预览或清理历史运行包")
    cleanup_parser.add_argument("--root", required=True, help="单条管线产物根目录")
    cleanup_parser.add_argument(
        "--latest-root",
        default=None,
        help="latest 所在根目录；不传时与 --root 相同",
    )
    cleanup_parser.add_argument("--older-than-days", type=float, default=30.0)
    cleanup_parser.add_argument(
        "--run-class",
        choices=RUN_CLASSES,
        default="experiment",
        help="默认只清理 experiment；清理 official/backfill 需显式指定",
    )
    cleanup_parser.add_argument("--no-keep-latest", action="store_true")
    cleanup_parser.add_argument("--apply", action="store_true", help="执行删除；默认只预览")

    return parser


def main(argv: list[str] | None = None) -> int:
    """执行索引或清理命令。"""
    args = _build_parser().parse_args(argv)
    if args.command == "index":
        payload = rebuild_run_index(Path(args.root))
        print(f"运行索引已更新: {args.root}，记录 {len(payload['runs'])} 个运行包")
        return 0

    try:
        candidates = collect_run_candidates(
            Path(args.root),
            args.older_than_days,
            run_class=args.run_class,
            latest_root=Path(args.latest_root) if args.latest_root else None,
            keep_latest=not args.no_keep_latest,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as error:
        _build_parser().error(str(error))
    _print_candidates(candidates, Path(args.root))
    if not args.apply:
        print("预览模式，未删除任何运行包。需要执行删除时追加 --apply。")
        return 0

    cutoff = time() - args.older_than_days * 24 * 60 * 60
    deleted, skipped = delete_run_candidates(candidates, root=Path(args.root), cutoff=cutoff)
    rebuild_run_index(Path(args.root))
    print(f"已删除: {deleted} 个；跳过: {skipped} 个。")
    return 0


def _print_candidates(candidates: list[ArtifactRunCandidate], root: Path) -> None:
    total_size = sum(item.size_bytes for item in candidates)
    resolved_root = root.resolve()
    print(f"产物根目录: {resolved_root}")
    print(f"候选运行包: {len(candidates)} 个；总大小: {total_size} bytes")
    for item in candidates:
        print(
            f"- [{item.run_class}] {item.path.relative_to(resolved_root)} ({item.size_bytes} bytes)"
        )


if __name__ == "__main__":
    raise SystemExit(main())
