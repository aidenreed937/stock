#!/usr/bin/env python3
"""系统运行资源监控与性能阻塞诊断脚本 (Resource & Performance Monitor).

实时监控 Python 核心程序、CLI 回填与测试任务的 CPU、内存、I/O 占用，
并基于阈值规则引擎检测是否存在高负载、内存膨胀、I/O 停滞或潜在死锁阻塞。
"""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SystemMetrics:
    """系统整机资源指标."""

    cpu_count: int = 1
    load_1m: float = 0.0
    load_5m: float = 0.0
    load_15m: float = 0.0
    cpu_percent: float = 0.0
    mem_total_gb: float = 0.0
    mem_used_gb: float = 0.0
    mem_free_gb: float = 0.0
    mem_percent: float = 0.0


@dataclass
class ProcessMetrics:
    """单个相关进程资源指标."""

    pid: int
    name: str
    cmdline: str
    cpu_percent: float = 0.0
    mem_rss_mb: float = 0.0
    mem_percent: float = 0.0
    status: str = "R"
    elapsed_time: str = "00:00"


@dataclass
class HealthIssue:
    """健康与性能诊断项."""

    level: str  # OK, WARNING, CRITICAL
    category: str  # CPU, MEMORY, IO_STALL, PROCESS
    message: str
    suggestion: str = ""


def _parse_darwin_mem() -> tuple[float, float, float, float]:
    """解析 macOS vm_stat 内存输出."""
    try:
        vm = subprocess.check_output(["/usr/bin/vm_stat"], text=True)
        page_size = 4096
        for line in vm.splitlines():
            if "page size of" in line:
                m = re.search(r"(\d+)", line)
                if m:
                    page_size = int(m.group(1))
                break

        vm_dict: dict[str, float] = {}
        for line in vm.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                v_clean = v.strip().replace(".", "")
                if v_clean.isdigit():
                    vm_dict[k.strip()] = int(v_clean) * page_size / (1024 * 1024)

        free_mb = vm_dict.get("Pages free", 0) + vm_dict.get("Pages speculative", 0)
        inactive_mb = vm_dict.get("Pages inactive", 0)
        active_mb = vm_dict.get("Pages active", 0)
        wired_mb = vm_dict.get("Pages wired down", 0)
        compressed_mb = vm_dict.get("Pages occupied by compressor", 0)

        used_mb = active_mb + wired_mb + compressed_mb
        total_mb = used_mb + free_mb + inactive_mb
        pct = (used_mb / total_mb) * 100 if total_mb > 0 else 0.0
        return total_mb / 1024, used_mb / 1024, (free_mb + inactive_mb) / 1024, pct
    except Exception:
        return 0.0, 0.0, 0.0, 0.0


def _parse_linux_mem() -> tuple[float, float, float, float]:
    """解析 Linux /proc/meminfo 内存输出."""
    try:
        meminfo = Path("/proc/meminfo").read_text()
        m_tot = re.search(r"MemTotal:\s+(\d+)", meminfo)
        m_avl = re.search(r"MemAvailable:\s+(\d+)", meminfo)
        if not m_tot or not m_avl:
            return 0.0, 0.0, 0.0, 0.0
        tot_kb, avl_kb = int(m_tot.group(1)), int(m_avl.group(1))
        used_kb = tot_kb - avl_kb
        pct = (used_kb / tot_kb) * 100 if tot_kb > 0 else 0.0
        scale = 1024 * 1024
        return tot_kb / scale, used_kb / scale, avl_kb / scale, pct
    except Exception:
        return 0.0, 0.0, 0.0, 0.0


def _get_cgroup_cpu_count(physical_count: int) -> int:
    """获取容器 cgroup 限制下的实际有效 CPU 核心数."""
    with contextlib.suppress(Exception):
        # Cgroup V2
        cgroup_v2_max = Path("/sys/fs/cgroup/cpu.max")
        if cgroup_v2_max.exists():
            parts = cgroup_v2_max.read_text().strip().split()
            if parts[0] != "max":
                return min(physical_count, math.ceil(int(parts[0]) / int(parts[1])))
        # Cgroup V1
        cgroup_v1_quota = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        cgroup_v1_period = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if cgroup_v1_quota.exists() and cgroup_v1_period.exists():
            quota = int(cgroup_v1_quota.read_text().strip())
            period = int(cgroup_v1_period.read_text().strip())
            if quota > 0 and period > 0:
                return min(physical_count, math.ceil(quota / period))
    return physical_count


