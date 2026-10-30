"""验证大商所 (DCE) 仓单解析器与 2-Tier 物化流程。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.chemicals.collectors.futures_price import (
    CHEMICAL_FUTURES_CONTRACTS,
)
from stock_data.fetcher.industry.chemicals.collectors.inventory import (
    CHEMICAL_FUTURES_SYMBOLS,
    FuturesInventoryCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.official import (
    DCE_LISTING_DATES,
    DEFAULT_DCE_INVENTORY_COMMODITIES,
    parse_dce_inventory_text,
)

SAMPLE_DCE_INVENTORY_TEXT = """
大连商品交易所指定交割仓库仓单日报
日期：2026年09月15日

品种：乙二醇
仓库/分库 昨日仓单量 今日仓单量 增减
张家港保税港区 1200 1500 300
太仓阳鸿石化 800 800 0
总计 2000 2300 300

品种：聚氯乙烯
天津港物流 500 500 0
上海金山仓 100 80 -20
总计 600 580 -20

品种：苯乙烯
常州华润 400 400 0
总计 400 400 0

品种：聚丙烯
广州石化 150 150 0
总计 150 150 0

品种：线型低密度聚乙烯
中石化华北 300 350 50
总计 300 350 50
"""

SAMPLE_DCE_INVENTORY_HTML = """
<html>
<body>
<table>
  <tr><td colspan="4">大连商品交易所仓单日报 2026-09-15</td></tr>
  <tr><td>品种：乙二醇</td></tr>
  <tr><td>仓库</td><td>昨日仓单量</td><td>今日仓单量</td><td>增减</td></tr>
  <tr><td>仓库A</td><td>1000</td><td>1200</td><td>200</td></tr>
  <tr><td>总计</td><td>1000</td><td>1200</td><td>200</td></tr>
  <tr><td>品种：聚氯乙烯</td></tr>
  <tr><td>仓库B</td><td>500</td><td>500</td><td>0</td></tr>
  <tr><td>小计</td><td>500</td><td>500</td><td>0</td></tr>
</table>
</body>
</html>
"""


def test_dce_symbols_registered() -> None:
    """验证大商所核心品种在仓单与行情配置中完整注册。"""
    assert "EG" in CHEMICAL_FUTURES_SYMBOLS
    assert CHEMICAL_FUTURES_SYMBOLS["EG"]["name"] == "乙二醇"
    assert CHEMICAL_FUTURES_SYMBOLS["EG"]["exchange"] == "DCE"

    assert "V" in CHEMICAL_FUTURES_SYMBOLS
    assert CHEMICAL_FUTURES_SYMBOLS["V"]["exchange"] == "DCE"

    assert "EB" in CHEMICAL_FUTURES_SYMBOLS
    assert CHEMICAL_FUTURES_SYMBOLS["EB"]["exchange"] == "DCE"

    # 行情配置包含 EG
    assert "EG" in CHEMICAL_FUTURES_CONTRACTS
    assert CHEMICAL_FUTURES_CONTRACTS["EG"]["main_contract"] == "EG0"
    assert CHEMICAL_FUTURES_CONTRACTS["EG"]["exchange"] == "DCE"

    # 上市日期包含 EG
    assert "EG" in DCE_LISTING_DATES
    assert DCE_LISTING_DATES["EG"] == date(2018, 12, 10)


def test_parse_dce_inventory_plain_text() -> None:
    """测试解析大商所纯文本格式仓单日报。"""
    res = parse_dce_inventory_text(SAMPLE_DCE_INVENTORY_TEXT)
    assert res["EG"] == (2300.0, 300.0)
    assert res["V"] == (580.0, -20.0)
    assert res["EB"] == (400.0, 0.0)
    assert res["PP"] == (150.0, 0.0)
    assert res["L"] == (350.0, 50.0)


def test_parse_dce_inventory_html() -> None:
    """测试解析大商所 HTML 表格格式仓单日报。"""
    res = parse_dce_inventory_text(SAMPLE_DCE_INVENTORY_HTML)
    assert res["EG"] == (1200.0, 200.0)
    assert res["V"] == (500.0, 0.0)


def test_parse_dce_inventory_empty_handling() -> None:
    """测试空文本与无效输入安全返回。"""
    assert parse_dce_inventory_text("") == dict.fromkeys(
        DEFAULT_DCE_INVENTORY_COMMODITIES, (None, None)
    )
    assert parse_dce_inventory_text("   \n\t  ") == dict.fromkeys(
        DEFAULT_DCE_INVENTORY_COMMODITIES, (None, None)
    )


def test_futures_inventory_collector_backfill_dce(tmp_path: Path) -> None:
    """测试 FuturesInventoryCollector 从本地 dce 缓存成功回填 RAW CSV。"""
    raw_dir = tmp_path
    dce_cache_dir = raw_dir / "chemicals" / "futures_inventory" / "dce" / "2026"
    dce_cache_dir.mkdir(parents=True, exist_ok=True)

    snapshot_file = dce_cache_dir / "20260915.txt"
    snapshot_file.write_text(SAMPLE_DCE_INVENTORY_TEXT, encoding="utf-8")

    collector = FuturesInventoryCollector(raw_dir=raw_dir)
    summary, fetched = collector.backfill_dce_raw()

    assert "EG" in summary
    assert summary["EG"] >= 1
    assert "V" in summary
    assert summary["V"] >= 1
    assert "EG:2026-09-15" in fetched
    assert "V:2026-09-15" in fetched

    # 验证生成的 EG.csv 内容
    eg_csv = raw_dir / "chemicals" / "futures_inventory" / "EG.csv"
    assert eg_csv.exists()
    content = eg_csv.read_text(encoding="utf-8")
    assert "2026-09-15,EG,乙二醇" in content
    assert "2300.0,300.0" in content
