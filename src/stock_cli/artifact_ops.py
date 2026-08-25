"""业务管线运行产物索引与清理 CLI 兼容入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

from stock_analytics.pipelines.artifact_ops import (
    RUN_CLASSES,
    ArtifactRunCandidate,
    cleanup_artifacts,
    index_artifacts,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="索引与清理业务管线运行产物")
    subparsers = parser.add_subparsers(dest="command", required=True)
    index_parser = subparsers.add_parser("index", help="重建运行索引")
    index_parser.add_argument("--root", required=True, help="单条管线产物根目录")
    cleanup_parser = subparsers.add_parser("cleanup", help="预览或清理历史运行包")
    cleanup_parser.add_argument("--root", required=True, help="单条管线产物根目录")
    cleanup_parser.add_argument("--latest-root", default=None)
    cleanup_parser.add_argument("--older-than-days", type=float, default=30.0)
    cleanup_parser.add_argument("--run-class", choices=RUN_CLASSES, default="experiment")
    cleanup_parser.add_argument("--no-keep-latest", action="store_true")
    cleanup_parser.add_argument("--apply", action="store_true", help="执行删除；默认只预览")
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析参数并调用产物运维 Facade。"""
    args = _build_parser().parse_args(argv)
    if args.command == "index":
        result = index_artifacts(Path(args.root))
        print(f"运行索引已更新: {result.root}，记录 {result.run_count} 个运行包")
        return 0

    try:
        cleanup_result = cleanup_artifacts(
            Path(args.root),
            args.older_than_days,
            run_class=args.run_class,
            latest_root=Path(args.latest_root) if args.latest_root else None,
            keep_latest=not args.no_keep_latest,
            apply=args.apply,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as error:
        _build_parser().error(str(error))
    _print_candidates(cleanup_result.candidates, cleanup_result.root)
    if not cleanup_result.applied:
        print("预览模式，未删除任何运行包。需要执行删除时追加 --apply。")
        return 0
    print(f"已删除: {cleanup_result.deleted} 个；跳过: {cleanup_result.skipped} 个。")
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