def collect_system_metrics() -> SystemMetrics:
    """采集系统整体 CPU 与内存指标（兼容 macOS 与 Linux）."""
    physical_cpus = os.cpu_count() or 1
    metrics = SystemMetrics(cpu_count=_get_cgroup_cpu_count(physical_cpus))

    with contextlib.suppress(Exception):
        l1, l5, l15 = os.getloadavg()
        metrics.load_1m = round(l1, 2)
        metrics.load_5m = round(l5, 2)
        metrics.load_15m = round(l15, 2)
        metrics.cpu_percent = round(min(100.0, (l1 / metrics.cpu_count) * 100), 1)

    if sys.platform == "darwin":
        tot, used, free, pct = _parse_darwin_mem()
    elif sys.platform.startswith("linux"):
        tot, used, free, pct = _parse_linux_mem()
    else:
        tot, used, free, pct = 0.0, 0.0, 0.0, 0.0

    metrics.mem_total_gb, metrics.mem_used_gb = round(tot, 2), round(used, 2)
    metrics.mem_free_gb, metrics.mem_percent = round(free, 2), round(pct, 1)
    return metrics


def _parse_proc_line(line: str, my_pid: int) -> ProcessMetrics | None:
    """解析单行 ps 进程信息."""
    parts = line.strip().split(None, 6)
    if len(parts) < 7:
        return None
    pid_str, cpu_str, mem_str, rss_str, stat, el_time, cmd = parts
    if not pid_str.isdigit():
        return None
    pid = int(pid_str)
    if pid == my_pid:
        return None

    keywords = ["stock", "backfill", "pytest", "master_audit", "reconciliation"]
    if not any(kw in cmd for kw in keywords) or not any(
        kw in cmd for kw in ["python", "uv", "pytest"]
    ):
        return None

    name = Path(cmd.split()[0]).name
    rss_mb = float(rss_str) / 1024 if rss_str.isdigit() else 0.0
    return ProcessMetrics(
        pid=pid,
        name=name,
        cmdline=cmd,
        cpu_percent=float(cpu_str) if cpu_str.replace(".", "").isdigit() else 0.0,
        mem_rss_mb=round(rss_mb, 1),
        mem_percent=float(mem_str) if mem_str.replace(".", "").isdigit() else 0.0,
        status=stat,
        elapsed_time=el_time,
    )


