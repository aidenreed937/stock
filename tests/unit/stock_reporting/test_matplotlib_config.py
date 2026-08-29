"""Matplotlib 统一配置测试。"""

from __future__ import annotations

import os
from pathlib import Path

from stock_reporting.core.matplotlib_config import configure_matplotlib


def test_configure_matplotlib_initialization() -> None:
    """测试 configure_matplotlib 返回可用实例并配置字体参数。"""
    mpl, plt = configure_matplotlib()

    assert mpl is not None

    assert os.environ.get("MPLCONFIGDIR") is not None
    assert Path(os.environ["MPLCONFIGDIR"]).is_absolute()
    assert plt.rcParams["axes.unicode_minus"] is False
    assert "PingFang SC" in plt.rcParams["font.sans-serif"]
    assert "DejaVu Sans" in plt.rcParams["font.sans-serif"]


def test_configure_matplotlib_render_without_warnings(tmp_path: Path) -> None:
    """测试实际图表生成不触发字体及缓存警告。"""
    _, plt = configure_matplotlib()

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.set_title("测试标题", fontsize=12, fontweight="semibold")
    ax.set_xlabel("X轴", fontsize=10)
    ax.set_ylabel("Y轴", fontsize=10)

    out_file = tmp_path / "test_render.png"
    fig.savefig(out_file)
    plt.close(fig)

    assert out_file.exists()
    assert out_file.stat().st_size > 0
