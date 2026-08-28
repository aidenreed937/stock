"""清理宏观风控 runs 目录下冗余的多批次历史产物，仅保留各交易日最新批次。"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def cleanup_runs(
    runs_root: Path | str = "data/analytics/macro_risk/runs",
    *,
    keep_latest: int = 1,
    dry_run: bool = False,
) -> None:
    root = Path(runs_root)
    if not root.is_dir():
        print(f"未找到运行目录: {root}")
        return

    as_of_dirs = sorted(root.glob("as_of=*"))
    total_checked = 0
    total_deleted = 0

    print(f"=== 开始扫描并清理宏观风控冗余运行产物 (保留最新 {keep_latest} 批次) ===")
    if dry_run:
        print("【DRY-RUN 演练模式：仅展示拟清理目录，不执行物理删除】\n")

    for as_of_dir in as_of_dirs:
        runs = sorted(path for path in as_of_dir.glob("run_*") if path.is_dir())
        total_checked += len(runs)
        if len(runs) <= keep_latest:
            continue

        to_delete = runs[:-keep_latest]
        for run_dir in to_delete:
            total_deleted += 1
            if dry_run:
                print(f"  [拟删除] {run_dir}")
            else:
                shutil.rmtree(run_dir)
                print(f"  [已删除] {run_dir}")

    print("\n--- 清理结果统计 ---")
    print(f"  - 扫描交易日分区数: {len(as_of_dirs)}")
    print(f"  - 扫描运行批次数  : {total_checked}")
    print(f"  - {'拟' if dry_run else '已'}清理冗余批次: {total_deleted}")
    print(f"  - 保留有效批次数  : {total_checked - total_deleted}")


def main() -> None:
    parser = argparse.ArgumentParser(description="清理宏观风控多批次历史产物工具。")
    parser.add_argument(
        "--root",
        type=str,
        default="data/analytics/macro_risk/runs",
        help="Runs 根目录路径",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=1,
        help="每个交易日保留最新的批次数 (默认 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览拟删除的目录，不执行物理删除",
    )
    args = parser.parse_args()

    cleanup_runs(
        runs_root=args.root,
        keep_latest=args.keep,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
