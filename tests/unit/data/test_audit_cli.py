"""Audit CLI 全分支单元测试。"""

from datetime import date
from unittest.mock import patch

import polars as pl
import pytest

from stock.cli.audit import main, run_audit


def test_run_audit_dispatches_correctly() -> None:
    with (
        patch(
            "stock.data.audit.master_audit.run_master_audit", return_value={"total": 100}
        ) as mock_master,
        patch("stock.data.audit.master_audit.print_master_audit_summary"),
    ):
        res = run_audit(audit_type="master", data_source="tushare")
        mock_master.assert_called_once()
        assert res["master"] == {"total": 100}

    with patch(
        "stock.data.audit.reconciliation.run_audit", return_value={"integrity_rate": 100.0}
    ) as mock_recon:
        res = run_audit(audit_type="recon", data_source="tushare")
        mock_recon.assert_called_once()
        assert res["reconciliation"] == {"integrity_rate": 100.0}

    with patch(
        "stock.data.audit.backfill_acceptance.accept_backfill", return_value={"status": "PASSED"}
    ) as mock_acc:
        res = run_audit(audit_type="acceptance", data_source="tushare")
        mock_acc.assert_called_once_with(endpoint="stock_daily_bar", data_source="tushare")
        assert res["acceptance"] == {"status": "PASSED"}

    with (
        patch(
            "stock.data.audit.valuation_audit.run_daily_basic_audit", return_value={}
        ) as mock_val,
        patch("stock.data.audit.valuation_audit.run_sw_industry_audit", return_value={}) as mock_sw,
    ):
        res = run_audit(
            audit_type="valuation", data_source="tushare", target_date=date(2026, 8, 12)
        )
        mock_val.assert_called_once()
        mock_sw.assert_called_once()

    with (
        patch("stock.data.audit.factor_audit.run_adj_factor_audit", return_value={}) as mock_fac,
        patch("stock.data.audit.factor_audit.run_sw_daily_audit", return_value={}) as mock_sw_d,
    ):
        res = run_audit(audit_type="factor", data_source="tushare")
        mock_fac.assert_called_once()
        mock_sw_d.assert_called_once()

    with patch("stock.data.audit.moneyflow_audit.run_hk_hold_audit", return_value={}) as mock_mf:
        res = run_audit(audit_type="moneyflow", data_source="tushare")
        mock_mf.assert_called_once()

    with patch(
        "stock.data.audit.distribution_audit.run_distribution_audit", return_value={"status": "PASSED"}
    ) as mock_dist:
        res = run_audit(audit_type="distribution", data_source="tushare", dataset="sw_daily")
        mock_dist.assert_called_once_with(
            dataset_name="sw_daily", data_source="tushare", start_date=None, end_date=None
        )
        assert res["distribution"] == {"status": "PASSED"}



def test_main_cli_dispatch() -> None:
    with (
        patch("sys.argv", ["audit.py", "-t", "master", "-s", "tushare", "-d", "2026-08-12"]),
        patch("stock.cli.audit.run_audit") as mock_run,
    ):
        main()
        mock_run.assert_called_once_with(
            audit_type="master",
            data_source="tushare",
            target_date=date(2026, 8, 12),
            start_date=None,
            end_date=None,
            domain=None,
            frequency=None,
            dataset=None,
            max_workers=4,
            show_details=False,
        )


def test_main_cli_range_dispatch() -> None:
    with (
        patch(
            "sys.argv",
            [
                "audit.py",
                "-t",
                "reconciliation",
                "-s",
                "tushare",
                "--start",
                "2026-08-01",
                "--end",
                "2026-08-14",
            ],
        ),
        patch("stock.cli.audit.run_audit") as mock_run,
    ):
        main()
        mock_run.assert_called_once_with(
            audit_type="reconciliation",
            data_source="tushare",
            target_date=None,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 14),
            domain=None,
            frequency=None,
            dataset=None,
            max_workers=4,
            show_details=False,
        )


def test_main_cli_error_exit() -> None:
    with (
        patch("sys.argv", ["audit.py", "-t", "master"]),
        patch("stock.cli.audit.run_audit", side_effect=ValueError("Test Error")),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 1


def test_main_cli_exits_on_failed_audit_result() -> None:
    with (
        patch("sys.argv", ["audit.py", "-t", "acceptance"]),
        patch("stock.cli.audit.run_audit", return_value={"acceptance": {"status": "FAILED"}}),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 1


def test_main_cli_exits_on_master_audit_errors() -> None:
    result = {
        "master": pl.DataFrame(
            {
                "source": ["tushare"],
                "dataset": ["stock_daily_bar"],
                "审计错误数": [1],
            }
        )
    }
    with (
        patch("sys.argv", ["audit.py", "-t", "master"]),
        patch("stock.cli.audit.run_audit", return_value=result),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 1


def test_resolve_audit_target_date_auto() -> None:
    from stock.cli.audit import _resolve_audit_target_date

    # 1. 显式传入目标日期
    dt, is_auto = _resolve_audit_target_date("valuation", "tushare", date(2026, 8, 12))
    assert dt == date(2026, 8, 12)
    assert not is_auto

    # 2. 自动探测
    with patch("stock.data.catalog.DataCatalog.latest_trade_dates", return_value=[date(2026, 8, 11)]):
        dt_auto, is_auto2 = _resolve_audit_target_date("valuation", "tushare", None)
        assert dt_auto == date(2026, 8, 11)
        assert is_auto2
