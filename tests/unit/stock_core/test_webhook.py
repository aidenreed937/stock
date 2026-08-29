from unittest.mock import MagicMock, patch

from stock_core.utils.webhook import (
    send_dingtalk_markdown,
    send_feishu_card,
    send_webhook_alert,
    send_wecom_markdown,
)


def test_send_feishu_card_dry_run() -> None:
    res = send_feishu_card(
        "https://open.feishu.cn/mock",
        title="测试标题",
        content_md="测试正文",
        dry_run=True,
    )
    assert res is True


def test_send_wecom_markdown_dry_run() -> None:
    res = send_wecom_markdown(
        "https://qyapi.weixin.qq.com/mock",
        content_md="测试企微",
        dry_run=True,
    )
    assert res is True


def test_send_dingtalk_markdown_dry_run() -> None:
    res = send_dingtalk_markdown(
        "https://oapi.dingtalk.com/mock",
        title="测试钉钉",
        content_md="测试钉钉内容",
        dry_run=True,
    )
    assert res is True


def test_send_webhook_alert_dispatch() -> None:
    res = send_webhook_alert(
        webhook_type="feishu",
        webhook_url="https://mock",
        title="统一告警",
        content_md="内容",
        dry_run=True,
    )
    assert res is True


@patch("requests.post")
def test_send_feishu_card_network_mock(mock_post: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"code": 0, "msg": "success"}
    mock_post.return_value = mock_resp

    res = send_feishu_card(
        "https://open.feishu.cn/mock",
        title="真实网络",
        content_md="正文",
        dry_run=False,
    )
    assert res is True
    mock_post.assert_called_once()
