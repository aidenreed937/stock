"""航运产业采集器。"""

from stock_data.fetcher.industry.shipping.collectors.akshare import (
    ShippingCollector,
    fetch_akshare_shipping_data,
)

__all__ = ["ShippingCollector", "fetch_akshare_shipping_data"]
