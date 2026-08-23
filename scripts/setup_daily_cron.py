"""每日盘后自动复盘定时任务配置工具 (支持 macOS launchd 与 crontab)。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

LAUNCHD_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.stock.daily.review</string>
    <key>WorkingDirectory</key>
    <string>{workspace_dir}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/make</string>
        <string>daily-review</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>30</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>{workspace_dir}/data/logs/daily_review.log</string>
    <key>StandardErrorPath</key>
    <string>{workspace_dir}/data/logs/daily_review_err.log</string>
</dict>
</plist>
"""


def install_launchd(workspace_dir: Path) -> Path:
    agents_dir = Path(os.path.expanduser("~/Library/LaunchAgents"))
    agents_dir.mkdir(parents=True, exist_ok=True)
    log_dir = workspace_dir / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    plist_path = agents_dir / "com.stock.daily.review.plist"
    content = LAUNCHD_PLIST_TEMPLATE.format(workspace_dir=str(workspace_dir.resolve()))
    with open(plist_path, "w", encoding="utf-8") as f:
        f.write(content)
    return plist_path


def main() -> None:
    parser = argparse.ArgumentParser(description="每日 15:30 自动复盘定时任务配置工具")
    parser.add_argument(
        "--action",
        choices=["install", "uninstall", "status"],
        default="status",
        help="操作: install (安装 launchd 任务), uninstall (卸载), status (查看状态)",
    )
    args = parser.parse_args()

    ws = Path.cwd()
    plist_path = Path(os.path.expanduser("~/Library/LaunchAgents/com.stock.daily.review.plist"))

    if args.action == "install":
        p = install_launchd(ws)
        sys.stdout.write(f"已生成 launchd 定时配置: {p}\n")
        sys.stdout.write("运行以下命令激活定时任务:\n")
        sys.stdout.write(f"  launchctl load {p}\n")
    elif args.action == "uninstall":
        if plist_path.exists():
            plist_path.unlink()
            sys.stdout.write(f"已移除 launchd 配置: {plist_path}\n")
            sys.stdout.write(f"请执行: launchctl unload {plist_path}\n")
        else:
            sys.stdout.write("未找到已安装的定时任务。\n")
    else:
        status_str = "已安装" if plist_path.exists() else "未安装"
        sys.stdout.write(f"每日 15:30 复盘定时任务状态: {status_str} ({plist_path})\n")


if __name__ == "__main__":
    main()
