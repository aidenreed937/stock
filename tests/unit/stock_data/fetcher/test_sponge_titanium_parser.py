from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser


def test_extract_sponge_titanium_range_yuan(tmp_path: Path) -> None:
    """验证海绵钛 (元/吨) 区间解析并计算中位数。"""
    text = """
    【有色/化工周报】
    本周海绵钛市场弱势运行，0#海绵钛主流现货在 45000-46000 元/吨，
    下游军工与民品钛材按需采购为主。
    """
    parser = ResearchReportParser(raw_dir=tmp_path)
    records = parser.extract_prices_from_text(
        text=text,
        publish_date=date(2026, 9, 14),
        source_name="Mysteel_海绵钛周报",
    )

    sponge = [r for r in records if r["symbol"] == "Ti_sponge"]
    assert len(sponge) == 1
    rec = sponge[0]
    assert rec["symbol"] == "Ti_sponge"
    assert rec["product_name"] == "海绵钛"
    assert rec["spot_price_cny"] == 45500.0
    assert rec["unit"] == "元/吨"
    assert rec["release_date"] == date(2026, 9, 14)


def test_extract_sponge_titanium_range_wan_yuan(tmp_path: Path) -> None:
    """验证海绵钛 (万元/吨) 区间解析并正确换算为元/吨。"""
    text = """
    截至9月13日附近，国内海绵钛现货大致在 4.3–4.5万元/吨，
    部分半流程企业面临亏损压力。
    """
    parser = ResearchReportParser(raw_dir=tmp_path)
    records = parser.extract_prices_from_text(
        text=text,
        publish_date=date(2026, 9, 14),
    )

    sponge = [r for r in records if r["symbol"] == "Ti_sponge"]
    assert len(sponge) == 1
    rec = sponge[0]
    assert rec["trade_date"] == date(2026, 9, 13)
    assert rec["spot_price_cny"] == 44000.0
    assert rec["release_date"] == date(2026, 9, 14)


def test_extract_sponge_titanium_single_price(tmp_path: Path) -> None:
    """验证海绵钛单点位报价（包括万元与元单位、品级前缀）。"""
    parser = ResearchReportParser(raw_dir=tmp_path)

    # 万元单值
    text1 = "据调研，目前国内0#海绵钛现货约为 4.5 万元/吨。"
    recs1 = parser.extract_prices_from_text(text=text1, publish_date=date(2026, 9, 11))
    s1 = [r for r in recs1 if r["symbol"] == "Ti_sponge"]
    assert len(s1) == 1
    assert s1[0]["spot_price_cny"] == 45000.0

    # 元单值
    text2 = "1#海绵钛主流出厂价格为 44500 元/吨。"
    recs2 = parser.extract_prices_from_text(text=text2, publish_date=date(2026, 9, 11))
    s2 = [r for r in recs2 if r["symbol"] == "Ti_sponge"]
    assert len(s2) == 1
    assert s2[0]["spot_price_cny"] == 44500.0


def test_sponge_titanium_noise_filtering(tmp_path: Path) -> None:
    """验证涨跌幅度、环比同比以及异常极值被正确过滤。"""
    parser = ResearchReportParser(raw_dir=tmp_path)

    # 涨跌幅噪音
    noise_text = """
    本周海绵钛跌 500 元/吨，市场交投清淡。
    海绵钛环比下跌 1000 元/吨。
    """
    recs = parser.extract_prices_from_text(text=noise_text, publish_date=date(2026, 9, 14))
    assert len([r for r in recs if r["symbol"] == "Ti_sponge"]) == 0

    # 超出边界（正常区间 30000 ~ 100000）
    out_of_bounds_text = """
    特种海绵钛标品 120000 元/吨，超低残次料 15000 元/吨。
    """
    recs_bound = parser.extract_prices_from_text(
        text=out_of_bounds_text, publish_date=date(2026, 9, 14)
    )
    assert len([r for r in recs_bound if r["symbol"] == "Ti_sponge"]) == 0
