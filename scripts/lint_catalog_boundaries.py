"""检查业务层是否绕过 DataCatalog 直接读取 Curated 物理目录。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_ROOTS = (ROOT / "src/stock_analytics", ROOT / "src/stock_reporting")
ALLOWED_ROOTS = (ROOT / "src/stock_analytics/features",)
CURATED_MARKERS = ("data/curated", "curated_root", "curated_dir", "curated_data_dir")
PHYSICAL_DISCOVERY_METHODS = frozenset({"glob", "rglob"})
PARQUET_READ_METHODS = frozenset({"read_parquet", "scan_parquet"})


@dataclass(frozen=True, slots=True)
class Violation:
    """单条 Curated 物理读取边界违规。"""

    path: Path
    line: int
    message: str


def main() -> int:
    """执行业务层 Curated 读取边界检查。"""
    violations = [
        violation
        for root in TARGET_ROOTS
        for path in root.rglob("*.py")
        if not _is_allowed(path)
        for violation in check_file(path)
    ]
    for violation in violations:
        print(f"{violation.path}:{violation.line}: {violation.message}")
    if violations:
        print(f"Catalog 物理读取边界检查失败: {len(violations)} 个问题")
        return 1
    print("Catalog 物理读取边界检查通过")
    return 0


def check_file(path: Path) -> list[Violation]:
    """检查单个 Python 文件中的 Curated 物理读取调用。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        if method in PHYSICAL_DISCOVERY_METHODS and _contains_curated_reference(node):
            violations.append(
                Violation(path, node.lineno, f"业务层禁止直接使用 {method}() 扫描 Curated 目录")
            )
        elif (
            method in PARQUET_READ_METHODS
            and node.args
            and _contains_curated_reference(node.args[0])
        ):
            violations.append(
                Violation(path, node.lineno, f"业务层禁止直接使用 {method}() 读取 Curated 文件")
            )
    return violations


def _is_allowed(path: Path) -> bool:
    resolved = path.resolve()
    return any(resolved == root or root in resolved.parents for root in ALLOWED_ROOTS)


def _contains_curated_reference(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            value = child.value.casefold()
            if any(marker in value for marker in CURATED_MARKERS):
                return True
        if isinstance(child, ast.Name) and _is_curated_name(child.id):
            return True
        if isinstance(child, ast.Attribute) and _is_curated_name(child.attr):
            return True
    return False


def _is_curated_name(value: str) -> bool:
    normalized = value.casefold()
    return any(
        marker.replace("_", "") in normalized.replace("_", "") for marker in CURATED_MARKERS[1:]
    )


if __name__ == "__main__":
    raise SystemExit(main())
