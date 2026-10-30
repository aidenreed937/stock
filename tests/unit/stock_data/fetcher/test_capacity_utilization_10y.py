from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import pytest

from stock_data.fetcher.industry.chemicals.collectors.capacity import (
    ChemicalCapacityUtilization10Y,
    NbsChemicalsCrawler,
    NbsSodaAshCrawler,
)
from stock_data.fetcher.industry.chemicals.schemas import CAPACITY_RAW_SCHEMA
from stock_data.fetcher.industry.chemicals.transforms.capacity import (
    build_capacity_utilization_frame,
)


def test_capacity_result_preserves_raw_and_reports_invalid_rows(tmp_path: Path) -> None:
    nbs_dir = tmp_path / "chemicals" / "nbs"
    nbs_dir.mkdir(parents=True)
    (nbs_dir / "nbs_soda_ash_monthly.csv").write_text(
        "report_month,output_current,output_yoy,release_date\n"
        "2026-07,100,5,2026-08-18\n"
        "2026-08,bad,5,2026-09-18\n",
        encoding="utf-8",
    )
    capacity_dir = tmp_path / "chemicals" / "capacity"
    capacity_dir.mkdir(parents=True)
    (capacity_dir / "soda_ash_annual_capacity.csv").write_text(
        "year,annual_capacity_w_tons,source\n2026,1200,CPCIF\n",
        encoding="utf-8",
    )

    result = ChemicalCapacityUtilization10Y(tmp_path).build_raw_utilization_result()

    assert result.status == "PARTIAL"
    assert result.frame.height == 2
    assert result.errors
    assert build_capacity_utilization_frame(result.frame).height == 1


def test_capacity_utilization_10y_build() -> None:
    builder = ChemicalCapacityUtilization10Y(raw_dir="data/raw/industry")
    raw_df = builder.build_raw_utilization()
    assert isinstance(raw_df, pl.DataFrame)
    assert len(raw_df) >= 100

    # 验证 RAW 底表不做任何计算：不包含派生与百分比字段
    for forbidden in (
        "implied_capacity_utilization_pct",
        "monthly_capacity_w_tons",
        "actual_output_w_tons",
    ):
        assert forbidden not in raw_df.columns

    df = builder.build_10y_utilization()
    assert isinstance(df, pl.DataFrame)
    assert "actual_output_w_tons" in df.columns
    assert "implied_capacity_utilization_pct" in df.columns
    assert "annual_capacity_w_tons" in df.columns
    assert len(df) >= 100
    # 验证产能利用率在合理物理区间 [20%, 120%]
    utils = df["implied_capacity_utilization_pct"].drop_nulls()
    assert float(utils.min()) > 20.0  # type: ignore[arg-type]
    assert float(utils.max()) < 120.0  # type: ignore[arg-type]


def test_capacity_raw_parquet_schema_purity(tmp_path: Path) -> None:
    """验证 RAW data.parquet 的纯净性、多品种列对齐与 2-Tier ETL 规范。"""
    chemicals_dir = tmp_path / "chemicals"
    chemicals_dir.mkdir(parents=True)
    parquet_path = chemicals_dir / "data.parquet"

    capacity_dir = tmp_path / "chemicals" / "capacity"
    capacity_dir.mkdir(parents=True, exist_ok=True)
    (capacity_dir / "soda_ash_annual_capacity.csv").write_text(
        "year,effective_capacity_w_tons,data_source,notes\n2026,4900.0,CPCIF,test\n",
        encoding="utf-8",
    )

    rows = [
        {
            "product_name": "纯碱",
            "symbol": "SA",
            "report_month": "2026-07",
            "trade_date": "2026-07-01",
            "output_current_raw": "341.7",
            "output_cumulative_raw": "2400.0",
            "output_yoy_raw": "11.3",
            "output_cum_yoy_raw": "8.0",
            "annual_capacity_raw": "4900.0",
            "capacity_source": "CPCIF",
            "unit": "万吨",
            "source": "NBS_Official",
            "release_date": "2026-08-18",
            "collected_at": "2026-09-09T00:00:00Z",
        }
    ]
    pl.DataFrame(rows).with_columns(
        pl.col("trade_date").str.to_date(),
        pl.col("release_date").str.to_date(),
    ).write_parquet(parquet_path)

    builder = ChemicalCapacityUtilization10Y(tmp_path)
    raw_frame = builder.build_raw_utilization()
    assert raw_frame.schema == CAPACITY_RAW_SCHEMA
    assert "implied_capacity_utilization_pct" not in raw_frame.columns

    curated = builder.build_10y_utilization()
    assert curated.height == 1
    assert "implied_capacity_utilization_pct" in curated.columns
    assert curated["implied_capacity_utilization_pct"][0] > 0


