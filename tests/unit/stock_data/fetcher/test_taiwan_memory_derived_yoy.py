from datetime import date

from stock_data.fetcher.industry.semiconductor.models import TaiwanMemoryLeadRecord
from stock_data.fetcher.industry.semiconductor.transforms import (
    records_to_taiwan_memory_lead_frame,
)


def test_taiwan_memory_adds_recomputed_yoy(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_data.pipeline.normalizer.unit_normalizer.monthly_usdtwd_rate",
        lambda _month, runtime=None: 32.0,
    )
    records = [
        TaiwanMemoryLeadRecord(
            report_month=f"{2023 + index // 12:04d}-{index % 12 + 1:02d}",
            trade_date=date(2023 + index // 12, index % 12 + 1, 28),
            symbol="2408",
            company_name="南亚科技",
            revenue_ntd_thousand=1_000_000.0 if index < 12 else 1_250_000.0,
        )
        for index in range(13)
    ]

    curated = records_to_taiwan_memory_lead_frame(records)
    latest = curated.filter(curated["report_month"] == "2024-01").to_dicts()[0]

    assert latest["revenue_yoy"] is None
    assert latest["revenue_yoy_derived"] == 0.25
