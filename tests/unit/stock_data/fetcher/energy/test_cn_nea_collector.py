"""国家能源局 (NEA) 电力数据采集与解析单元测试。"""

from datetime import date
from pathlib import Path
from unittest.mock import patch

import polars as pl

from stock_data.fetcher.energy.cn_nea import (
    CnNeaCollector,
    NeaDiffEngine,
    NeaPowerTableParser,
)
from stock_data.fetcher.energy.taxonomy import EnergyProduct

SAMPLE_NEA_TABLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>国家能源局发布2025年1-11月份全国电力工业统计数据</title>
</head>
<body>
    <h1>国家能源局发布2025年1-11月份全国电力工业统计数据</h1>
    <div class="time">发布时间：2025-12-26 来源：国家能源局</div>
    <p>12月26日，国家能源局发布1-11月份全国电力工业统计数据。截至11月底，全国累计发电装机容量37.9亿千瓦，同比增长17.1%。其中，太阳能发电装机容量11.6亿千瓦，同比增长41.9%；风电装机容量6.0亿千瓦，同比增长22.4%。</p>
    <table>
        <tr>
            <th>指 标 名 称</th>
            <th>单位</th>
            <th>1-11月累计</th>
            <th>同比增长（%）</th>
        </tr>
        <tr>
            <td>全国发电装机容量</td>
            <td>万千瓦</td>
            <td>379000</td>
            <td>17.1</td>
        </tr>
        <tr>
            <td>其中：水电</td>
            <td>万千瓦</td>
            <td>43500</td>
            <td>3.2</td>
        </tr>
        <tr>
            <td>火电</td>
            <td>万千瓦</td>
            <td>145000</td>
            <td>3.5</td>
        </tr>
        <tr>
            <td>核电</td>
            <td>万千瓦</td>
            <td>5800</td>
            <td>2.1</td>
        </tr>
        <tr>
            <td>风电</td>
            <td>万千瓦</td>
            <td>60000</td>
            <td>22.4*</td>
        </tr>
        <tr>
            <td>太阳能发电</td>
            <td>万千瓦</td>
            <td>116000</td>
            <td>41.9</td>
        </tr>
        <tr>
            <td>全国发电设备累计平均利用小时</td>
            <td>小时</td>
            <td>2858</td>
            <td>-289*</td>
        </tr>
        <tr>
            <td>电源工程投资完成</td>
            <td>亿元</td>
            <td>8200</td>
            <td>12.5</td>
        </tr>
        <tr>
            <td>电网工程投资完成</td>
            <td>亿元</td>
            <td>5100</td>
            <td>15.8▲</td>
        </tr>
    </table>
</body>
</html>
"""

SAMPLE_NEA_TEXT_ONLY_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>国家能源局发布2026年1-6月份全国电力统计数据</title>
</head>
<body>
    <h2>国家能源局发布2026年1-6月份全国电力统计数据</h2>
    <div class="info">发布时间：2026-07-22</div>
    <p>7月22日，国家能源局发布1-6月份全国电力统计数据。截至6月底，全国累计发电装机容量40.4亿千瓦，同比增长10.8%。其中，太阳能发电装机容量12.7亿千瓦，同比增长15.8%；风电装机容量6.8亿千瓦，同比增长18.5%。</p>
    <p>1-6月份，全国主要发电企业电源工程完成投资3600亿元，同比增长8.2%。电网工程完成投资2500亿元，同比增长12.3%。</p>
</body>
</html>
"""


def test_parse_html_table() -> None:
    """测试国家能源局通报 HTML 表格结构化解析。"""
    parsed = NeaPowerTableParser.parse_html(
        SAMPLE_NEA_TABLE_HTML, source_url="https://www.nea.gov.cn/sample1.htm"
    )
    assert parsed is not None
    assert parsed["period"] == "2025-11"
    assert parsed["month"] == 11
    assert parsed["release_date"] == date(2025, 12, 26)

    indicators = parsed["indicators"]
    assert "全国发电装机容量" in indicators
    assert indicators["全国发电装机容量"]["cumulative_value"] == 379000.0
    assert indicators["全国发电装机容量"]["yoy_growth"] == 0.171

    assert "太阳能发电" in indicators
    assert indicators["太阳能发电"]["cumulative_value"] == 116000.0
    assert indicators["太阳能发电"]["yoy_growth"] == 0.419

    assert "风电" in indicators
    assert indicators["风电"]["cumulative_value"] == 60000.0

    assert "全国发电设备累计平均利用小时" in indicators
    assert indicators["全国发电设备累计平均利用小时"]["cumulative_value"] == 2858.0

    assert "电网工程投资完成" in indicators
    assert indicators["电网工程投资完成"]["cumulative_value"] == 5100.0


