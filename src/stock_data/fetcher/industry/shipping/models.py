"""航运产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ShippingIndicesRecord:
    """全球海运与油运日频运价指数记录。"""

    trade_date: date
    bdi_index: float | None = None
    bdti_index: float | None = None
    bcti_index: float | None = None
    scfi_index: float | None = None
    bdi_ma200_bias: float | None = None
    bdti_ma200_bias: float | None = None
    unit: str = "index_points"
    source: str = "BalticExchange/SSE"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


__all__ = ["ShippingIndicesRecord"]
