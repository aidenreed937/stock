"""Matplotlib 统一配置与安全初始化模块。

确保在沙箱环境或无写权限环境中正确配置 MPLCONFIGDIR 缓存目录，
设置非交互式 Agg 后端，并统一配置跨平台中文字体回退链与字重。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_DEFAULT_CHINESE_FONTS: list[str] = [
    "PingFang SC",
    "Hiragino Sans GB",
    "Heiti SC",
    "STHeiti",
    "Microsoft YaHei",
    "SimHei",
    "Arial Unicode MS",
    "DejaVu Sans",
]


def configure_matplotlib() -> tuple[Any, Any]:
    """安全初始化 Matplotlib 环境、后端与字体配置。

    Returns:
        tuple[module, module]: (matplotlib, matplotlib.pyplot)
    """
    if not os.environ.get("MPLCONFIGDIR"):
        cache_dir = Path("data/.mplconfig")
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            os.environ["MPLCONFIGDIR"] = str(cache_dir.resolve())
        except OSError:
            # 在极其严苛的只读环境下优雅降级到系统临时目录
            import tempfile

            temp_cache = Path(tempfile.gettempdir()) / "mplconfig"
            temp_cache.mkdir(parents=True, exist_ok=True)
            os.environ["MPLCONFIGDIR"] = str(temp_cache.resolve())

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = _DEFAULT_CHINESE_FONTS
    plt.rcParams["axes.unicode_minus"] = False

    return matplotlib, plt


__all__ = ["configure_matplotlib"]
