from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.weekly_survey import (
    ChemicalWeeklySurveyCollector,
)


def test_weekly_survey_collector_mock(tmp_path: Path) -> None:
    mock_html = """
    <html><body>
    8月27日当周，纯碱装置开工率80.44%，较上周增加2.13%；纯碱产量76.62万吨，较上周增加2.72%。
    8月27日，本周国内纯碱库存187.27万吨，较上周增加1.51%。
    8月27日，本周中国纯碱企业出货量73.84万吨，环比减少2.54%，纯碱出货率在96.37%。
    </body></html>
    """

    collector = ChemicalWeeklySurveyCollector(raw_dir=tmp_path, enable_online=True)
    with patch.object(collector, "_fetch_html_with_cookie_bypass", return_value=mock_html):
        df = collector.collect(current_year=2026)
        assert not df.is_empty()
        assert "operating_rate_pct" in df.columns
        assert "factory_inventory_w_tons" in df.columns
        assert "shipment_rate_pct" in df.columns
        # 同一 mock 页会被 100ppi 与 Longzhong 两条通道消费，因此按 source 锁定 100ppi 通道行断言
        row = df.filter(
            (pl.col("report_date") == date(2026, 8, 27)) & (pl.col("source") == "100ppi_Weekly")
        )
        assert len(row) == 1
        assert row["operating_rate_pct"][0] == 80.44
        assert row["factory_inventory_w_tons"][0] == 187.27
        assert row["shipment_rate_pct"][0] == 96.37
        assert row["release_date"][0] is None
        assert row["raw_content_sha256"][0]
        snapshot_path = row["raw_snapshot_path"][0]
        assert snapshot_path.startswith("chemicals/operating_rates/snapshots/100ppi_weekly_2026_")
        assert snapshot_path.endswith(".html")
        assert (collector.raw_dir / snapshot_path).exists()


def test_weekly_survey_skips_longzhong_page_without_metrics(tmp_path: Path) -> None:
    collector = ChemicalWeeklySurveyCollector(raw_dir=tmp_path)
    with (
        patch.object(collector, "_fetch_html_with_cookie_bypass", return_value=""),
        patch.object(
            collector.session,
            "get",
            return_value=SimpleNamespace(status_code=200, text="<html>暂无产业指标</html>"),
        ),
    ):
        df = collector.collect(current_year=2026)

    assert df.is_empty()


def test_weekly_survey_project_raw() -> None:
    collector = ChemicalWeeklySurveyCollector(raw_dir="data/raw/industry")
    csv_file = collector.survey_dir / "weekly_survey.csv"
    if csv_file.exists():
        records = collector._load_raw_csv()
        assert len(records) > 0


def test_weekly_survey_force_preserves_local_raw_history(tmp_path: Path) -> None:
    collector = ChemicalWeeklySurveyCollector(raw_dir=tmp_path)
    collector.survey_dir.joinpath("weekly_survey.csv").write_text(
        "trade_date,report_date,product_name,symbol,operating_rate_pct,weekly_output_w_tons,"
        "factory_inventory_w_tons,shipment_rate_pct,source,source_url,release_date,data_status,collected_at,raw_content_sha256,raw_snapshot_path\n"
        "2026-08-27,2026-08-27,纯碱,SA,80.44,,,,100ppi_Weekly,https://100ppi.com,,actual,now,sha256-test,chemicals/operating_rates/snapshots/test.html\n",
        encoding="utf-8",
    )
    with (
        patch.object(collector, "_fetch_html_with_cookie_bypass", return_value=""),
        patch.object(collector, "_load_mysteel_sources", return_value=[]),
    ):
        result = collector.collect(current_year=2026, force=True)

    assert result.height == 1
    assert result["report_date"][0] == date(2026, 8, 27)