def test_parse_fallback_text() -> None:
    """测试无表格纯文本通报正则降级提取。"""
    parsed = NeaPowerTableParser.parse_html(
        SAMPLE_NEA_TEXT_ONLY_HTML, source_url="https://www.nea.gov.cn/sample2.htm"
    )
    assert parsed is not None
    assert parsed["period"] == "2026-06"
    assert parsed["month"] == 6
    assert parsed["release_date"] == date(2026, 7, 22)

    indicators = parsed["indicators"]
    assert "全国发电装机容量" in indicators
    assert (
        indicators["全国发电装机容量"]["cumulative_value"] == 404000.0
    )  # 40.4 亿千瓦 = 404000 万千瓦
    assert indicators["全国发电装机容量"]["yoy_growth"] == 0.108

    assert "太阳能发电" in indicators
    assert indicators["太阳能发电"]["cumulative_value"] == 127000.0  # 12.7 亿千瓦
    assert indicators["太阳能发电"]["yoy_growth"] == 0.158

    assert "风电" in indicators
    assert indicators["风电"]["cumulative_value"] == 68000.0  # 6.8 亿千瓦

    assert "电网工程投资完成" in indicators
    assert indicators["电网工程投资完成"]["cumulative_value"] == 2500.0


def test_diff_engine() -> None:
    """测试月度差分引擎。"""
    bulletin_10 = {
        "period": "2025-10",
        "month": 10,
        "indicators": {
            "太阳能发电": {"cumulative_value": 110000.0, "unit": "万千瓦", "yoy_growth": 0.40},
            "风电": {"cumulative_value": 58000.0, "unit": "万千瓦", "yoy_growth": 0.20},
            "电网工程投资完成": {"cumulative_value": 4500.0, "unit": "亿元"},
        },
    }
    bulletin_11 = {
        "period": "2025-11",
        "month": 11,
        "indicators": {
            "太阳能发电": {"cumulative_value": 116000.0, "unit": "万千瓦", "yoy_growth": 0.419},
            "风电": {"cumulative_value": 60000.0, "unit": "万千瓦", "yoy_growth": 0.224},
            "电网工程投资完成": {"cumulative_value": 5100.0, "unit": "亿元"},
        },
    }

    diff_list = NeaDiffEngine.calculate_monthly_diff([bulletin_10, bulletin_11])
    assert len(diff_list) == 2

    diff_11 = diff_list[1]
    computed = diff_11["computed_metrics"]

    # 11月太阳能累计装机: 116000 万千瓦 = 1160 GW
    assert computed["太阳能发电_cum_gw"] == 1160.0
    # 11月太阳能当月新增: (116000 - 110000) * 0.01 = 60 GW
    assert computed["太阳能发电_new_gw"] == 60.0
    # 11月风电当月新增: (60000 - 58000) * 0.01 = 20 GW
    assert computed["风电_new_gw"] == 20.0
    # 11月电网工程单月投资: 5100 - 4500 = 600 亿元
    assert computed["电网工程投资完成_monthly_billion_cny"] == 600.0


def test_collector_end_to_end(tmp_path: Path) -> None:
    """测试 CnNeaCollector 端到端采集与 Parquet 落盘。"""
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"

    collector = CnNeaCollector(raw_dir=raw_dir, curated_dir=curated_dir)

    # Mock 爬虫返回 HTML 快照
    mock_snapshots = [
        {
            "period": "2025-11",
            "url": "https://www.nea.gov.cn/sample1.htm",
            "html_content": SAMPLE_NEA_TABLE_HTML,
            "collected_at": "2026-08-31T00:00:00Z",
        }
    ]

    with patch.object(collector.crawler, "fetch_bulletins", return_value=mock_snapshots):
        records = collector.collect()
        assert len(records["capacity"]) > 0
        assert len(records["generation"]) > 0

        # 执行落盘
        counts = collector.collect_and_save()
        assert counts["global_renewable_capacity"] > 0
        assert counts["global_power_generation"] > 0

        # 检查 Parquet 文件
        p_cap = curated_dir / "global_renewable_capacity.parquet"
        p_gen = curated_dir / "global_power_generation.parquet"
        assert p_cap.exists()
        assert p_gen.exists()

        df_cap = pl.read_parquet(p_cap)
        solar_row = df_cap.filter(
            (pl.col("geo_code") == "CHN") & (pl.col("technology") == EnergyProduct.SOLAR_PV)
        )
        assert solar_row.height == 1
        assert solar_row["capacity_gw"][0] == 1160.0  # 11.6 亿千瓦 = 1160 GW
        assert solar_row["source"][0] == "NEA"
