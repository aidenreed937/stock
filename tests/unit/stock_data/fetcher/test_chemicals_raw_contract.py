"""化工产业端点 RAW/Curated 两层落盘契约测试。"""

from datetime import date

import polars as pl

from stock_data.fetcher.industry.chemicals import (
    ChemicalMarketRecord,
    records_to_chemical_market_frame,
    records_to_raw_chemical_market_frame,
)
from stock_data.fetcher.industry.chemicals.collectors.futures_hold_rank import (
    build_hold_rank_curated_frame,
)
from stock_data.fetcher.industry.chemicals.collectors.inventory import (
    FUTURES_INVENTORY_SCHEMA,
    build_futures_inventory_curated_frame,
    build_futures_inventory_raw_frame,
)
from stock_data.fetcher.industry.chemicals.collectors.market import ChemicalsCollector
from stock_data.fetcher.industry.chemicals.registry import ENDPOINT_SPECS
from stock_data.fetcher.industry.chemicals.schemas import HOLD_RANK_RAW_SCHEMA
from stock_data.fetcher.industry.contracts import IndustryFrameResult, IndustryRunContext
from stock_data.fetcher.industry.runner import frame_endpoint, record_endpoint, run_endpoint


def test_chemical_endpoints_declare_shared_raw_subdir() -> None:
    assert all(spec.raw_subdir == "chemicals" for spec in ENDPOINT_SPECS)


def test_chemical_market_raw_transform_keeps_source_fields_separate(tmp_path) -> None:
    record = ChemicalMarketRecord(
        report_month="2026-08",
        trade_date=date(2026, 8, 31),
        soda_ash_production=289.0,
        release_date=date(2026, 9, 18),
        raw_content_sha256="sha-chemical",
        raw_snapshot_path="chemicals/100ppi/mdi.html",
    )
    spec = record_endpoint(
        endpoint="chemical_market",
        domain="chemicals",
        collect=lambda _raw_dir, _force: [record],
        raw_transform=records_to_raw_chemical_market_frame,
        transform=records_to_chemical_market_frame,
        target_file="chemical_market.parquet",
        primary_keys=["report_month"],
        raw_subdir="chemicals",
    )

    run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
        ),
    )

    raw = pl.read_parquet(tmp_path / "raw" / "chemicals" / "chemical_market.parquet")
    curated = pl.read_parquet(tmp_path / "curated" / "chemical_market.parquet")
    assert "soda_ash_production_raw" in raw.columns
    assert "soda_ash_production" not in raw.columns
    assert raw["raw_content_sha256"][0] == "sha-chemical"
    assert "soda_ash_production" in curated.columns
    assert "raw_content_sha256" not in curated.columns


def test_futures_inventory_raw_transform_roundtrip(tmp_path) -> None:
    frame = pl.DataFrame(
        [
            {
                "symbol": "SA",
                "name": "纯碱",
                "industry_code": "220200",
                "trade_date": date(2026, 8, 31),
                "inventory": 7013.0,
                "change": -1037.0,
                "unit": "contracts",
                "source": "Eastmoney/CZCE/DCE",
                "source_url": "https://data.eastmoney.com/ifdata/kcsj.html",
                "release_date": date(2026, 8, 31),
                "collected_at": "2026-09-01T00:00:00Z",
            }
        ],
        schema=FUTURES_INVENTORY_SCHEMA,
    )
    raw = build_futures_inventory_raw_frame(frame)
    curated = build_futures_inventory_curated_frame(raw)
    assert raw.schema["inventory_raw"] == pl.String
    assert "inventory" not in raw.columns
    assert curated["inventory"][0] == 7013.0
    assert curated["change"][0] == -1037.0