def test_weekly_survey_uses_recent_raw_without_repeating_request(tmp_path: Path) -> None:
    collector = ChemicalWeeklySurveyCollector(raw_dir=tmp_path)
    collector.survey_dir.joinpath("weekly_survey.csv").write_text(
        "trade_date,report_date,product_name,symbol,operating_rate_pct,weekly_output_w_tons,"
        "factory_inventory_w_tons,shipment_rate_pct,source,source_url,release_date,data_status,collected_at,raw_content_sha256,raw_snapshot_path\n"
        "2026-08-27,2026-08-27,纯碱,SA,80.44,,,,100ppi_Weekly,https://100ppi.com,,actual,now,sha256-test,chemicals/operating_rates/snapshots/test.html\n",
        encoding="utf-8",
    )
    with (
        patch.object(collector, "_fetch_html_with_cookie_bypass") as fetch_html,
        patch.object(collector, "_load_mysteel_sources", return_value=[]),
    ):
        result = collector.collect_result(
            current_year=2026,
            start_date=date(2026, 8, 27),
            end_date=date(2026, 8, 28),
        )

    fetch_html.assert_not_called()
    assert result.status == "SUCCESS"
    assert result.cached_periods == ("100ppi_Weekly:SA:2026-08-27",)


def test_weekly_survey_keeps_same_date_from_multiple_sources(tmp_path: Path) -> None:
    collector = ChemicalWeeklySurveyCollector(raw_dir=tmp_path)
    records = {
        ("纯碱", "2026-08-06", "100ppi_Weekly"): {
            "trade_date": date(2026, 8, 6),
            "report_date": date(2026, 8, 6),
            "product_name": "纯碱",
            "symbol": "SA",
            "operating_rate_pct": 80.0,
            "weekly_output_w_tons": None,
            "factory_inventory_w_tons": None,
            "shipment_rate_pct": None,
            "source": "100ppi_Weekly",
            "source_url": "https://100ppi.com",
            "release_date": None,
            "collected_at": "now",
            "raw_content_sha256": "sha-ppi",
            "raw_snapshot_path": "chemicals/operating_rates/snapshots/ppi.html",
        },
        ("纯碱", "2026-08-06", "Longzhong_Oilchem"): {
            "trade_date": date(2026, 8, 6),
            "report_date": date(2026, 8, 6),
            "product_name": "纯碱",
            "symbol": "SA",
            "operating_rate_pct": 81.0,
            "weekly_output_w_tons": None,
            "factory_inventory_w_tons": None,
            "shipment_rate_pct": None,
            "source": "Longzhong_Oilchem",
            "source_url": "https://mysteel.com",
            "release_date": None,
            "collected_at": "now",
            "raw_content_sha256": "sha-lz",
            "raw_snapshot_path": "chemicals/operating_rates/snapshots/lz.html",
        },
    }

    collector._save_raw_csv(records)
    loaded = collector.load_from_raw()

    assert loaded.height == 2
    assert set(loaded["source"].to_list()) == {"100ppi_Weekly", "Longzhong_Oilchem"}


def test_weekly_survey_filters_100ppi_records_before_raw_write(tmp_path: Path) -> None:
    mock_html = """
    <html><body>
    8月27日当周，纯碱装置开工率80.44%。
    </body></html>
    """
    collector = ChemicalWeeklySurveyCollector(raw_dir=tmp_path)
    with (
        patch.object(collector, "_fetch_html_with_cookie_bypass", return_value=mock_html),
        patch.object(collector, "_load_mysteel_sources", return_value=[]),
    ):
        result = collector.collect(
            current_year=2026,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )

    assert result.is_empty()
    assert not collector.survey_dir.joinpath("weekly_survey.csv").exists()


def test_coalesce_weekly_survey_merges_monday_and_thursday() -> None:
    """验证同周内周一纯库存快讯与周四综合周报正确合流为一个完整周度基准记录。"""
    from stock_data.fetcher.industry.chemicals.transforms.weekly_survey import (
        coalesce_weekly_survey_frame,
    )

    raw_data = pl.DataFrame(
        [
            {
                "trade_date": "2026-07-27",  # 周一
                "report_date": "2026-07-27",
                "product_name": "纯碱",
                "symbol": "SA",
                "operating_rate_pct": None,
                "weekly_output_w_tons": None,
                "factory_inventory_w_tons": 179.24,
                "shipment_rate_pct": None,
                "source": "100ppi_Weekly",
                "source_url": "https://100ppi.com/mon",
                "release_date": "2026-07-27",
                "data_status": "actual",
                "collected_at": "now",
            },
            {
                "trade_date": "2026-07-30",  # 周四
                "report_date": "2026-07-30",
                "product_name": "纯碱",
                "symbol": "SA",
                "operating_rate_pct": 80.68,
                "weekly_output_w_tons": 76.85,
                "factory_inventory_w_tons": 180.07,
                "shipment_rate_pct": 97.48,
                "source": "100ppi_Weekly",
                "source_url": "https://100ppi.com/thu",
                "release_date": "2026-07-30",
                "data_status": "actual",
                "collected_at": "now",
            },
        ]
    )

    coalesced = coalesce_weekly_survey_frame(raw_data)
    assert len(coalesced) == 1
    row = coalesced.row(0, named=True)
    assert row["report_date"] == date(2026, 7, 30)  # 基准日对齐到周四
    assert row["operating_rate_pct"] == 80.68
    assert row["weekly_output_w_tons"] == 76.85
    assert row["factory_inventory_w_tons"] == 180.07
    assert row["shipment_rate_pct"] == 97.48
    assert row["data_status"] == "actual"


