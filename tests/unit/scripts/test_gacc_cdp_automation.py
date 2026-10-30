"""GACC CDP 自动化脚本单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from scripts.cdp.gacc_cdp_automation import (
    CdpClient,
    fill_gacc_form,
    is_port_open,
    read_query_codes,
)


def test_read_query_codes_from_workspace() -> None:
    """验证从真实仓库读取查询税号清单。"""
    path = Path("config/data/customs/gacc_query_codes.txt")
    if not path.exists():
        pytest.skip("gacc_query_codes.txt 不存在")
    codes_str = read_query_codes(path)
    assert codes_str
    codes = [c.strip() for c in codes_str.split(",") if c.strip()]
    assert len(codes) > 500
    for code in codes:
        assert len(code) == 8
        assert code.isdigit()


def test_read_query_codes_invalid_path(tmp_path: Path) -> None:
    """验证无效文件路径抛出异常。"""
    dummy = tmp_path / "non_existent.txt"
    with pytest.raises(FileNotFoundError):
        read_query_codes(dummy)

    empty = tmp_path / "empty.txt"
    empty.write_text("=== Header ===\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未在文件中找到逗号分隔"):
        read_query_codes(empty)


def test_is_port_open_mock() -> None:
    """验证端口健康检查逻辑。"""
    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_open.return_value = mock_resp
        assert is_port_open(9222) is True

    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        assert is_port_open(9222) is False


def test_fill_gacc_form() -> None:
    """验证表单注入与求值调用（支持半年度范围）。"""
    mock_client = MagicMock(spec=CdpClient)
    mock_client.evaluate.return_value = {
        "status": "success",
        "start_month": "1",
        "end_month": "6",
        "logs": ["已选择: 出口", "已选择: 美元", "已默认设置半年范围: 1 至 6 月"],
    }

    # 默认半年 1-6 月
    result = fill_gacc_form(mock_client, "12345678,87654321", 2025)
    assert result["status"] == "success"
    assert result["start_month"] == "1"
    assert result["end_month"] == "6"
    assert "已选择: 出口" in result["logs"]
    mock_client.evaluate.assert_called_once()

    # 指定下半年 7-12 月
    mock_client.evaluate.reset_mock()
    mock_client.evaluate.return_value = {
        "status": "success",
        "start_month": "7",
        "end_month": "12",
        "logs": ["已默认设置半年范围: 7 至 12 月"],
    }
    result_h2 = fill_gacc_form(mock_client, "12345678,87654321", 2025, 7, 12)
    assert result_h2["start_month"] == "7"
    assert result_h2["end_month"] == "12"
    mock_client.evaluate.assert_called_once()


def test_resolve_task_specific_filename(tmp_path: Path) -> None:
    """验证根据任务特性重命名导出文件。"""
    from scripts.cdp.gacc_cdp_automation import resolve_task_specific_filename

    csv_file = tmp_path / "数据导出.csv"
    csv_file.write_text(
        '"数据年月","商品编码","美元"\n"202501","13021910","100"\n"202506","13021910","200"\n',
        encoding="gb18030",
    )

    renamed = resolve_task_specific_filename(csv_file, 2025, 1, 6, "export", "usd")
    assert not csv_file.exists()
    assert renamed.exists()
    assert renamed.name.startswith("gacc_export_usd_202501_202506_monthly_")
    assert renamed.name.endswith(".csv")


def test_detect_captcha_dialog() -> None:
    """验证滑块验证码弹窗检测逻辑。"""
    from scripts.cdp.gacc_cdp_automation import detect_captcha_dialog

    mock_client = MagicMock(spec=CdpClient)
    mock_client.evaluate.return_value = True
    assert detect_captcha_dialog(mock_client) is True

    mock_client.evaluate.return_value = False
    assert detect_captcha_dialog(mock_client) is False


def test_detect_query_results_ready() -> None:
    """验证数据检索结果就绪检测逻辑。"""
    from scripts.cdp.gacc_cdp_automation import detect_query_results_ready

    mock_client = MagicMock(spec=CdpClient)
    # 未就绪状态
    mock_client.evaluate.return_value = {
        "ready": False,
        "total_size": 0,
        "in_result_page": False,
        "has_loading": True,
    }
    res = detect_query_results_ready(mock_client)
    assert res["ready"] is False
    assert res["total_size"] == 0

    # 渲染完成状态
    mock_client.evaluate.return_value = {
        "ready": True,
        "total_size": 5221,
        "in_result_page": True,
        "has_loading": False,
    }
    res_ready = detect_query_results_ready(mock_client)
    assert res_ready["ready"] is True
    assert res_ready["total_size"] == 5221


def test_dismiss_historical_notice() -> None:
    """验证非近期历史数据提示框自动确认逻辑。"""
    from scripts.cdp.gacc_cdp_automation import dismiss_historical_notice

    mock_client = MagicMock(spec=CdpClient)
    mock_client.evaluate.return_value = True
    assert dismiss_historical_notice(mock_client) is True

    mock_client.evaluate.return_value = False
    assert dismiss_historical_notice(mock_client) is False


def test_trigger_result_export_and_confirm() -> None:
    """验证结果页导出触发与确认弹窗逻辑。"""
    from scripts.cdp.gacc_cdp_automation import (
        dismiss_export_confirm_dialog,
        trigger_result_export,
    )

    mock_client = MagicMock(spec=CdpClient)
    mock_client.evaluate.return_value = True
    assert trigger_result_export(mock_client) is True
    assert dismiss_export_confirm_dialog(mock_client) is True

    mock_client.evaluate.return_value = False
    assert trigger_result_export(mock_client) is False
    assert dismiss_export_confirm_dialog(mock_client) is False
