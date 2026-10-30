"""消费产业黄金事实表转换。"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

import polars as pl

from stock_data.fetcher.industry.consumer.models import LiquorWholesaleRecord
from stock_data.fetcher.industry.consumer.schemas import LIQUOR_WHOLESALE_SCHEMA


def empty_liquor_wholesale() -> pl.DataFrame:
    """构造白酒一批价空事实表骨架。"""
    return pl.DataFrame(schema=LIQUOR_WHOLESALE_SCHEMA)


def _parse_report_date(value: str | date) -> date:
    """将白酒报告日期转换为 Curated 的自然日。"""
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def records_to_liquor_wholesale_frame(
    records: Sequence[LiquorWholesaleRecord],
) -> pl.DataFrame:
    """将白酒一批价记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_liquor_wholesale()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_date": [_parse_report_date(r.report_date) for r in records],
        "trade_date": [r.trade_date for r in records],
        "moutai_loose_price_cny": [r.moutai_loose_price_cny for r in records],
        "moutai_boxed_price_cny": [r.moutai_boxed_price_cny for r in records],
        "wuliangye_puwu_price_cny": [r.wuliangye_puwu_price_cny for r in records],
        "guojiao1573_price_cny": [r.guojiao1573_price_cny for r in records],
        "moutai_loose_price_yoy": [r.moutai_loose_price_yoy for r in records],
        "moutai_loose_price_mom": [r.moutai_loose_price_mom for r in records],
        "unit": [r.unit or "cny_per_bottle" for r in records],
        "source": [r.source or "TodayLiquorPrice" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=LIQUOR_WHOLESALE_SCHEMA)
        .unique(subset=["report_date"], keep="last")
        .sort("trade_date")
    )


def compute_liquor_price_derivatives(
    records: list[LiquorWholesaleRecord],
) -> list[LiquorWholesaleRecord]:
    """计算飞天茅台散瓶批价的 4 周环比与 52 周同比特征。"""
    updated: list[LiquorWholesaleRecord] = []
    for i, rec in enumerate(records):
        mom: float | None = None
        if (
            i >= 4
            and records[i - 4].moutai_loose_price_cny is not None
            and rec.moutai_loose_price_cny is not None
        ):
            prev_p = records[i - 4].moutai_loose_price_cny
            if prev_p and prev_p > 0:
                mom = round((rec.moutai_loose_price_cny - prev_p) / prev_p, 4)

        yoy: float | None = None
        if (
            i >= 52
            and records[i - 52].moutai_loose_price_cny is not None
            and rec.moutai_loose_price_cny is not None
        ):
            prev_y_p = records[i - 52].moutai_loose_price_cny
            if prev_y_p and prev_y_p > 0:
                yoy = round((rec.moutai_loose_price_cny - prev_y_p) / prev_y_p, 4)

        updated.append(
            LiquorWholesaleRecord(
                report_date=rec.report_date,
                trade_date=rec.trade_date,
                moutai_loose_price_cny=rec.moutai_loose_price_cny,
                moutai_boxed_price_cny=rec.moutai_boxed_price_cny,
                wuliangye_puwu_price_cny=rec.wuliangye_puwu_price_cny,
                guojiao1573_price_cny=rec.guojiao1573_price_cny,
                moutai_loose_price_yoy=yoy,
                moutai_loose_price_mom=mom,
                unit=rec.unit,
                source=rec.source,
                source_url=rec.source_url,
                release_date=rec.release_date,
                data_status=rec.data_status,
                collected_at=rec.collected_at,
            )
        )
    return updated


__all__ = [
    "compute_liquor_price_derivatives",
    "empty_liquor_wholesale",
    "records_to_liquor_wholesale_frame",
]
