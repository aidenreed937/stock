"""消费电子产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ConsumerElectronicsRecord:
    """消费电子终端季度出货与 AI 渗透率记录。"""

    report_quarter: str
    trade_date: date
    global_smartphone_shipments_million: float | None = None
    china_smartphone_shipments_million: float | None = None
    global_pc_shipments_million: float | None = None
    ai_phone_penetration_rate: float | None = None
    ai_pc_penetration_rate: float | None = None
    smartphone_yoy_growth: float | None = None
    pc_yoy_growth: float | None = None
    apple_shipments_million: float | None = None
    transsion_shipments_million: float | None = None
    unit: str = "million_units/percent"
    source: str = "IDC/Canalys"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


__all__ = ["ConsumerElectronicsRecord"]
