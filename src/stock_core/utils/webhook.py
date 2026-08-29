"""多渠道 Webhook 告警与通知工具模块。

支持：
1. 飞书机器人 (Feishu Interactive Card)；
2. 企业微信机器人 (WeCom Markdown)；
3. 钉钉机器人 (DingTalk Markdown)；
4. macOS 本地系统弹窗 (osascript)；
5. 控制台高亮输出与 dry-run 预览。
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import requests

from stock_core.utils.logger import logger


def send_macos_notification(title: str, subtitle: str, message: str) -> bool:
    """通过 macOS 系统内置 AppleScript 发送桌面原生通知。"""
    clean_msg = message.replace('"', '\\"').replace("\n", " ")
    clean_sub = subtitle.replace('"', '\\"')
    clean_title = title.replace('"', '\\"')
    script = f'display notification "{clean_msg}" with title "{clean_title}" subtitle "{clean_sub}"'
    try:
        subprocess.run(  # noqa: S603
            ["/usr/bin/osascript", "-e", script],
            check=True,
            capture_output=True,
        )
        return True
    except Exception as exc:
        logger.warning("macOS 桌面通知发送失败: %s", exc)
        return False


def send_feishu_card(
    webhook_url: str,
    *,
    title: str,
    content_md: str,
    is_alert: bool = True,
    dry_run: bool = False,
) -> bool:
    """发送飞书机器人交互式卡片消息。"""
    template_color = "red" if is_alert else "blue"
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template_color,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content_md},
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": "宏观风控量化系统 · 自动化巡检"}],
                },
            ],
        },
    }
    if dry_run:
        logger.info("[Dry-Run 飞书卡片预览]\n%s", json.dumps(payload, ensure_ascii=False, indent=2))
        return True

    try:
        resp = requests.post(webhook_url, json=payload, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0 or data.get("StatusCode") == 0:
            return True
        logger.error("飞书 Webhook 返回错误: %s", data)
        return False
    except Exception as exc:
        logger.error("飞书 Webhook 发送失败: %s", exc)
        return False


def send_wecom_markdown(
    webhook_url: str,
    *,
    content_md: str,
    dry_run: bool = False,
) -> bool:
    """发送企业微信机器人 Markdown 消息。"""
    payload: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {"content": content_md},
    }
    if dry_run:
        logger.info("[Dry-Run 企微 Markdown 预览]\n%s", content_md)
        return True

    try:
        resp = requests.post(webhook_url, json=payload, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") == 0:
            return True
        logger.error("企业微信 Webhook 返回错误: %s", data)
        return False
    except Exception as exc:
        logger.error("企业微信 Webhook 发送失败: %s", exc)
        return False


def send_dingtalk_markdown(
    webhook_url: str,
    *,
    title: str,
    content_md: str,
    dry_run: bool = False,
) -> bool:
    """发送钉钉机器人 Markdown 消息。"""
    payload: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"### {title}\n\n{content_md}",
        },
    }
    if dry_run:
        logger.info("[Dry-Run 钉钉 Markdown 预览]\n%s", content_md)
        return True

    try:
        resp = requests.post(webhook_url, json=payload, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") == 0:
            return True
        logger.error("钉钉 Webhook 返回错误: %s", data)
        return False
    except Exception as exc:
        logger.error("钉钉 Webhook 发送失败: %s", exc)
        return False


def send_webhook_alert(
    *,
    webhook_type: str,
    webhook_url: str | None = None,
    title: str,
    content_md: str,
    is_alert: bool = True,
    dry_run: bool = False,
) -> bool:
    """统一多渠道 Webhook 发送入口。

    Args:
        webhook_type: 'feishu' | 'wecom' | 'dingtalk' | 'macos' | 'none'
        webhook_url: 目标 Webhook URL (若为 macos/none 可为空)
        title: 告警标题
        content_md: Markdown 格式通知正文
        is_alert: 是否为紧急告警 (影响飞书卡片颜色等)
        dry_run: 是否为本地预览 (不发送真实网络请求)
    """
    w_type = webhook_type.lower().strip()
    if w_type == "none" or (not webhook_url and w_type not in {"macos", "dry_run"}):
        if dry_run:
            logger.info("[Dry-Run 控制台预览] %s:\n%s", title, content_md)
            return True
        return False

    if w_type == "macos":
        return send_macos_notification(title, "宏观风控信号", content_md)

    if not webhook_url:
        logger.warning("未配置 Webhook URL，跳过发送")
        return False

    if w_type == "feishu":
        return send_feishu_card(
            webhook_url, title=title, content_md=content_md, is_alert=is_alert, dry_run=dry_run
        )
    if w_type in {"wecom", "wechat"}:
        full_md = f"### {title}\n\n{content_md}"
        return send_wecom_markdown(webhook_url, content_md=full_md, dry_run=dry_run)
    if w_type == "dingtalk":
        return send_dingtalk_markdown(
            webhook_url, title=title, content_md=content_md, dry_run=dry_run
        )

    logger.warning("未知的 Webhook 类型: %s", webhook_type)
    return False


__all__ = [
    "send_dingtalk_markdown",
    "send_feishu_card",
    "send_macos_notification",
    "send_webhook_alert",
    "send_wecom_markdown",
]
