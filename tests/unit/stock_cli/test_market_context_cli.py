"""市场分析上下文 CLI 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock_cli import market_context


def test_market_context_cli_outputs_compact_json(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    context = MagicMock()
    context.query.return_value = {
        "as_of_date": "2026-08-21",
        "run_id": "run_test",
        "current": {"composite": {"temperature": 42.0}},
    }
    loader = MagicMock(return_value=context)
    monkeypatch.setattr(market_context.MarketAnalysisContext, "load", loader)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stock_cli.market_context",
            "--artifact-root",
            str(Path("tmp/analytics")),
            "--questions",
            "overview,trend",
        ],
    )

    market_context.main()

    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "run_test"
    loader.assert_called_once()
    context.query.assert_called_once_with(("overview", "trend"), compare_date=None)