def test_coalesce_weekly_survey_prioritizes_latest_thursday_values_over_monday() -> None:
    """验证同周内若周一与周四均有值，各指标优先采纳周四最新上报值而非被周一锚定覆盖 (P5)。"""
    from stock_data.fetcher.industry.chemicals.transforms.weekly_survey import (
        coalesce_weekly_survey_frame,
    )

    raw_data = pl.DataFrame(
        [
            {
                "trade_date": "2026-09-14",  # 周一
                "report_date": "2026-09-14",
                "product_name": "纯碱",
                "symbol": "SA",
                "operating_rate_pct": 82.50,  # 周一开工
                "weekly_output_w_tons": 70.00,
                "factory_inventory_w_tons": 190.62,  # 周一旧库存
                "shipment_rate_pct": 92.00,
                "source": "100ppi_Weekly",
                "source_url": "https://100ppi.com/mon",
                "release_date": "2026-09-14",
                "data_status": "actual",
                "collected_at": "now",
            },
            {
                "trade_date": "2026-09-17",  # 周四
                "report_date": "2026-09-17",
                "product_name": "纯碱",
                "symbol": "SA",
                "operating_rate_pct": None,  # 周四未更新开工率，应回退取周一 82.50
                "weekly_output_w_tons": 71.50,  # 周四最新产量
                "factory_inventory_w_tons": 188.88,  # 周四最新库存（应取该最新值）
                "shipment_rate_pct": 95.00,  # 周四最新出货率
                "source": "100ppi_Weekly",
                "source_url": "https://100ppi.com/thu",
                "release_date": "2026-09-17",
                "data_status": "actual",
                "collected_at": "now",
            },
        ]
    )

    coalesced = coalesce_weekly_survey_frame(raw_data)
    assert len(coalesced) == 1
    row = coalesced.row(0, named=True)
    assert row["report_date"] == date(2026, 9, 17)
    assert row["factory_inventory_w_tons"] == 188.88  # 取周四最新值，非 190.62
    assert row["weekly_output_w_tons"] == 71.50  # 取周四最新产量
    assert row["shipment_rate_pct"] == 95.00  # 取周四最新出货率
    assert row["operating_rate_pct"] == 82.50  # 周四缺失，安全回退至周一非空值


def test_coalesce_weekly_survey_physics_imputation() -> None:
    """验证对缺失开工率的周产量记录执行物理守恒补算并打标 imputed。"""
    from stock_data.fetcher.industry.chemicals.transforms.weekly_survey import (
        coalesce_weekly_survey_frame,
    )

    raw_data = pl.DataFrame(
        [
            # 基准周：产量 64 万吨，开工率 80%，隐含有效周产能 80 万吨
            {
                "trade_date": "2024-01-11",
                "report_date": "2024-01-11",
                "product_name": "纯碱",
                "symbol": "SA",
                "operating_rate_pct": 80.0,
                "weekly_output_w_tons": 64.0,
                "factory_inventory_w_tons": 30.0,
                "shipment_rate_pct": 95.0,
                "source": "CFA_Futures_Report",
                "source_url": "https://cfachina.org",
                "release_date": "2024-01-11",
                "data_status": "actual",
                "collected_at": "now",
            },
            # 缺失开工率周：产量 68 万吨，开工率缺失 -> 补算应为 68 / 80 * 100 = 85.0%
            {
                "trade_date": "2024-01-18",
                "report_date": "2024-01-18",
                "product_name": "纯碱",
                "symbol": "SA",
                "operating_rate_pct": None,
                "weekly_output_w_tons": 68.0,
                "factory_inventory_w_tons": 35.0,
                "shipment_rate_pct": None,
                "source": "CFA_Futures_Report",
                "source_url": "https://cfachina.org",
                "release_date": "2024-01-18",
                "data_status": "actual",
                "collected_at": "now",
            },
        ]
    )

    coalesced = coalesce_weekly_survey_frame(raw_data)
    assert len(coalesced) == 2
    target_row = coalesced.filter(pl.col("report_date") == date(2024, 1, 18)).row(0, named=True)
    assert target_row["operating_rate_pct"] == 85.0
    assert target_row["data_status"] == "imputed"


