"""ReportRenderer 单元测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from stock.reporting.engine.renderer import ReportRenderer


def test_renderer_singleton() -> None:
    r1 = ReportRenderer.get_instance()
    r2 = ReportRenderer.get_instance()
    assert r1 is r2

    ReportRenderer.reset_instance()
    r3 = ReportRenderer.get_instance()
    assert r3 is not r1


def test_render_string_with_filters() -> None:
    renderer = ReportRenderer.get_instance()
    template = "成交: {{ amount | yi }} (环比: {{ change | pct }})"
    rendered = renderer.render_string(template, amount=15000000000, change=0.035)
    assert rendered == "成交: 150.00 亿 (环比: +3.50%)"


def test_render_template_from_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tpl_path = Path(tmpdir) / "test.md.j2"
        tpl_path.write_text("# {{ title }}\n- {{ item }}\n", encoding="utf-8")

        custom_renderer = ReportRenderer(template_dir=Path(tmpdir))
        result = custom_renderer.render("test.md.j2", title="测试报告", item="项目A")
        assert result == "# 测试报告\n- 项目A\n"
