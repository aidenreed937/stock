"""汽车产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class NevMonthlyRecord:
    """乘联会 / 中汽协新能源汽车月度产销与渗透率记录。"""

    report_month: str
    trade_date: date
    wholesale_volume_ten_thousand: float | None = None
    total_volume_ten_thousand: float | None = None
    wholesale_volume_3mma: float | None = None
    retail_volume_ten_thousand: float | None = None
    export_volume_ten_thousand: float | None = None
    penetration_rate: float | None = None
    battery_installation_gwh: float | None = None
    yoy_growth: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    unit: str = "ten_thousand_units"
    source: str = "CPCA"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    wholesale_volume_raw: str | None = None
    total_volume_raw: str | None = None
    retail_volume_raw: str | None = None
    export_volume_raw: str | None = None
    penetration_rate_raw: str | None = None
    battery_installation_gwh_raw: str | None = None
    yoy_growth_raw: str | None = None
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""


__all__ = ["NevMonthlyRecord"]
