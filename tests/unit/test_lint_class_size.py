"""单元测试：代码健康度与类规模防膨胀检查工具 (scripts/lint_class_size.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.lint_class_size import (
    ClassMetric,
    FileMetric,
    Limits,
    analyze_file,
    check_metrics,
    load_baseline,
    update_baseline,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_analyze_file(tmp_path: Path) -> None:
    """测试 AST 分析文件并提取类与文件度量."""
    sample_code = """
class SmallService:
    def __init__(self) -> None:
        self.val = 1

    def calculate(self, x: int) -> int:
        return x + self.val

    async def fetch_async(self) -> None:
        pass
"""
    file_path = tmp_path / "sample.py"
    file_path.write_text(sample_code.strip(), encoding="utf-8")

    file_m, class_m_list = analyze_file(file_path)

    assert file_m.lines == 9
    assert len(class_m_list) == 1
    c = class_m_list[0]
    assert c.name == "SmallService"
    assert c.methods_count == 3
    assert c.lines == 9


def test_check_metrics_normal_pass() -> None:
    """测试正常未超标的类和文件检查通过."""
    classes = [
        ClassMetric(
            name="NormalClass",
            file_path="src/stock/normal.py",
            lineno=10,
            lines=50,
            methods_count=5,
        )
    ]
    files = [FileMetric(file_path="src/stock/normal.py", lines=100)]
    baseline: dict = {"classes": {}, "files": {}}
    limits = Limits(max_class_lines=200, max_class_methods=10, max_file_lines=400)

    errors = check_metrics(classes, files, baseline, limits=limits)
    assert len(errors) == 0


def test_check_metrics_new_god_class_lines_fail() -> None:
    """测试未在基线中的新类如果行数超标，被拦截并报错."""
    classes = [
        ClassMetric(
            name="GiantClass",
            file_path="src/stock/giant.py",
            lineno=1,
            lines=250,
            methods_count=5,
        )
    ]
    files = [FileMetric(file_path="src/stock/giant.py", lines=300)]
    baseline: dict = {"classes": {}, "files": {}}
    limits = Limits(max_class_lines=200, max_class_methods=10, max_file_lines=400)

    errors = check_metrics(classes, files, baseline, limits=limits)
    assert len(errors) == 1
    assert "[NEW_GOD_CLASS]" in errors[0]
    assert "GiantClass" in errors[0]
    assert "行数 250 > 上限 200" in errors[0]


def test_check_metrics_new_god_class_methods_fail() -> None:
    """测试未在基线中的新类如果方法数超标，被拦截并报错."""
    classes = [
        ClassMetric(
            name="TooManyMethodsClass",
            file_path="src/stock/methods.py",
            lineno=5,
            lines=150,
            methods_count=15,
        )
    ]
    files = [FileMetric(file_path="src/stock/methods.py", lines=200)]
    baseline: dict = {"classes": {}, "files": {}}
    limits = Limits(max_class_lines=200, max_class_methods=10, max_file_lines=400)

    errors = check_metrics(classes, files, baseline, limits=limits)
    assert len(errors) == 1
    assert "[NEW_GOD_CLASS]" in errors[0]
    assert "方法数 15 > 上限 10" in errors[0]


def test_check_metrics_baseline_exempt() -> None:
    """测试在基线中且规模未恶化的存量超标类被正常豁免."""
    classes = [
        ClassMetric(
            name="LegacyClass",
            file_path="src/stock/legacy.py",
            lineno=1,
            lines=300,
            methods_count=12,
        )
    ]
    files = [FileMetric(file_path="src/stock/legacy.py", lines=500)]
    baseline = {
        "classes": {"src/stock/legacy.py::LegacyClass": {"lines": 300, "methods": 12}},
        "files": {"src/stock/legacy.py": {"lines": 500}},
    }
    limits = Limits(max_class_lines=200, max_class_methods=10, max_file_lines=400)

    errors = check_metrics(classes, files, baseline, limits=limits)
    assert len(errors) == 0


def test_check_metrics_baseline_worsened_fail() -> None:
    """测试基线中的存量类如果行数或方法数进一步恶化，被拦截并报错."""
    classes = [
        ClassMetric(
            name="LegacyClass",
            file_path="src/stock/legacy.py",
            lineno=1,
            lines=320,  # 基线是 300，恶化 +20
            methods_count=14,  # 基线是 12，恶化 +2
        )
    ]
    files = [FileMetric(file_path="src/stock/legacy.py", lines=550)]
    baseline = {
        "classes": {"src/stock/legacy.py::LegacyClass": {"lines": 300, "methods": 12}},
        "files": {"src/stock/legacy.py": {"lines": 500}},
    }
    limits = Limits(max_class_lines=200, max_class_methods=10, max_file_lines=400)

    errors = check_metrics(classes, files, baseline, limits=limits)
    assert len(errors) == 2
    assert any("[CLASS_WORSENED]" in e and "由基线 300 增至 320" in e for e in errors)
    assert any("[FILE_WORSENED]" in e and "由基线 500 膨胀至 550" in e for e in errors)


def test_check_metrics_new_file_too_long() -> None:
    """测试未在基线中的新文件若行数超标，被拦截并报错."""
    classes = []
    files = [FileMetric(file_path="src/stock/new_huge.py", lines=450)]
    baseline = {"classes": {}, "files": {}}
    limits = Limits(max_class_lines=200, max_class_methods=10, max_file_lines=400)

    errors = check_metrics(classes, files, baseline, limits=limits)
    assert len(errors) == 1
    assert "[FILE_TOO_LONG]" in errors[0]
    assert "src/stock/new_huge.py" in errors[0]


def test_update_and_load_baseline(tmp_path: Path) -> None:
    """测试更新基线文件与加载基线数据."""
    baseline_file = tmp_path / "test_baseline.json"
    classes = [
        ClassMetric(
            name="OverClass",
            file_path="src/stock/over.py",
            lineno=10,
            lines=250,
            methods_count=12,
        ),
        ClassMetric(
            name="NormalClass",
            file_path="src/stock/normal.py",
            lineno=1,
            lines=80,
            methods_count=3,
        ),
    ]
    files = [
        FileMetric(file_path="src/stock/over.py", lines=450),
        FileMetric(file_path="src/stock/normal.py", lines=100),
    ]
    limits = Limits(max_class_lines=200, max_class_methods=10, max_file_lines=400)

    update_baseline(baseline_file, classes, files, limits=limits)

    assert baseline_file.exists()
    loaded = load_baseline(baseline_file)
    assert "src/stock/over.py::OverClass" in loaded["classes"]
    assert loaded["classes"]["src/stock/over.py::OverClass"]["lines"] == 250
    assert "src/stock/normal.py::NormalClass" not in loaded["classes"]
    assert "src/stock/over.py" in loaded["files"]
    assert "src/stock/normal.py" not in loaded["files"]
