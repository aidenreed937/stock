"""数据目录基线清单工具。"""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import polars as pl


def build_baseline(root: str = "data", output: str | None = None) -> dict[str, Any]:
    """扫描 RAW/Curated Parquet，生成可比较的文件、Schema、日期和哈希清单。"""
    base = Path(root)
    files: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.parquet")) if base.exists() else []:
        raw = path.read_bytes()
        item: dict[str, Any] = {
            "path": str(path),
            "bytes": len(raw),
            "sha256": sha256(raw).hexdigest(),
        }
        try:
            df = pl.read_parquet(path)
            item["rows"] = len(df)
            item["columns"] = df.columns
            date_col = next(
                (
                    c
                    for c in ("trade_date", "date", "end_date", "month", "quarter")
                    if c in df.columns
                ),
                None,
            )
            if date_col and not df.is_empty():
                values = df[date_col].cast(pl.Utf8, strict=False)
                item["date_column"] = date_col
                item["min_date"] = values.min()
                item["max_date"] = values.max()
        except Exception as exc:
            item["error"] = str(exc)
        files.append(item)
    result = {"generated_at": datetime.now(UTC).isoformat(), "root": str(base), "files": files}
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="生成数据目录基线清单")
    parser.add_argument("--root", default="data")
    parser.add_argument("--output", default="data/audit/baseline.json")
    args = parser.parse_args()
    print(json.dumps(build_baseline(args.root, args.output), ensure_ascii=False, indent=2))
