"""汽车产业数据源的在线传输客户端。"""

from stock_data.fetcher.industry.automotive.clients.cabia import CabiaOnlineClient
from stock_data.fetcher.industry.automotive.clients.cls import (
    ClsBatteryClient,
    generate_cls_sign,
)
from stock_data.fetcher.industry.automotive.clients.cpca import CpcaOnlineClient
from stock_data.fetcher.industry.automotive.clients.cpca_archive import CpcaReportArchiveClient

__all__ = [
    "CabiaOnlineClient",
    "ClsBatteryClient",
    "CpcaOnlineClient",
    "CpcaReportArchiveClient",
    "generate_cls_sign",
]
