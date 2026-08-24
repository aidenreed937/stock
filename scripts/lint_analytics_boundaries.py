"""检查 analytics 分层和外部消费者的导入边界。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
CONSUMER_ROOTS = (SRC_ROOT / "stock_cli", SRC_ROOT / "stock_strategy")
PUBLIC_ROOTS = {
    "stock_analytics.api",
    "stock_analytics.features",
    "stock_analytics.marts",
    "stock_analytics.metrics",
    "stock_analytics.primitives",
    "stock_analytics.realtime",
}
PIPELINE_ROOT = "stock_analytics.pipelines"
LAYER_FORBIDDEN = {
    "primitives": {"features", "metrics", "marts", "pipelines", "realtime"},
    "metrics": {"features", "marts", "pipelines"},
    "features": {"metrics", "pipelines"},
}


@dataclass(frozen=True, slots=True)
class Violation:
    """单条导入边界违规。"""

    path: Path
    line: int
    message: str


def main() -> int:
    """执行导入边界检查。"""
    violations = [
        *_check_external_consumers(),
        *_check_internal_layers(),
        *_check_public_exports(),
    ]
    for violation in violations:
        print(f"{violation.path}:{violation.line}: {violation.message}")
    if violations:
        print(f"analytics 导入边界检查失败: {len(violations)} 个问题")
        return 1
    print("analytics 导入边界检查通过")
    return 0


def _check_external_consumers() -> list[Violation]:
    violations: list[Violation] = []
    for root in CONSUMER_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for target, line in _imports(tree):
                if target.startswith("stock_analytics.") and not _is_public_import(target):
                    violations.append(
                        Violation(
                            path, line, f"外部消费者必须通过 analytics 包级门面导入: {target}"
                        )
                    )
    return violations


def _check_internal_layers() -> list[Violation]:
    violations: list[Violation] = []
    analytics_root = SRC_ROOT / "stock_analytics"
    for layer, forbidden in LAYER_FORBIDDEN.items():
        layer_root = analytics_root / layer
        for path in layer_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for target, line in _imports(tree):
                parts = target.split(".")
                if len(parts) >= 2 and parts[:2] == ["stock_analytics", parts[1]]:
                    imported_layer = parts[1]
                    if imported_layer in forbidden:
                        violations.append(
                            Violation(path, line, f"{layer} 不得依赖 {imported_layer}: {target}")
                        )
    return violations


def _check_public_exports() -> list[Violation]:
    violations: list[Violation] = []
    analytics_root = SRC_ROOT / "stock_analytics"
    for path in analytics_root.rglob("__init__.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        exports = _literal_all(tree)
        if exports is None:
            continue
        declared = _declared_names(tree)
        for name in exports:
            if name not in declared:
                violations.append(
                    Violation(path, _all_line(tree), f"__all__ 导出了未定义名称: {name}")
                )
    return violations


def _is_public_import(target: str) -> bool:
    if target in PUBLIC_ROOTS:
        return True
    if target == PIPELINE_ROOT:
        return True
    if target.startswith(f"{PIPELINE_ROOT}."):
        return target.count(".") == 2
    return False


def _imports(tree: ast.AST) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append((node.module, node.lineno))
    return result


def _literal_all(tree: ast.Module) -> list[str] | None:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            return None
        return (
            [item for item in value if isinstance(item, str)]
            if isinstance(value, (list, tuple))
            else None
        )
    return None


def _declared_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _all_line(tree: ast.Module) -> int:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return node.lineno
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