def test_research_parser_excludes_downstream_glass_operating_rate(tmp_path: Path) -> None:
    """验证研报解析器严格排除浮法玻璃开工率，不误当成纯碱开工率。"""
    from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser

    report_text = """
    供应方面：近期行业整体开工负荷略提，货源供应量增加。
    截止到2024年1月4日，周内纯碱产量66.32万吨。
    1月3日，全国浮法玻璃日产量为17.38万吨，浮法玻璃行业开工率为83.01%。
    库存方面：截止到2024年1月4日，本周国内纯碱厂家总库存36.96万吨。
    """
    parser = ResearchReportParser(raw_dir=tmp_path)
    metrics = parser.extract_metrics_from_text(
        text=report_text,
        product_name="纯碱",
        publish_date=date(2024, 1, 4),
    )

    assert len(metrics) > 0
    main = metrics[0]
    # 纯碱开工率应为 None，绝不能被玻璃的 83.01% 污染
    assert main["operating_rate_pct"] is None
    assert main["weekly_output_w_tons"] == 66.32
    assert main["factory_inventory_w_tons"] == 36.96


def test_parse_commodity_weekly_metrics_anti_misparse_annual_and_monthly() -> None:
    """验证大宗商品周度解析器严格排除年度、月度、日产量，防止周期错位与异常大值。"""
    from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
        parse_commodity_weekly_metrics,
    )

    # 1. PTA 2023 全年产量 6375 万吨与 1 月月产 584.5 万吨
    pta_text = """
    2.3 PTA 供需平衡附近
    2023 年国内PTA产量 6375万吨，同比增加 18.3%。2024年 1 月 PTA产量 584.5万吨。
    国内PTA周均产能利用率至83.30%，环比上升0.22个百分点。
    """
    pta_res = parse_commodity_weekly_metrics(pta_text, "精对苯二甲酸", "TA")
    assert pta_res["weekly_output_w_tons"] is None  # 坚决不抓年产或月产
    assert pta_res["operating_rate_pct"] == 83.30

    # 2. PVC 2 月月度产量 189 万吨
    pvc_text = """
    截至目前PVC有效产能为2706万吨。2024年2月国内PVC产量189万吨，环比降低5.97%，同比增加7.39%。
    PVC整体开工负荷率达到了80.28%，环比微增。
    上周国内PVC社会库存58.71万吨。
    """
    pvc_res = parse_commodity_weekly_metrics(pvc_text, "聚氯乙烯", "V")
    assert pvc_res["weekly_output_w_tons"] is None  # 189 是月产，不能当周产
    assert pvc_res["operating_rate_pct"] == 80.28
    assert pvc_res["factory_inventory_w_tons"] == 58.71

    # 3. 甲醇 2 月预估产量 675 万吨
    ma_text = """
    2月份，考虑到2月29天且部分装置稳定运行，预估2月份国内甲醇产量在675万吨。
    港口库存86.95万吨。
    """
    ma_res = parse_commodity_weekly_metrics(ma_text, "甲醇", "MA")
    assert ma_res["weekly_output_w_tons"] is None  # 675 是月产
    assert ma_res["factory_inventory_w_tons"] == 86.95


