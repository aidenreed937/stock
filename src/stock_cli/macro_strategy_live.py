"""CLI 入口：宏观风控多策略盘尾 14:50 实时巡检与 Webhook 告警。

用法:
    # 本地预览巡检与报单卡片 (dry-run)
    uv run python -m stock_cli.macro_strategy_live --strategy macro_rotation_v4_etf --dry-run

    # 巡检并推送到飞书群机器人 (触发调仓时才推送)
    uv run python -m stock_cli.macro_strategy_live --strategy macro_rotation_v4_etf --webhook-type feishu --webhook-url "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"

    # 强制发送心跳健康通知
    uv run python -m stock_cli.macro_strategy_live --strategy macro_rotation_v6_etf --webhook-type feishu --webhook-url "https://..." --force-notify
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from stock_core.utils.logger import logger
from stock_core.utils.webhook import send_webhook_alert
from stock_strategy.macro_live import inspect_live_signal
from stock_strategy.state.signal_repo import SignalRepository


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="宏观风控多策略盘尾 14:50 实时巡检与 Webhook 自动告警工具",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="macro_rotation_v4_etf",
        help="策略名称 (默认: macro_rotation_v4_etf)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/strategy/macro_risk.yaml",
        help="策略配置文件路径 (默认: config/strategy/macro_risk.yaml)",
    )
    parser.add_argument(
        "--risk-root",
        type=str,
        default="data/analytics/macro_risk",
        help="宏观风险产物根目录 (默认: data/analytics/macro_risk)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="账户总资产人民币元 (用于计算目标金额与下单手数, 默认: 100000)",
    )
    parser.add_argument(
        "--webhook-type",
        type=str,
        choices=["feishu", "wecom", "wechat", "dingtalk", "macos", "none"],
        default="none",
        help="Webhook 告警渠道 (feishu / wecom / dingtalk / macos / none)",
    )
    parser.add_argument(
        "--webhook-url",
        type=str,
        default=None,
        help="Webhook URL (可留空，默认读取环境变量 FEISHU_WEBHOOK_URL / WECOM_WEBHOOK_URL / DINGTALK_WEBHOOK_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="本地调试预览模式，不发送真实网络告警请求",
    )
    parser.add_argument(
        "--force-notify",
        action="store_true",
        help="无调仓信号时也强制发送巡检通知 (常用于定时心跳健康检查)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_file():
        logger.error("配置文件不存在: %s", config_path)
        sys.exit(1)

    print(
        f"正在执行宏观策略盘尾实时信号推演 ({args.strategy}, 账户资产: ¥{args.capital:,.2f})...\n"
    )

    try:
        res = inspect_live_signal(
            strategy_key=args.strategy,
            config_path=config_path,
            risk_root=args.risk_root,
            total_capital=args.capital,
        )
    except Exception as exc:
        logger.error("实时巡检推演失败: %s", exc)
        sys.exit(1)

    # 控制台打印渲染卡片
    print(res.markdown_card)

    # 记录信号至 SQLite 数据库
    signal_repo = SignalRepository()
    signal_id, is_new = signal_repo.record_signal(res)
    if is_new:
        logger.info("已持久化新信号记录至 SQLite: %s", signal_id)
    else:
        logger.debug("当前信号已存在于 SQLite (幂等去重): %s", signal_id)

    # 解析 Webhook 配置
    w_type = args.webhook_type.lower()
    w_url = args.webhook_url

    # 确定是否需要发送通知
    should_send = res.has_rebalance or args.force_notify or args.dry_run
    if not should_send:
        print("💡 当前持仓正常且无调仓信号，静默跳过 Webhook 消息推送 (防止骚扰)。")
        signal_repo.record_notification(
            signal_id=signal_id,
            channel=w_type if w_type != "none" else "console",
            title="日常巡检",
            content_md=res.markdown_card,
            is_alert=False,
            sent_status="SKIPPED",
        )
        return

    if not w_url and w_type != "none":
        if w_type == "feishu":
            w_url = os.environ.get("FEISHU_WEBHOOK_URL")
        elif w_type in {"wecom", "wechat"}:
            w_url = os.environ.get("WECOM_WEBHOOK_URL")
        elif w_type == "dingtalk":
            w_url = os.environ.get("DINGTALK_WEBHOOK_URL")

    title = (
        f"🚨 宏观风控调仓指令 ({args.strategy})"
        if res.has_rebalance
        else f"📊 宏观风控日常巡检 ({args.strategy})"
    )

    if w_type != "none" or args.dry_run:
        sent = send_webhook_alert(
            webhook_type=w_type if w_type != "none" else "feishu",
            webhook_url=w_url or "https://open.feishu.cn/mock/hook",
            title=title,
            content_md=res.markdown_card,
            is_alert=res.has_rebalance,
            dry_run=args.dry_run or (w_url is None and w_type != "macos"),
        )
        status_str = "SUCCESS" if sent else ("DRY_RUN" if args.dry_run else "FAILED")
        signal_repo.record_notification(
            signal_id=signal_id,
            channel=w_type if w_type != "none" else "console",
            title=title,
            content_md=res.markdown_card,
            is_alert=res.has_rebalance,
            sent_status=status_str,
        )
        if sent and not args.dry_run:
            print(f"✅ Webhook 告警已成功推送至 [{w_type}] 并记录审计日志！")


if __name__ == "__main__":
    main()
