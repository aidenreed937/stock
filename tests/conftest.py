"""根测试配置与环境初始化。"""

from __future__ import annotations

import os
from pathlib import Path

# 确保在 pytest 测试套件运行期间，Matplotlib 缓存目录位于项目内的可写路径
if not os.environ.get("MPLCONFIGDIR"):
    mpl_cache = Path("data/.mplconfig")
    try:
        mpl_cache.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(mpl_cache.resolve())
    except OSError:
        pass
