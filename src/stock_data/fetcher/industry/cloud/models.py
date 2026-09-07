"""云计算产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CloudCapexRecord:
    """北美四大云厂商季度 AI 资本开支记录。"""

    report_quarter: str
    trade_date: date
    total_capex_billion_usd: float | None
    msft_capex_billion_usd: float | None = None
    goog_capex_billion_usd: float | None = None
    meta_capex_billion_usd: float | None = None
    amzn_capex_billion_usd: float | None = None
    yoy_growth: float | None = None
    qoq_growth: float | None = None
    unit: str = "billion_usd"
    source: str = "Company Filings (10-Q/10-K)"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    msft_capex_raw: str | None = None
    goog_capex_raw: str | None = None
    meta_capex_raw: str | None = None
    amzn_capex_raw: str | None = None
    msft_release_date: date | None = None
    goog_release_date: date | None = None
    meta_release_date: date | None = None
    amzn_release_date: date | None = None


__all__ = ["CloudCapexRecord"]
