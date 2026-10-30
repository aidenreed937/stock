"""从本地 TuShare Curated 输入重建版本化申万成分表。"""

from __future__ import annotations

import argparse
from pathlib import Path

from stock_data.pipeline.index_member_versioned import materialize_index_member_versioned


def main() -> int:
    """执行 dry-run 或应用版本化成员表重建。"""
    parser = argparse.ArgumentParser(description="重建 index_member_versioned Curated 黄金表")
    parser.add_argument("--storage-dir", default=None, help="Curated 数据根目录，默认使用项目配置")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="将重建结果原子写入 Curated；缺省只预览，不修改磁盘",
    )
    args = parser.parse_args()
    frame = materialize_index_member_versioned(
        storage_dir=Path(args.storage_dir) if args.storage_dir else None,
        dry_run=not args.apply,
    )
    print(
        f"index_member_versioned: rows={frame.height}, "
        f"src={sorted(frame.get_column('src').unique().to_list()) if 'src' in frame.columns else []}, "
        f"mode={'apply' if args.apply else 'dry-run'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