def test_parse_commodity_weekly_metrics_anti_misparse_downstream() -> None:
    """验证大宗商品周度解析器严格排除下游聚酯、醋酸等开工率污染。"""
    from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
        parse_commodity_weekly_metrics,
    )

    # 1. 甲醇研报中包含下游醋酸开工 96.68%
    ma_text = """
    下游需求方面：国内醋酸开工：本周96.68%，上周96%。预计节后开工将逐步回升。
    截至2月28日，中国甲醇港口样本库存量：71.50万吨。
    """
    ma_res = parse_commodity_weekly_metrics(ma_text, "甲醇", "MA")
    assert ma_res["operating_rate_pct"] is None  # 醋酸 96.68% 绝不能作为甲醇开工
    assert ma_res["factory_inventory_w_tons"] == 71.50

    # 2. 乙二醇研报中包含下游聚酯负荷 90%
    meg_text = """
    需求端，三季度开始聚酯负荷维持在 90%附近高位。
    截至1月11日当周，乙二醇开工率59.67%，周环比微降。
    华东主港库存98.70万吨。
    """
    meg_res = parse_commodity_weekly_metrics(meg_text, "乙二醇", "MEG")
    assert meg_res["operating_rate_pct"] == 59.67  # 抓取乙二醇自身，绝不抓聚酯 90%
    assert meg_res["factory_inventory_w_tons"] == 98.70


def test_parse_commodity_weekly_metrics_valid_weekly_output() -> None:
    """验证真实的周度产量与开工率被精准召回。"""
    from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
        parse_commodity_weekly_metrics,
    )

    v_text = """
    据隆众统计，截至1月26日当周，PVC周度产量为45.56万吨，环比减少0.9万吨。
    PVC行业开工率为79.97%。
    """
    v_res = parse_commodity_weekly_metrics(v_text, "聚氯乙烯", "V")
    assert v_res["weekly_output_w_tons"] == 45.56
    assert v_res["operating_rate_pct"] == 79.97


def test_parse_commodity_weekly_metrics_mysteel_actual_samples() -> None:
    """验证从 Mysteel 真实周评与周度分析文章文本中准确提取多品种指标。"""
    from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
        parse_commodity_weekly_metrics,
    )

    # 1. PTA 周评：包含周产量、利用率与社会库存
    pta_html = """
    <div>
    <p>1、本周期国内PTA周产量128.12万吨，较上周3.24 万吨；</p>
    <p>2、本周期国内PTA周产能利用率66.69%，较上周+1.70%；</p>
    <p>3、本周期聚酯行业周度平均开工77.69%，较上周-0.38%；</p>
    <p>4、本周PTA社会库存量约在320.37万吨，环比-5.65万吨；</p>
    </div>
    """
    ta_res = parse_commodity_weekly_metrics(pta_html, "精对苯二甲酸", "TA")
    assert ta_res["weekly_output_w_tons"] == 128.12
    assert ta_res["operating_rate_pct"] == 66.69
    assert ta_res["factory_inventory_w_tons"] == 320.37

    # 2. 乙二醇周评：冒号修饰词与华东主港库存
    meg_text = """
    1、本周关注点：本周国内乙二醇产量：40.10万吨，较上周增加0.28万吨，环比升0.70%；
    本周乙二醇产能利用率:61.89%，环比升0.42%;
    本周乙二醇华东主港库存：11.4万吨，环比降2.56%；
    本周乙二醇主要下游聚酯产能利用率73.99%。
    """
    meg_res = parse_commodity_weekly_metrics(meg_text, "乙二醇", "MEG")
    assert meg_res["weekly_output_w_tons"] == 40.10
    assert meg_res["operating_rate_pct"] == 61.89
    assert meg_res["factory_inventory_w_tons"] == 11.4

    # 3. 甲醇产量与利用率：吨到万吨单位转换与装置利用率
    ma_text = """
    一、产量及产能利用率趋势定性分析
    本周(20260911-0917)中国甲醇产量为1893285吨，较上周增加20650吨；
    装置产能利用率为83.80%，环比+1.10%。
    """
    ma_res = parse_commodity_weekly_metrics(ma_text, "甲醇", "MA")
    assert ma_res["weekly_output_w_tons"] == 189.33
    assert ma_res["operating_rate_pct"] == 83.80

    # 4. PVC 社会库存：全角括号地域说明
    pvc_text = """
    隆众数据显示，截止9月17日本周PVC（华东+华南）社会库存在108.47万吨，环比减少1.84%。
    """
    pvc_res = parse_commodity_weekly_metrics(pvc_text, "聚氯乙烯", "V")
    assert pvc_res["factory_inventory_w_tons"] == 108.47
