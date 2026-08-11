"""全局常量定义模块，消除魔数与散落硬编码。"""

from typing import Final

# 默认技术指标周期
DEFAULT_SMA_WINDOW: Final[int] = 5
DEFAULT_EMA_WINDOW: Final[int] = 12
DEFAULT_RSI_WINDOW: Final[int] = 14

# 存储层与路径相关常量
DEFAULT_PARQUET_SUBDIR: Final[str] = "parquet"

# 模拟数据源随机种子
DEFAULT_RANDOM_SEED: Final[int] = 42
