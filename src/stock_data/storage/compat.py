"""本地存储历史数据兼容门面。"""

from stock_data.storage.compat_aliases import DatasetAliasMixin
from stock_data.storage.compat_columns import ColumnCompatMixin
from stock_data.storage.compat_frames import FrameCompatMixin
from stock_data.storage.compat_queries import QueryCompatMixin


class StorageCompat(DatasetAliasMixin, ColumnCompatMixin, FrameCompatMixin, QueryCompatMixin):
    """集中暴露存量数据兼容、格式归一与迁移辅助逻辑。"""


__all__ = ["StorageCompat"]
