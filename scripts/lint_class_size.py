"""代码健康度与类规模静态约束工具.

用于防止类与模块代码无约束膨胀（God Class、职责过载）。
提供基于 AST 的类物理行数、方法总数、文件行数门禁，
并支持存量基线锁定（只许减不许增）与增量强阻断（Fail-Closed）。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASELINE_PATH = Path("config/code_health_baseline.json")


@dataclass(frozen=True)
class Limits:
    """阈值配置参数."""

    max_class_lines: int = 200
    max_class_methods: int = 10
    max_file_lines: int = 400


@dataclass
class ClassMetric:
    """单个类的度量数据."""

    name: str
    file_path: str
    lineno: int
    lines: int
    methods_count: int

    @property
    def key(self) -> str:
        """生成唯一标识键."""
        return f"{self.file_path}::{self.name}"


@dataclass
class FileMetric:
    """单个文件的度量数据."""

    file_path: str
    lines: int


def analyze_file(file_path: Path) -> tuple[FileMetric, list[ClassMetric]]:
    """使用 AST 解析单个 Python 文件并提取类与文件度量."""
    rel_path = str(file_path.as_posix())
    content = file_path.read_text(encoding="utf-8")
    file_lines = len(content.splitlines())
    file_metric = FileMetric(file_path=rel_path, lines=file_lines)

    class_metrics: list[ClassMetric] = []
    tree = ast.parse(content, filename=rel_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            end_lineno = node.end_lineno if node.end_lineno is not None else node.lineno
            lines = end_lineno - node.lineno + 1
            # 统计类体内定义的函数与方法（包含普通方法、异步方法、静态方法、类方法）
            methods = [
                n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            class_metrics.append(
                ClassMetric(
                    name=node.name,
                    file_path=rel_path,
                    lineno=node.lineno,
                    lines=lines,
                    methods_count=len(methods),
                )
            )

    return file_metric, class_metrics


def scan_directory(
    root_dir: Path, target_files: list[Path] | None = None
) -> tuple[list[FileMetric], list[ClassMetric]]:
    """扫描指定目录或指定文件列表."""
    all_files: list[FileMetric] = []
    all_classes: list[ClassMetric] = []

    if target_files:
        files_to_scan = [f for f in target_files if f.suffix == ".py" and f.exists()]
    else:
        files_to_scan = sorted(root_dir.rglob("*.py"))

    for file_path in files_to_scan:
        try:
            file_m, class_m_list = analyze_file(file_path)
            all_files.append(file_m)
            all_classes.extend(class_m_list)
        except Exception as e:
            print(f"[WARN] 无法解析文件 {file_path}: {e}", file=sys.stderr)

    return all_files, all_classes


def load_baseline(baseline_path: Path) -> dict:
    """加载代码健康度基线文件."""
    if not baseline_path.exists():
        return {"classes": {}, "files": {}, "thresholds": {}}
    try:
        return json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] 无法读取基线文件 {baseline_path}: {e}", file=sys.stderr)
        return {"classes": {}, "files": {}, "thresholds": {}}


def update_baseline(
    baseline_path: Path,
    classes: list[ClassMetric],
    files: list[FileMetric],
    limits: Limits | None = None,
) -> None:
    """将当前超标的类与文件作为存量基线保存."""
    cfg = limits or Limits()
    baseline_classes: dict[str, dict[str, int]] = {}
    for c in classes:
        if c.lines > cfg.max_class_lines or c.methods_count > cfg.max_class_methods:
            baseline_classes[c.key] = {
                "lines": c.lines,
                "methods": c.methods_count,
            }

    baseline_files: dict[str, dict[str, int]] = {}
    for f in files:
        if f.lines > cfg.max_file_lines:
            baseline_files[f.file_path] = {"lines": f.lines}

    data = {
        "version": "1.0",
        "thresholds": {
            "max_class_lines": cfg.max_class_lines,
            "max_class_methods": cfg.max_class_methods,
            "max_file_lines": cfg.max_file_lines,
        },
        "classes": baseline_classes,
        "files": baseline_files,
    }

    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    msg = (
        f"[INFO] 成功更新代码健康度基线: {baseline_path} "
        f"(收录 {len(baseline_classes)} 个超标类, {len(baseline_files)} 个超标文件)"
    )
    print(msg)


def _check_single_class(c: ClassMetric, baseline_classes: dict, limits: Limits) -> str | None:
    """检查单个类是否超标或恶化."""
    is_over_lines = c.lines > limits.max_class_lines
    is_over_methods = c.methods_count > limits.max_class_methods

    if not (is_over_lines or is_over_methods):
        return None

    if c.key not in baseline_classes:
        reasons = []
        if is_over_lines:
            reasons.append(f"行数 {c.lines} > 上限 {limits.max_class_lines}")
        if is_over_methods:
            reasons.append(f"方法数 {c.methods_count} > 上限 {limits.max_class_methods}")
        return (
            f"{c.file_path}:{c.lineno}: [NEW_GOD_CLASS] 类 '{c.name}' "
            f"超过设计阈值 ({', '.join(reasons)})。"
            f" 请按单一职责原则进行拆分（如分离引擎与仓储、提取规则策略或步骤流水线）。"
        )

    b_entry = baseline_classes[c.key]
    b_lines = b_entry.get("lines", 0)
    b_methods = b_entry.get("methods", 0)

    worsened = []
    if c.lines > b_lines:
        worsened.append(f"行数由基线 {b_lines} 增至 {c.lines} (+{c.lines - b_lines})")
    if c.methods_count > b_methods:
        delta = c.methods_count - b_methods
        worsened.append(f"方法数由基线 {b_methods} 增至 {c.methods_count} (+{delta})")

    if worsened:
        return (
            f"{c.file_path}:{c.lineno}: [CLASS_WORSENED] 存量类 '{c.name}' "
            f"发生恶化 ({', '.join(worsened)})。"
            f" 存量大类严禁继续追加逻辑，只允许重构缩减。"
        )
    return None


def _check_single_file(f: FileMetric, baseline_files: dict, limits: Limits) -> str | None:
    """检查单个文件是否超标或恶化."""
    if f.lines <= limits.max_file_lines:
        return None

    if f.file_path not in baseline_files:
        return (
            f"{f.file_path}:1: [FILE_TOO_LONG] 新增/非基线文件行数 {f.lines} "
            f"超过上限 {limits.max_file_lines}。请拆分为多个模块。"
        )

    b_file_lines = baseline_files[f.file_path].get("lines", 0)
    if f.lines > b_file_lines:
        delta = f.lines - b_file_lines
        return (
            f"{f.file_path}:1: [FILE_WORSENED] 存量文件行数由基线 "
            f"{b_file_lines} 膨胀至 {f.lines} (+{delta})。"
        )
    return None


def check_metrics(
    classes: list[ClassMetric],
    files: list[FileMetric],
    baseline: dict,
    limits: Limits | None = None,
) -> list[str]:
    """门禁检查：验证类和文件是否合规或恶化."""
    cfg = limits or Limits()
    errors: list[str] = []
    baseline_classes = baseline.get("classes", {})
    baseline_files = baseline.get("files", {})

    for c in classes:
        err = _check_single_class(c, baseline_classes, cfg)
        if err is not None:
            errors.append(err)

    for f in files:
        err = _check_single_file(f, baseline_files, cfg)
        if err is not None:
            errors.append(err)

    return errors


def print_stats(
    classes: list[ClassMetric],
    files: list[FileMetric],
    top_n: int = 15,
    limits: Limits | None = None,
) -> None:
    """打印当前代码库的类与文件健康度排行榜."""
    cfg = limits or Limits()
    print("=" * 80)
    print(f"代码库类健康度 TOP {top_n} 排行 (按行数降序)")
    print("=" * 80)
    sorted_classes = sorted(classes, key=lambda x: x.lines, reverse=True)
    for idx, c in enumerate(sorted_classes[:top_n], start=1):
        is_over = c.lines > cfg.max_class_lines or c.methods_count > cfg.max_class_methods
        status = "[超标]" if is_over else "[正常]"
        print(
            f"{idx:2d}. {status:<6} | {c.lines:4d} 行 | {c.methods_count:2d} 方法 | "
            f"{c.name:<32} | {c.file_path}:{c.lineno}"
        )

    print("\n" + "=" * 80)
    print(f"代码库模块文件大小 TOP {top_n} 排行")
    print("=" * 80)
    sorted_files = sorted(files, key=lambda x: x.lines, reverse=True)
    for idx, f in enumerate(sorted_files[:top_n], start=1):
        status = "[超标]" if f.lines > cfg.max_file_lines else "[正常]"
        print(f"{idx:2d}. {status:<6} | {f.lines:4d} 行 | {f.file_path}")
    print("=" * 80)


def main() -> int:
    """CLI 入口函数."""
    parser = argparse.ArgumentParser(description="Python 类与模块防膨胀检查工具（基于 AST）")
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="可选待检查文件路径。若为空则扫描整个 src 目录。",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src"),
        help="扫描的根目录（默认: src）",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help=f"基线配置文件路径（默认: {DEFAULT_BASELINE_PATH}）",
    )
    parser.add_argument(
        "--max-class-lines",
        type=int,
        default=200,
        help="单个类物理行数上限（默认: 200）",
    )
    parser.add_argument(
        "--max-class-methods",
        type=int,
        default=10,
        help="单个类方法数量上限（默认: 10）",
    )
    parser.add_argument(
        "--max-file-lines",
        type=int,
        default=400,
        help="单个文件总行数上限（默认: 400）",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="扫描全量代码并更新基线文件（用于存量初次锁定或重构后同步）",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="打印代码健康度与大类排行榜",
    )

    args = parser.parse_args()
    limits = Limits(
        max_class_lines=args.max_class_lines,
        max_class_methods=args.max_class_methods,
        max_file_lines=args.max_file_lines,
    )

    # 1. 扫描文件
    target_files = args.files if args.files else None
    if target_files:
        target_files = [f for f in target_files if str(f).startswith(str(args.root))]
        if not target_files:
            return 0

    files, classes = scan_directory(args.root, target_files=target_files)

    # 2. 如果是 stats 模式
    if args.stats:
        all_f, all_c = scan_directory(args.root)
        print_stats(all_c, all_f, limits=limits)
        return 0

    # 3. 如果是 update-baseline 模式
    if args.update_baseline:
        all_f, all_c = scan_directory(args.root)
        update_baseline(args.baseline, all_c, all_f, limits=limits)
        return 0

    # 4. 门禁检查模式
    baseline = load_baseline(args.baseline)
    errors = check_metrics(classes=classes, files=files, baseline=baseline, limits=limits)

    if errors:
        print(f"\n[ERROR] 发现 {len(errors)} 项代码结构设计超标/恶化违规：\n", file=sys.stderr)
        for err in errors:
            print(f"  * {err}", file=sys.stderr)
        tip = (
            "\n修复建议：\n"
            "  1. 避免在现有大类中继续堆砌方法与属性，通过策略模式、步骤管道或领域仓储进行拆分；\n"
            "  2. 若完成存量重构并成功缩减了规模，执行 "
            "`python scripts/lint_class_size.py --update-baseline` 同步新基线。\n"
        )
        print(tip, file=sys.stderr)
        return 1

    print(f"类与模块设计规模检查通过 (扫描 {len(files)} 个文件, {len(classes)} 个类)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