def test_capacity_legacy_parquet_fallback(tmp_path: Path) -> None:
    """验证旧路径 chemicals/capacity/data.parquet 的无缝向后兼容对齐。"""
    capacity_dir = tmp_path / "chemicals" / "capacity"
    capacity_dir.mkdir(parents=True)
    legacy_parquet = capacity_dir / "data.parquet"

    rows = [
        {
            "report_month": "2026-07",
            "trade_date": "2026-07-01",
            "output_current_raw": "341.7",
            "output_yoy_raw": "11.3",
            "annual_capacity_raw": "4900.0",
            "capacity_source": "CPCIF",
            "source": "NBS_Official",
            "release_date": "2026-08-18",
            "collected_at": "2026-09-09T00:00:00Z",
        }
    ]
    pl.DataFrame(rows).with_columns(
        pl.col("trade_date").str.to_date(),
        pl.col("release_date").str.to_date(),
    ).write_parquet(legacy_parquet)

    builder = ChemicalCapacityUtilization10Y(tmp_path)
    raw_frame = builder.build_raw_utilization()
    assert raw_frame.schema == CAPACITY_RAW_SCHEMA
    assert raw_frame["product_name"][0] == "纯碱"
    assert raw_frame["symbol"][0] == "SA"


def test_capacity_incremental_update_with_mock_crawler(tmp_path: Path) -> None:
    """验证当在线采集发现新月份时，增量合并写回 RAW 底表并更新状态。"""
    chemicals_dir = tmp_path / "chemicals"
    chemicals_dir.mkdir(parents=True)
    parquet_path = chemicals_dir / "data.parquet"

    # 初始化包含 2026-07 历史行
    init_df = pl.DataFrame(
        [
            {
                "product_name": "纯碱",
                "symbol": "SA",
                "report_month": "2026-07",
                "trade_date": "2026-07-01",
                "output_current_raw": "341.7",
                "output_cumulative_raw": None,
                "output_yoy_raw": "11.3",
                "output_cum_yoy_raw": None,
                "annual_capacity_raw": "4900.0",
                "capacity_source": "CPCIF",
                "unit": "万吨",
                "source": "NBS_Official",
                "release_date": "2026-08-18",
                "collected_at": "2026-09-09T00:00:00Z",
            }
        ]
    ).with_columns(
        pl.col("trade_date").str.to_date(),
        pl.col("release_date").str.to_date(),
    )
    init_df.write_parquet(parquet_path)
    assert NbsSodaAshCrawler is NbsChemicalsCrawler

    mock_crawler = MagicMock(spec=NbsChemicalsCrawler)
    mock_crawler.fetch_range.return_value = (
        [
            {
                "report_month": "2026-08",
                "output_current_raw": "350.0",
                "output_yoy_raw": "8.5",
            }
        ],
        [],
    )

    builder = ChemicalCapacityUtilization10Y(tmp_path, crawler=mock_crawler)
    result = builder.build_raw_utilization_result(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 8, 1),
    )

    assert result.updated is True
    assert result.status == "SUCCESS"
    assert "2026-08" in result.fetched_periods
    assert result.frame.height == 2

    # 验证增量写回后的 Parquet 仍然是纯 RAW，无计算字段
    updated_parquet = pl.read_parquet(parquet_path)
    assert updated_parquet.height == 2
    assert "implied_capacity_utilization_pct" not in updated_parquet.columns
    assert set(updated_parquet["report_month"].to_list()) == {"2026-07", "2026-08"}