def test_frame_endpoint_propagates_partial_collection_status(tmp_path) -> None:
    frame = pl.DataFrame({"trade_date": [date(2026, 8, 31)], "value": [1.0]})
    spec = frame_endpoint(
        endpoint="chemical_inventory_status",
        domain="chemicals",
        context_collect=lambda _context: IndustryFrameResult(
            frame=frame,
            status="PARTIAL",
            missing_periods=("SA:2026-08-28..2026-08-28",),
            errors=("source timeout",),
        ),
        transform=lambda value: value,
        target_file="chemical_inventory_status.parquet",
        primary_keys=["trade_date"],
    )

    result = run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
        ),
    )

    assert result.status == "PARTIAL"
    assert result.missing_periods == ("SA:2026-08-28..2026-08-28",)
    assert result.errors == ("source timeout",)


def test_hold_rank_curated_frame_derives_from_raw_rows() -> None:
    raw = pl.DataFrame(
        [
            {
                "trade_date": date(2026, 8, 31),
                "symbol": "SA",
                "name": "纯碱",
                "contract": "SA2609",
                "side": "long",
                "member_name_raw": "席位A",
                "position_volume_raw": "100",
                "source": "Sina_Exchange_Hold_Rank",
                "release_date": date(2026, 8, 31),
                "collected_at": "2026-09-01T00:00:00Z",
                "raw_content_sha256": "sha-rank",
                "raw_snapshot_path": "chemicals/futures_hold_rank/SA_20260831.csv",
            },
            {
                "trade_date": date(2026, 8, 31),
                "symbol": "SA",
                "name": "纯碱",
                "contract": "SA2609",
                "side": "short",
                "member_name_raw": "席位B",
                "position_volume_raw": "80",
                "source": "Sina_Exchange_Hold_Rank",
                "release_date": date(2026, 8, 31),
                "collected_at": "2026-09-01T00:00:00Z",
                "raw_content_sha256": "sha-rank",
                "raw_snapshot_path": "chemicals/futures_hold_rank/SA_20260831.csv",
            },
        ],
        schema=HOLD_RANK_RAW_SCHEMA,
    )
    curated = build_hold_rank_curated_frame(raw)
    assert curated["top20_net_long_vol"][0] == 20.0
    assert curated["top1_long_member"][0] == "席位A"
    assert curated["smart_money_bias"][0] == "neutral"


def test_chemical_market_keeps_ppi_provenance_separate_from_nbs(tmp_path) -> None:
    from stock_data.fetcher.industry.chemicals.collectors.market import (
        save_chemicals_raw_csv,
    )
    from stock_data.fetcher.industry.models import ChemicalMarketRecord

    save_chemicals_raw_csv(
        tmp_path / "chemicals" / "chemical_operating_spreads.csv",
        [
            ChemicalMarketRecord(
                report_month="2026-08",
                trade_date=date(2026, 8, 31),
                soda_ash_production=289.0,
                source="NBS_Official",
                source_url="https://data.stats.gov.cn/",
                release_date=date(2026, 9, 18),
            )
        ],
    )
    # 现货基准表派生 MDI 参考价，并携带字段级血统
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        [
            {
                "symbol": "MDI",
                "trade_date": date(2026, 8, 31),
                "spot_price_cny": 17000.0,
                "source": "100ppi",
                "source_url": "https://www.100ppi.com/graph/cindex.php?f=graph_ave&ppid=975&type=1&mode=3",
                "release_date": date(2026, 9, 7),
                "data_status": "spot_benchmark",
                "collected_at": "2026-09-01T00:00:00Z",
                "raw_content_sha256": "sha-mdi",
                "raw_snapshot_path": "chemicals/100ppi/MDI.json",
            }
        ]
    ).write_parquet(curated_dir / "chemical_spot_price.parquet")

    records = ChemicalsCollector(raw_dir=tmp_path, curated_dir=curated_dir).collect()
    record = records[0]
    assert record.source == "NBS_Official"
    assert record.release_date == date(2026, 9, 18)
    assert record.mdi_source == "100ppi"
    assert record.mdi_release_date == date(2026, 9, 7)
    assert record.mdi_raw_content_sha256 == "sha-mdi"
