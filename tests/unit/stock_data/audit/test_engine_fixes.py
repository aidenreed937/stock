"""数据审计模块核心修复专项单元测试 (假阳性防御、RAW重复行容忍、动态元数据与分区对账)。"""

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl

from stock_data.audit.engine import UniversalAuditEngine
from stock_data.audit.factor_audit import run_sw_daily_audit
from stock_data.audit.reconciliation import _run_raw_curated_reconciliation


def test_engine_false_positive_prevention() -> None:
    """测试实际数据与预期基准完全错位时，覆盖率应为 0% 且判定为 FAILED，杜绝假阳性。"""
    mock_catalog = MagicMock()
    mock_catalog.data_source = "lixinger"
    # 模拟实际数据落盘 3 个理杏仁代码 ('110000', '210000', '220000')
    # 但基准却被错配置为 3 个申万代码 ('801010.SI', '801030.SI', '801040.SI')
    mock_catalog.load_dataset.return_value = pl.DataFrame(
        {
            "symbol": ["110000", "210000", "220000"],
            "trade_date": [date(2026, 8, 14), date(2026, 8, 14), date(2026, 8, 14)],
        }
    )

    mock_provider = MagicMock()
    mock_provider.get_expected_keys.return_value = pl.DataFrame(
        {
            "symbol": ["801010.SI", "801030.SI", "801040.SI"],
            "trade_date": ["20260814", "20260814", "20260814"],
        }
    )
    mock_provider.get_suspended_keys.return_value = pl.DataFrame(
        {"symbol": pl.Series([], dtype=pl.Utf8), "trade_date": pl.Series([], dtype=pl.Utf8)}
    )

    with patch("stock_data.audit.engine.resolve_benchmark_provider", return_value=mock_provider):
        engine = UniversalAuditEngine(catalog=mock_catalog)
        report = engine.audit_single_day(
            "sw_2021_fundamental", date(2026, 8, 14), data_source="lixinger"
        )

        assert report.expected_count == 3
        assert report.actual_count == 3
        assert report.missing_count == 3  # 全部缺失
        assert report.suspended_count == 0
        assert report.integrity_rate == 0.0  # 覆盖率为 0%
        assert report.status == "FAILED"  # 绝不能报 PASSED


def test_reconciliation_raw_duplicate_tolerance(tmp_path, monkeypatch) -> None:
    """测试 RAW 存在合法批次重复行但 Curated 已去重时，对账判定为 PASSED。"""
    raw_root = tmp_path / "raw"
    curated_root = tmp_path / "curated"
    monkeypatch.setattr("stock_data.audit.reconciliation.data_settings.raw_data_dir", raw_root)
    monkeypatch.setattr(
        "stock_data.audit.reconciliation.data_settings.curated_data_dir", curated_root
    )

    raw_path = raw_root / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    curated_path = (
        curated_root / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    )
    raw_path.mkdir(parents=True)
    curated_path.mkdir(parents=True)

    # RAW 包含 2 个重复行
    pl.DataFrame(
        {
            "symbol": ["600519.SH", "600519.SH", "000001.SZ", "000001.SZ"],
            "trade_date": ["2026-08-03", "2026-08-03", "2026-08-03", "2026-08-03"],
        }
    ).write_parquet(raw_path / "data.parquet")

    # Curated 黄金表已去重
    pl.DataFrame(
        {
            "symbol": ["600519.SH", "000001.SZ"],
            "trade_date": [date(2026, 8, 3), date(2026, 8, 3)],
        }
    ).write_parquet(curated_path / "data.parquet")

    result = _run_raw_curated_reconciliation(date(2026, 8, 3), "tushare")

    assert result["raw_curated_status"] == "PASSED"
    assert result["raw_count"] == 4
    assert result["curated_count"] == 2
    assert result["raw_key_count"] == 2
    assert result["curated_key_count"] == 2
    assert result["missing_in_curated_count"] == 0
    assert result["extra_in_curated_count"] == 0
    assert "已权威去重" in result["raw_curated_reason"]


def test_check_raw_curated_partition_flow(tmp_path) -> None:
    """测试 UniversalAuditEngine._check_raw_curated 支持 market=CN 分区探测。"""
    raw_dir = (
        tmp_path / "raw" / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    )
    curated_dir = (
        tmp_path
        / "curated"
        / "tushare"
        / "market=CN"
        / "stock_daily_bar"
        / "year=2026"
        / "month=08"
    )
    raw_dir.mkdir(parents=True)
    curated_dir.mkdir(parents=True)

    # 构造测试 parquet
    df_raw = pl.DataFrame({"symbol": ["000001.SZ"], "trade_date": ["2026-08-03"]})
    df_curated = pl.DataFrame({"symbol": ["000001.SZ"], "trade_date": [date(2026, 8, 3)]})

    df_raw.write_parquet(raw_dir / "data.parquet")
    df_curated.write_parquet(curated_dir / "data.parquet")

    engine = UniversalAuditEngine()
    with (
        patch("stock_data.settings.data_settings.raw_data_dir", tmp_path / "raw"),
        patch("stock_data.settings.data_settings.curated_data_dir", tmp_path / "curated"),
    ):
        r_cnt, c_cnt, status = engine._check_raw_curated(
            "stock_daily_bar", "tushare", date(2026, 8, 3)
        )
        assert status == "PASSED"
        assert r_cnt == 1
        assert c_cnt == 1


