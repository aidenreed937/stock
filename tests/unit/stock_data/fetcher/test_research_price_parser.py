from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser


def test_extract_single_point_prices(tmp_path: Path) -> None:
    """验证从券商化工周报文本中提取点位价格（钛精矿、浓硫酸、钛白粉）。"""
    report_text = """
    【基础化工周报】
    本周原料及产品动态：
    攀西钛精矿(46%)价格为 2220 元/吨，较上周持平。
    国内98%浓硫酸价格为 350 元/吨，局部交投平稳。
    金红石型钛白粉出厂价为 14500 元/吨，出口订单相对稳定。
    """
    parser = ResearchReportParser(raw_dir=tmp_path)
    records = parser.extract_prices_from_text(
        text=report_text,
        publish_date=date(2024, 3, 18),
        source_name="中信建投_基础化工周报",
        source_url="https://example.com/report1",
    )

    assert len(records) == 3
    by_symbol = {r["symbol"]: r for r in records}

    assert "ilmenite" in by_symbol
    ilmenite = by_symbol["ilmenite"]
    assert ilmenite["spot_price_cny"] == 2220.0
    assert ilmenite["unit"] == "元/吨"
    assert ilmenite["product_name"] == "钛精矿"
    assert ilmenite["spec"] == "46%;攀西"
    assert ilmenite["release_date"] == date(2024, 3, 18)
    assert ilmenite["source"] == "中信建投_基础化工周报"

    assert "H2SO4" in by_symbol
    acid = by_symbol["H2SO4"]
    assert acid["spot_price_cny"] == 350.0
    assert acid["product_name"] == "硫酸"
    assert acid["spec"] == "98%;工业级浓硫酸"
    assert acid["release_date"] == date(2024, 3, 18)

    assert "TiO2" in by_symbol
    tio2 = by_symbol["TiO2"]
    assert tio2["spot_price_cny"] == 14500.0
    assert tio2["product_name"] == "钛白粉"
    assert tio2["spec"] == "金红石型;硫酸法"
    assert tio2["release_date"] == date(2024, 3, 18)


def test_extract_range_price_ilmenite(tmp_path: Path) -> None:
    """验证钛精矿价格区间解析取中位数（例如 2200-2260 元/吨 -> 2230.0）。"""
    report_text = """
    上游原料：攀西钛精矿在 2200-2260 元/吨，主流大厂挺价意愿强烈。
    """
    parser = ResearchReportParser(raw_dir=tmp_path)
    records = parser.extract_prices_from_text(
        text=report_text,
        publish_date=date(2024, 4, 1),
    )

    assert len(records) == 1
    rec = records[0]
    assert rec["symbol"] == "ilmenite"
    assert rec["spot_price_cny"] == 2230.0


def test_survey_date_and_no_lookahead(tmp_path: Path) -> None:
    """验证正文中调查截止日解析以及 release_date 绑定研报发布日（消灭前视偏差）。"""
    report_text = """
    本周行情跟踪：
    截止到2024年3月15日，攀西钛精矿(46%)价格为 2250 元/吨。
    """
    parser = ResearchReportParser(raw_dir=tmp_path)
    records = parser.extract_prices_from_text(
        text=report_text,
        publish_date=date(2024, 3, 18),
    )

    assert len(records) == 1
    rec = records[0]
    # 正文统计日期是 3月15日
    assert rec["trade_date"] == date(2024, 3, 15)
    assert rec["report_date"] == date(2024, 3, 15)
    # 真实知晓该信息的时间是研报发布日 3月18日
    assert rec["release_date"] == date(2024, 3, 18)


def test_survey_short_date_parsing(tmp_path: Path) -> None:
    """验证短日期（截至3月15日）的正确解析。"""
    report_text = """
    截至3月15日，98%浓硫酸价格为 380 元/吨。
    """
    parser = ResearchReportParser(raw_dir=tmp_path)
    records = parser.extract_prices_from_text(
        text=report_text,
        publish_date=date(2024, 3, 18),
    )

    assert len(records) == 1
    assert records[0]["trade_date"] == date(2024, 3, 15)
    assert records[0]["release_date"] == date(2024, 3, 18)