def collect_project_processes() -> list[ProcessMetrics]:
    """收集当前与量化系统相关的 Python/CLI 进程状态."""
    results: list[ProcessMetrics] = []
    my_pid = os.getpid()

    with contextlib.suppress(Exception):
        ps_cmd = shutil.which("ps") or "/bin/ps"
        out = subprocess.check_output(  # noqa: S603
            [ps_cmd, "-eo", "pid,%cpu,%mem,rss,stat,time,command"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines()[1:]:
            item = _parse_proc_line(line, my_pid)
            if item is not None:
                results.append(item)

    return sorted(results, key=lambda x: x.mem_rss_mb, reverse=True)


def _check_system_issues(sys_metrics: SystemMetrics) -> list[HealthIssue]:
    """诊断系统级 CPU 与内存健康."""
    issues: list[HealthIssue] = []
    load_ratio = sys_metrics.load_1m / sys_metrics.cpu_count if sys_metrics.cpu_count > 0 else 0.0
    if load_ratio >= 1.0:
        issues.append(
            HealthIssue(
                level="CRITICAL",
                category="CPU",
                message=f"CPU负载 ({sys_metrics.load_1m}) 超过核心数 ({sys_metrics.cpu_count})",
                suggestion="任务存在 CPU 争抢，建议调小 Makefile 中的 MAX_WORKERS",
            )
        )
    elif load_ratio >= 0.8:
        issues.append(
            HealthIssue(
                level="WARNING",
                category="CPU",
                message=f"CPU 1分钟负载率偏高 ({load_ratio * 100:.1f}%)",
                suggestion="系统处于高负载计算状态，注意观察并发稳定性",
            )
        )

    if sys_metrics.mem_percent >= 90.0:
        issues.append(
            HealthIssue(
                level="CRITICAL",
                category="MEMORY",
                message=f"物理内存使用率达到 {sys_metrics.mem_percent}%",
                suggestion="面临 OOM 风险，建议开启 DuckDB/RAW 攒批微批处理",
            )
        )
    elif sys_metrics.mem_percent >= 80.0:
        issues.append(
            HealthIssue(
                level="WARNING",
                category="MEMORY",
                message=f"系统内存使用率偏高 ({sys_metrics.mem_percent}%)",
                suggestion="建议避免同时启动过多全量回填进程",
            )
        )
    return issues


def _check_process_issues(procs: list[ProcessMetrics]) -> list[HealthIssue]:
    """诊断各进程异常状态与死锁/挂起风险."""
    issues: list[HealthIssue] = []
    for p in procs:
        if p.mem_rss_mb > 2048.0:
            issues.append(
                HealthIssue(
                    level="CRITICAL",
                    category="PROCESS",
                    message=f"进程 [PID {p.pid}] 内存过高 ({p.mem_rss_mb:.1f} MB)",
                    suggestion="检查是否存在单次读取超大 Parquet 数据帧未释放",
                )
            )
        if "D" in p.status:
            issues.append(
                HealthIssue(
                    level="CRITICAL",
                    category="IO_STALL",
                    message=f"进程 [PID {p.pid}] 处于 D 状态 (不可中断睡眠)，疑似 I/O 挂起",
                    suggestion="检查目标存储磁盘健康度、网络连通性或 API 连接",
                )
            )
    return issues


def render_report(sys_metrics: SystemMetrics, procs: list[ProcessMetrics]) -> None:
    """渲染格式化终端看板与诊断报告."""
    issues = _check_system_issues(sys_metrics) + _check_process_issues(procs)

    print("\n" + "=" * 80)
    print(" 📊 量化系统运行性能与资源占用诊断报告 (Resource Health Monitor)")
    print("=" * 80)

    status_icon = "🟢 正常"
    if any(i.level == "CRITICAL" for i in issues):
        status_icon = "🔴 严重告警"
    elif any(i.level == "WARNING" for i in issues):
        status_icon = "🟡 存在预警"

    print(f"\n[整机综合健康度]: {status_icon}")
    print(
        f"  - CPU 核心: {sys_metrics.cpu_count} 核  | 负载 (1m/5m/15m): "
        f"{sys_metrics.load_1m} / {sys_metrics.load_5m} / {sys_metrics.load_15m} "
        f"({sys_metrics.cpu_percent:.1f}% 饱和度)"
    )
    print(
        f"  - 物理内存: 总计 {sys_metrics.mem_total_gb:.2f} GB | 已用: "
        f"{sys_metrics.mem_used_gb:.2f} GB ({sys_metrics.mem_percent}%) | "
        f"可用: {sys_metrics.mem_free_gb:.2f} GB"
    )

    print("\n[当前运行中的核心任务/CLI 进程]:")
    if not procs:
        print("  (当前无活跃的 stock/backfill/pytest 业务进程)")
    else:
        print(
            f"  {'PID':<7} {'状态':<5} {'CPU%':<7} {'内存(MB)':<10} {'运行时长':<12} {'命令详情'}"
        )
        print("  " + "-" * 78)
        for p in procs:
            cmd_short = (p.cmdline[:45] + "...") if len(p.cmdline) > 48 else p.cmdline
            print(
                f"  {p.pid:<7} {p.status:<5} {p.cpu_percent:<7.1f} {p.mem_rss_mb:<10.1f} "
                f"{p.elapsed_time:<12} {cmd_short}"
            )

    print("\n[性能诊断与异常预警分析]:")
    if not issues:
        print("  ✅ 未检测到任何 CPU 争抢、内存泄漏或 I/O 阻塞异常，系统运行状态优良。")
    else:
        for issue in issues:
            print(f"  ! [{issue.level:<8}] ({issue.category}) {issue.message}")
            if issue.suggestion:
                print(f"                 ↳ 建议: {issue.suggestion}")

    print("=" * 80 + "\n")


def main() -> None:
    """主入口点，支持单次快照与持续轮询监控."""
    parser = argparse.ArgumentParser(description="系统资源占用与阻塞性能监控工具")
    parser.add_argument("--watch", "-w", action="store_true", help="开启循环持续监控模式")
    parser.add_argument("--interval", "-i", type=int, default=3, help="监控刷新间隔秒数 (默认 3s)")
    args = parser.parse_args()

    try:
        while True:
            sys_m = collect_system_metrics()
            procs = collect_project_processes()
            render_report(sys_m, procs)

            if not args.watch:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已退出资源监控。")


if __name__ == "__main__":
    main()