def test_factor_audit_sw_daily_exact(tmp_path, monkeypatch) -> None:
    """测试 factor_audit 中的 sw_daily 审计使用精准交集。"""
    curated_root = tmp_path / "curated"
    monkeypatch.setattr(
        "stock_data.audit.factor_audit.data_settings.curated_data_dir", curated_root
    )

    sw_path = curated_root / "tushare" / "market=CN" / "sw_daily" / "year=2026" / "month=08"
    sw_path.mkdir(parents=True)

    official_31 = [f"8010{i:02d}.SI" for i in range(1, 32)]
    sub_5 = ["801250.SI", "801260.SI", "801270.SI", "801280.SI", "801300.SI"]
    all_syms = official_31 + sub_5

    df = pl.DataFrame({"symbol": all_syms, "trade_date": [date(2026, 8, 14)] * len(all_syms)})
    df.write_parquet(sw_path / "data.parquet")

    with patch(
        "stock_data.audit.benchmarks.industry.IndustryDailyBenchmarkProvider._get_industry_codes",
        return_value=official_31,
    ):
        res = run_sw_daily_audit(date(2026, 8, 14), data_source="tushare", quiet=True)
        assert res["expected_l1_count"] == 31
        assert res["actual_l1_count"] == 31
        assert res["coverage_rate"] == 100.0
        assert res["total_industry_count"] == 36


def test_engine_dataset_alias_resolution() -> None:
    """测试 engine.audit_single_day 传入别名时，自动以 spec.dataset 加载数据。"""
    mock_catalog = MagicMock()
    mock_catalog.data_source = "lixinger"
    # 当以 sw_2021_fundamental 加载时返回有效数据
    mock_catalog.load_dataset.side_effect = lambda name, **kw: (
        pl.DataFrame({"symbol": ["110000"], "trade_date": [date(2026, 8, 14)]})
        if name == "sw_2021_fundamental"
        else pl.DataFrame()
    )

    mock_provider = MagicMock()
    mock_provider.get_expected_keys.return_value = pl.DataFrame(
        {"symbol": ["110000"], "trade_date": ["20260814"]}
    )
    mock_provider.get_suspended_keys.return_value = pl.DataFrame(
        {"symbol": pl.Series([], dtype=pl.Utf8), "trade_date": pl.Series([], dtype=pl.Utf8)}
    )

    with patch("stock_data.audit.engine.resolve_benchmark_provider", return_value=mock_provider):
        engine = UniversalAuditEngine(catalog=mock_catalog)
        report = engine.audit_single_day("sw_industry", date(2026, 8, 14), data_source="lixinger")

        # 验证 catalog 以 spec.dataset (sw_2021_fundamental) 被调用
        mock_catalog.load_dataset.assert_called_with(
            "sw_2021_fundamental", start_date=date(2026, 8, 14), end_date=date(2026, 8, 14)
        )
        assert report.actual_count == 1
        assert report.integrity_rate == 100.0
        assert report.status == "PASSED"


def test_industry_benchmark_lixinger_empty_shells_filtered() -> None:
    """测试理杏仁行业基准动态提取时，自动剔除 6 个空壳无数据代码，保留可交付基准。"""
    from stock_data.audit.benchmarks.industry import (
        LIXINGER_SW_L1_CODES,
        IndustryDailyBenchmarkProvider,
    )

    mock_catalog = MagicMock()
    mock_catalog.data_source = "lixinger"
    # 模拟 sw_2021_constituents 包含 38 个后四位 0000 的代码（含空壳）
    all_38 = LIXINGER_SW_L1_CODES + ["250000", "260000", "310000", "320000", "440000", "470000"]
    mock_catalog.load_dataset.return_value = pl.DataFrame({"symbol": all_38})

    provider = IndustryDailyBenchmarkProvider(catalog=mock_catalog, data_source="lixinger")
    codes = provider._get_industry_codes()

    assert len(codes) == len(LIXINGER_SW_L1_CODES)
    assert "250000" not in codes
    assert "110000" in codes


def test_engine_raw_curated_missing_status(tmp_path) -> None:
    """测试当 RAW 层无目标日期数据时，_check_raw_curated 返回 RAW_MISSING 而非笼统 FAILED。"""
    raw_dir = tmp_path / "raw" / "tushare" / "market=CN" / "sw_daily" / "year=2020" / "month=01"
    curated_dir = (
        tmp_path / "curated" / "tushare" / "market=CN" / "sw_daily" / "year=2026" / "month=08"
    )
    raw_dir.mkdir(parents=True)
    curated_dir.mkdir(parents=True)

    # RAW 只有 2020 年数据，Curated 有 2026 年数据
    pl.DataFrame({"symbol": ["801010.SI"], "trade_date": ["2020-01-02"]}).write_parquet(
        raw_dir / "data.parquet"
    )
    pl.DataFrame({"symbol": ["801010.SI"], "trade_date": [date(2026, 8, 14)]}).write_parquet(
        curated_dir / "data.parquet"
    )

    engine = UniversalAuditEngine()
    with (
        patch("stock_data.settings.data_settings.raw_data_dir", tmp_path / "raw"),
        patch("stock_data.settings.data_settings.curated_data_dir", tmp_path / "curated"),
    ):
        r_cnt, c_cnt, status = engine._check_raw_curated("sw_daily", "tushare", date(2026, 8, 14))
        assert status == "RAW_MISSING"
        assert r_cnt == 0
        assert c_cnt == 1