def test_noise_filtering_and_bounds(tmp_path: Path) -> None:
    """验证异常低/高值以及涨跌幅噪点被正确过滤。"""
    report_text = """
    本周钛精矿跌幅 50 元/吨，浓硫酸跌 20 元/吨。
    某特种高纯硫酸折百 2500 元/吨。
    超低价钛精矿 500 元/吨。
    """
    parser = ResearchReportParser(raw_dir=tmp_path)
    records = parser.extract_prices_from_text(
        text=report_text,
        publish_date=date(2024, 3, 18),
    )
    # 涨跌幅和超范围价格应全被过滤
    assert len(records) == 0


def test_missing_publish_date_returns_empty(tmp_path: Path) -> None:
    """若缺失研报发布日，出于严格 PIT 原则不应提取。"""
    report_text = "攀西钛精矿(46%)价格为 2220 元/吨"
    parser = ResearchReportParser(raw_dir=tmp_path)
    records = parser.extract_prices_from_text(text=report_text, publish_date=None)
    assert records == []


def test_save_prices_to_csv_and_deduplication(tmp_path: Path) -> None:
    """验证价格记录持久化为 CSV，并实现按 (symbol, trade_date) 幂等去重与排序。"""
    parser = ResearchReportParser(raw_dir=tmp_path)
    target_csv = tmp_path / "survey" / "expert_prices.csv"

    batch1 = [
        {
            "trade_date": "2024-03-15",
            "report_date": "2024-03-15",
            "product_name": "钛精矿",
            "symbol": "ilmenite",
            "spec": "46%;攀西",
            "spot_price_cny": 2220.0,
            "unit": "元/吨",
            "source": "Report_A",
            "source_url": "",
            "release_date": "2024-03-18",
            "data_status": "verified_industry_report",
            "collected_at": "2024-03-18T00:00:00Z",
        },
        {
            "trade_date": "2024-03-15",
            "report_date": "2024-03-15",
            "product_name": "硫酸",
            "symbol": "H2SO4",
            "spec": "98%;工业级浓硫酸",
            "spot_price_cny": 350.0,
            "unit": "元/吨",
            "source": "Report_A",
            "source_url": "",
            "release_date": "2024-03-18",
            "data_status": "verified_industry_report",
            "collected_at": "2024-03-18T00:00:00Z",
        },
    ]

    saved_path = parser.save_prices_to_csv(batch1, csv_path=target_csv)
    assert saved_path.exists()

    # 再次保存：包含相同 2024-03-15 ilmenite，以及新一周 2024-03-22 ilmenite
    batch2 = [
        {
            "trade_date": "2024-03-15",
            "report_date": "2024-03-15",
            "product_name": "钛精矿",
            "symbol": "ilmenite",
            "spec": "46%;攀西",
            "spot_price_cny": 2220.0,
            "unit": "元/吨",
            "source": "Report_A_Duplicate",
            "source_url": "",
            "release_date": "2024-03-18",
            "data_status": "verified_industry_report",
            "collected_at": "2024-03-18T00:00:00Z",
        },
        {
            "trade_date": "2024-03-22",
            "report_date": "2024-03-22",
            "product_name": "钛精矿",
            "symbol": "ilmenite",
            "spec": "46%;攀西",
            "spot_price_cny": 2250.0,
            "unit": "元/吨",
            "source": "Report_B",
            "source_url": "",
            "release_date": "2024-03-25",
            "data_status": "verified_industry_report",
            "collected_at": "2024-03-25T00:00:00Z",
        },
    ]

    parser.save_prices_to_csv(batch2, csv_path=target_csv)

    # 读取并验证总共只有 3 条记录（2024-03-15 重复项被去重）
    import csv

    with target_csv.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 3
        # 验证排序与字段正确
        symbols = [r["symbol"] for r in reader]
        assert "H2SO4" in symbols
        assert "ilmenite" in symbols
