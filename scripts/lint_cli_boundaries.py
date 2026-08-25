"""检查已迁移 CLI 入口的规模 ratchet。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "config/cli_boundaries_baseline.json"


def main() -> int:
    """确保已迁移 CLI 不重新承载业务逻辑。"""
    baseline = _load_baseline()
    violations: list[str] = []
    for relative_path, spec in baseline.get("commands", {}).items():
        path = ROOT / relative_path
        if not path.is_file():
            violations.append(f"入口文件不存在: {relative_path}")
            continue
        max_lines = spec.get("max_lines")
        if not isinstance(max_lines, int):
            violations.append(f"入口基线缺少有效 max_lines: {relative_path}")
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > max_lines:
            violations.append(f"{relative_path}: {line_count} 行 > ratchet 上限 {max_lines} 行")
    for violation in violations:
        print(violation)
    if violations:
        print(f"CLI 边界 ratchet 检查失败: {len(violations)} 个问题")
        return 1
    print("CLI 边界 ratchet 检查通过")
    return 0


def _load_baseline() -> dict[str, Any]:
    try:
        payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"无法读取 CLI 边界基线: {BASELINE_PATH}: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"CLI 边界基线格式错误: {BASELINE_PATH}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
