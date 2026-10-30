"""有色金属产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class NonFerrousMetalsRecord:
    """有色大宗金属价格与显性库存记录。"""

    report_date: str
    trade_date: date
    lithium_carbonate_price: float | None = None
    shfe_copper_price: float | None = None
    shfe_aluminum_price: float | None = None
    sge_gold_price: float | None = None
    copper_inventory_ton: float | None = None
    unit: str = "mixed"
    source: str = "AkShare"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


__all__ = ["NonFerrousMetalsRecord"]
