"""从本地 TuShare/LiXinger Curated 输入重建申万跨源黄金表。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stock_data.pipeline.sw_industry_golden import materialize_sw_2021_industry_golden


def main() -> int:
    """执行 dry-run 或应用申万跨源黄金表重建。"""
    parser = argparse.ArgumentParser(description="重建申万 2021 跨源行业黄金表")
    parser.add_argument("--storage-dir", default=None, help="Curated 数据根目录，默认使用项目配置")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="将重建结果原子写入 derived Curated；缺省只预览，不修改磁盘",
    )
    args = parser.parse_args()
    result = materialize_sw_2021_industry_golden(
        storage_dir=Path(args.storage_dir) if args.storage_dir else None,
        dry_run=not args.apply,
    )
    payload = {
        "dimension_rows": result.dimension.height,
        "member_rows": result.members.height,
        "snapshot_date": result.snapshot_date,
        "request_id": result.request_id,
        "conflict_rows": (
            int(result.members.filter(result.members["conflict_flag"]).height)
            if "conflict_flag" in result.members.columns
            else 0
        ),
        "canonical_rows": (
            int(result.members.filter(result.members["is_canonical"]).height)
            if "is_canonical" in result.members.columns
            else 0
        ),
        "mode": "apply" if args.apply else "dry-run",
        "dimension_path": str(result.dimension_path) if result.dimension_path else None,
        "member_path": str(result.member_path) if result.member_path else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
