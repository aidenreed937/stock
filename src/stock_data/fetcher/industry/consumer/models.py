"""消费产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class LiquorWholesaleRecord:
    """高端名优白酒周度一批价与动销监测记录。"""

    report_date: str
    trade_date: date
    moutai_loose_price_cny: float | None = None
    moutai_boxed_price_cny: float | None = None
    wuliangye_puwu_price_cny: float | None = None
    guojiao1573_price_cny: float | None = None
    moutai_loose_price_yoy: float | None = None
    moutai_loose_price_mom: float | None = None
    unit: str = "cny_per_bottle"
    source: str = "TodayLiquorPrice"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""


__all__ = ["LiquorWholesaleRecord"]
