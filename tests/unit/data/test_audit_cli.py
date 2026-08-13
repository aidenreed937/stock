"""Audit CLI 单元测试。"""

from unittest.mock import patch
from stock.cli.audit import run_audit


def test_run_audit_dispatches_correctly() -> None:
    with patch("stock.data.audit.master_audit.run_master_audit", return_value={"total": 100}) as mock_master:
        res = run_audit(audit_type="master", data_source="tushare")
        mock_master.assert_called_once()
        assert res["master"] == {"total": 100}

    with patch("stock.data.audit.reconciliation.main") as mock_recon:
        res = run_audit(audit_type="recon", data_source="tushare")
        mock_recon.assert_called_once()
        assert res["reconciliation"] == {"status": "success"}