def test_capacity_crawler_offline_fallback(tmp_path: Path) -> None:
    """验证网络异常或离线环境下的优雅降级。"""
    chemicals_dir = tmp_path / "chemicals"
    chemicals_dir.mkdir(parents=True)
    parquet_path = chemicals_dir / "data.parquet"

    init_df = pl.DataFrame(
        [
            {
                "product_name": "纯碱",
                "symbol": "SA",
                "report_month": "2026-07",
                "trade_date": "2026-07-01",
                "output_current_raw": "341.7",
                "output_cumulative_raw": None,
                "output_yoy_raw": "11.3",
                "output_cum_yoy_raw": None,
                "annual_capacity_raw": "4900.0",
                "capacity_source": "CPCIF",
                "unit": "万吨",
                "source": "NBS_Official",
                "release_date": "2026-08-18",
                "collected_at": "2026-09-09T00:00:00Z",
            }
        ]
    ).with_columns(
        pl.col("trade_date").str.to_date(),
        pl.col("release_date").str.to_date(),
    )
    init_df.write_parquet(parquet_path)

    mock_crawler = MagicMock(spec=NbsChemicalsCrawler)
    mock_crawler.fetch_range.return_value = ([], ["2026-08: Connection timeout"])

    builder = ChemicalCapacityUtilization10Y(tmp_path, crawler=mock_crawler)
    result = builder.build_raw_utilization_result(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 8, 1),
    )

    assert result.updated is False
    assert result.status == "PARTIAL"
    assert result.frame.height == 1


