"""Analytics 分层门禁测试。"""

import ast
from pathlib import Path

from scripts import lint_analytics_boundaries as lint


def test_plugins_forbid_high_layer_dependencies() -> None:
    assert lint.LAYER_FORBIDDEN["plugins"] == {"marts", "pipelines"}
    assert lint.LAYER_FORBIDDEN["marts"] == {"pipelines", "realtime"}


def test_hardcoded_latest_path_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.py"
    tree = ast.parse(
        'from pathlib import Path\nPath("data/analytics/market_temperature/latest/scores.json")'
    )

    violations = lint._check_hardcoded_latest_path(path, tree)

    assert len(violations) == 1
    assert "Artifact Reader" in violations[0].message


def test_configurable_artifact_root_is_allowed(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.py"
    tree = ast.parse('from pathlib import Path\nPath("data/analytics/market_temperature")')

    assert lint._check_hardcoded_latest_path(path, tree) == []
