from pathlib import Path

from stock_strategy.industry.audit import (
    load_macro_regimes,
    load_stress_tests,
    run_industry_strategy_audit,
)


def test_load_regimes_and_stress() -> None:
    regimes = load_macro_regimes()
    assert len(regimes) == 6

    stress = load_stress_tests()
    assert len(stress) == 4


def test_run_industry_strategy_audit_runs(tmp_path: Path) -> None:
    res = run_industry_strategy_audit(
        output_dir=tmp_path,
        assert_guardrails=False,
    )
    assert not res["regime_df"].empty
    assert not res["stress_df"].empty
    assert Path(res["report_markdown"]).exists()
    assert Path(res["chart_png"]).exists()