def test_nbs_chemicals_crawler_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证国家统计局 (NBS) 官方实物产量数据获取、指标解析与原始快照存盘。"""
    import sys

    import pandas as pd

    mock_df = pd.DataFrame(
        {
            "2026年8月": [
                "334.4",
                "2568.1",
                "3.0",
                "4.2",
            ]
        },
        index=[
            "纯碱（碳酸钠）产量当期值(万吨)",
            "纯碱（碳酸钠）产量累计值(万吨)",
            "纯碱（碳酸钠）产量同比增长(%)",
            "纯碱（碳酸钠）产量累计增长(%)",
        ],
    )

    mock_ak = MagicMock()
    mock_ak.macro_china_nbs_nation.return_value = mock_df
    monkeypatch.setitem(sys.modules, "akshare", mock_ak)

    crawler = NbsChemicalsCrawler(raw_dir=tmp_path, enable_network=True)
    parsed = crawler.fetch_month("2026-08", product_name="纯碱")

    assert parsed is not None
    assert parsed["report_month"] == "2026-08"
    assert parsed["output_current_raw"] == "334.4"
    assert parsed["output_cumulative_raw"] == "2568.1"
    assert parsed["output_yoy_raw"] == "3.0"
    assert parsed["output_cum_yoy_raw"] == "4.2"
    assert parsed["source"] == "NBS_Official"
    assert parsed["release_date"] == date(2026, 9, 18)

    snapshot_file = tmp_path / "chemicals" / "capacity" / "snapshots" / "nbs_纯碱_2026-08.json.gz"
    assert snapshot_file.exists()


def test_incremental_pipeline_with_nbs_crawler(tmp_path: Path) -> None:
    """验证 NbsChemicalsCrawler 增量采集并入 RAW 底表与 Curated 利用率派生全流程。"""
    chemicals_dir = tmp_path / "chemicals"
    chemicals_dir.mkdir(parents=True)
    parquet_path = chemicals_dir / "data.parquet"

    cap_dir = chemicals_dir / "capacity"
    cap_dir.mkdir(parents=True, exist_ok=True)
    (cap_dir / "soda_ash_annual_capacity.csv").write_text(
        "year,annual_capacity_w_tons,source\n2026,4900.0,CPCIF\n",
        encoding="utf-8",
    )

    init_df = pl.DataFrame(
        [
            {
                "product_name": "纯碱",
                "symbol": "SA",
                "report_month": "2026-07",
                "trade_date": "2026-07-01",
                "output_current_raw": "341.7",
                "output_cumulative_raw": None,
                "output_yoy_raw": "11.3",
                "output_cum_yoy_raw": None,
                "annual_capacity_raw": "4900.0",
                "capacity_source": "CPCIF",
                "unit": "万吨",
                "source": "NBS_Official",
                "release_date": "2026-08-18",
                "collected_at": "2026-09-09T00:00:00Z",
            }
        ]
    ).with_columns(
        pl.col("trade_date").str.to_date(),
        pl.col("release_date").str.to_date(),
    )
    init_df.write_parquet(parquet_path)

    crawler = NbsChemicalsCrawler(raw_dir=tmp_path)
    crawler.fetch_month = MagicMock(  # type: ignore[method-assign]
        return_value={
            "report_month": "2026-08",
            "output_current_raw": "334.4",
            "output_cumulative_raw": "2568.1",
            "output_yoy_raw": "3.0",
            "output_cum_yoy_raw": "4.2",
            "source": "NBS_Official",
            "release_date": date(2026, 9, 18),
        }
    )

    builder = ChemicalCapacityUtilization10Y(tmp_path, crawler=crawler)
    result = builder.build_raw_utilization_result(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 8, 1),
    )

    assert result.updated is True
    assert result.status == "SUCCESS"
    assert "2026-08" in result.fetched_periods

    # 1. 验证 RAW data.parquet 格式严格无任何计算字段
    raw_df = pl.read_parquet(parquet_path)
    assert raw_df.height == 2
    for forbidden in ("implied_capacity_utilization_pct", "monthly_capacity_w_tons"):
        assert forbidden not in raw_df.columns

    aug_raw = raw_df.filter(pl.col("report_month") == "2026-08").to_dicts()[0]
    assert aug_raw["source"] == "NBS_Official"
    assert aug_raw["output_current_raw"] == "334.4"
    assert aug_raw["release_date"] == date(2026, 9, 18)

    # 2. 验证 Curated 成功生成折算与产能利用率 (334.4 / ((4900 / 365) * 31) = 80.35%)
    curated = builder.build_10y_utilization()
    assert curated.height == 2
    aug_curated = curated.filter(pl.col("month") == 8).to_dicts()[0]
    assert round(float(aug_curated["implied_capacity_utilization_pct"]), 2) == 80.35
    assert aug_curated["actual_output_w_tons"] == 334.4
    assert aug_curated["source"] == "NBS_Official/CPCIF"


def test_capacity_jan_feb_day_weighted_split() -> None:
    """验证方案 1：无周度高频数据时，自然天数加权拆解 1-2 月合并累计数据且实物守恒。"""
    raw_df = pl.DataFrame(
        [
            {
                "product_name": "纯碱",
                "symbol": "SA",
                "report_month": "2023-01",
                "trade_date": date(2023, 1, 1),
                "output_current_raw": None,
                "output_cumulative_raw": None,
                "output_yoy_raw": None,
                "output_cum_yoy_raw": None,
                "annual_capacity_raw": "3800.0",
                "capacity_source": "CPCIF",
                "unit": "万吨",
                "source": "NBS_Official",
                "release_date": None,
                "collected_at": "2026-09-09T00:00:00Z",
            },
            {
                "product_name": "纯碱",
                "symbol": "SA",
                "report_month": "2023-02",
                "trade_date": date(2023, 2, 1),
                "output_current_raw": None,
                "output_cumulative_raw": "502.9",
                "output_yoy_raw": None,
                "output_cum_yoy_raw": "7.6",
                "annual_capacity_raw": "3800.0",
                "capacity_source": "CPCIF",
                "unit": "万吨",
                "source": "NBS_Official",
                "release_date": date(2023, 3, 18),
                "collected_at": "2026-09-09T00:00:00Z",
            },
        ],
        schema=CAPACITY_RAW_SCHEMA,
    )

    # 显式传入空的 weekly_survey_df 确保触发方案 1 (自然天数)
    curated = build_capacity_utilization_frame(raw_df, weekly_survey_df=pl.DataFrame())
    assert curated.height == 2

    jan = curated.filter(pl.col("month") == 1).to_dicts()[0]
    feb = curated.filter(pl.col("month") == 2).to_dicts()[0]

    # 1. 验证实物总量严格守恒 (264.22 + 238.68 = 502.9)
    total_output = round(float(jan["actual_output_w_tons"]) + float(feb["actual_output_w_tons"]), 2)
    assert total_output == 502.9

    # 2. 验证天数加权下 1 月与 2 月的利用率数学恒等 (均为 81.85%)
    assert jan["implied_capacity_utilization_pct"] == feb["implied_capacity_utilization_pct"]
    assert jan["implied_capacity_utilization_pct"] is not None
    assert 81.0 < float(jan["implied_capacity_utilization_pct"]) < 83.0

    # 3. 验证同比增速继承自累计同比 7.6%
    assert jan["yoy_growth"] == 0.076
    assert feb["yoy_growth"] == 0.076

    # 4. 验证血统标记为 day_weighted_split
    assert "day_weighted_split" in str(jan["source"])
    assert "day_weighted_split" in str(feb["source"])


def test_capacity_jan_feb_weekly_survey_split() -> None:
    """验证方案 2：有周度高频调查数据时，优先使用周度实物权重拆解 1-2 月。"""
    raw_df = pl.DataFrame(
        [
            {
                "product_name": "纯碱",
                "symbol": "SA",
                "report_month": "2025-02",
                "trade_date": date(2025, 2, 1),
                "output_current_raw": None,
                "output_cumulative_raw": "600.0",
                "output_yoy_raw": None,
                "output_cum_yoy_raw": "5.0",
                "annual_capacity_raw": "4600.0",
                "capacity_source": "CPCIF",
                "unit": "万吨",
                "source": "NBS_Official",
                "release_date": date(2025, 3, 18),
                "collected_at": "2026-09-09T00:00:00Z",
            },
        ],
        schema=CAPACITY_RAW_SCHEMA,
    )

    # 模拟周度调查数据：1 月周度产量总计 200，2 月周度产量总计 400 (比例 1:2)
    mock_survey = pl.DataFrame(
        [
            {
                "product_name": "纯碱",
                "report_date": date(2025, 1, 15),
                "weekly_output_w_tons": 200.0,
            },
            {
                "product_name": "纯碱",
                "report_date": date(2025, 2, 15),
                "weekly_output_w_tons": 400.0,
            },
        ]
    )

    curated = build_capacity_utilization_frame(raw_df, weekly_survey_df=mock_survey)
    assert curated.height == 2

    jan = curated.filter(pl.col("month") == 1).to_dicts()[0]
    feb = curated.filter(pl.col("month") == 2).to_dicts()[0]

    # 1. 验证按 1:2 权重拆解 (1月 = 600 * 1/3 = 200.0, 2月 = 600 * 2/3 = 400.0)
    assert jan["actual_output_w_tons"] == 200.0
    assert feb["actual_output_w_tons"] == 400.0

    # 2. 验证总量严格守恒
    assert (
        round(float(jan["actual_output_w_tons"]) + float(feb["actual_output_w_tons"]), 2) == 600.0
    )

    # 3. 验证血统标记为 weekly_survey_split
    assert "weekly_survey_split" in str(jan["source"])
    assert "weekly_survey_split" in str(feb["source"])


def test_capacity_utilization_10_products_full_coverage() -> None:
    """验证扩充后的 10 品种全景通用大底座数据覆盖率、利用率与物理区间。"""
    builder = ChemicalCapacityUtilization10Y(raw_dir="data/raw/industry")
    raw_df = builder.build_raw_utilization()

    # 1. 验证 10 品种齐备且行数 1200 (10 品种 × 120 月度)
    expected_products = {
        "纯碱",
        "烧碱",
        "PTA",
        "甲醇",
        "初级形态塑料",
        "农用化肥",
        "平板玻璃",
        "合成纤维",
        "尿素",
        "PVC",
    }
    actual_products = set(raw_df["product_name"].unique().to_list())
    assert expected_products == actual_products
    assert raw_df.height == 1200

    # 2. 验证 Curated 事实表 (纯碱与平板玻璃已推进至 2026-08 满 120 月，其余 8 品种 119 月，合计 1192 行)
    curated_df = builder.build_10y_utilization()
    assert curated_df.height >= 1190

    # 3. 验证具备官方经审计年鉴/研报的 8 大核心品种具备有效年产能与合理利用率 (20%~120%)
    for sym in ("SA", "SH", "TA", "MA", "V", "FG", "SF", "UR"):
        sub_df = curated_df.filter(pl.col("symbol") == sym)
        assert sub_df.height >= 119
        sub_utils = sub_df["implied_capacity_utilization_pct"].drop_nulls()
        assert not sub_utils.is_empty()
        assert float(sub_utils.min()) >= 20.0  # type: ignore[arg-type]
        assert float(sub_utils.max()) <= 120.0  # type: ignore[arg-type]

    # 4. 验证宏观汇总大口径品种 (初级塑料 PL, 农用化肥 CF) 不虚构数据: 利用率严格为 None，但实物月度产量真实保留
    for sym in ("PL", "CF"):
        sub_df = curated_df.filter(pl.col("symbol") == sym)
        assert sub_df.height >= 119
        assert sub_df["implied_capacity_utilization_pct"].drop_nulls().is_empty()
        assert not sub_df["actual_output_w_tons"].drop_nulls().is_empty()


def test_capacity_utilization_offline_by_default(tmp_path: Path) -> None:
    """验证 ChemicalCapacityUtilization10Y 默认纯离线模式，不发起外部爬虫。"""
    chemicals_dir = tmp_path / "chemicals"
    chemicals_dir.mkdir(parents=True)
    parquet_path = chemicals_dir / "data.parquet"

    init_df = pl.DataFrame(
        [
            {
                "product_name": "纯碱",
                "symbol": "SA",
                "report_month": "2026-07",
                "trade_date": "2026-07-01",
                "output_current_raw": "341.7",
                "output_cumulative_raw": None,
                "output_yoy_raw": "11.3",
                "output_cum_yoy_raw": None,
                "annual_capacity_raw": "4900.0",
                "capacity_source": "CPCIF",
                "unit": "万吨",
                "source": "NBS_Official",
                "release_date": "2026-08-18",
                "collected_at": "2026-09-09T00:00:00Z",
            }
        ]
    ).with_columns(
        pl.col("trade_date").str.to_date(),
        pl.col("release_date").str.to_date(),
    )
    init_df.write_parquet(parquet_path)

    # 不传 mock crawler，验证不会发起任何网络请求，无报错
    builder = ChemicalCapacityUtilization10Y(tmp_path)
    result = builder.build_raw_utilization_result(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 8, 1),
    )
    assert result.status == "SUCCESS"
    assert result.errors == ()
    assert result.updated is False
