"""工程机械产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ConstructionMachineryRecord:
    """工程机械行业月度产销与小松挖掘机开工小时数记录。"""

    report_month: str
    trade_date: date
    excavator_total_units: float | None = None
    excavator_domestic_units: float | None = None
    excavator_export_units: float | None = None
    komatsu_hours_china: float | None = None
    komatsu_hours_yoy: float | None = None
    export_ratio: float | None = None
    excavator_total_3mma: float | None = None
    yoy_growth: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    unit: str = "units/hours"
    source: str = "CCMA/Komatsu"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


__all__ = ["ConstructionMachineryRecord"]
