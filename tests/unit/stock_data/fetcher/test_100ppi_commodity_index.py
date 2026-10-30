"""生意社 100ppi 商品定基指数采集、解析与物化单元测试。"""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.commodity_index import (
    CommodityIndexCollector,
)
from stock_data.fetcher.industry.chemicals.parsers.commodity_index import (
    CommodityIndexRow,
    parse_100ppi_ptrade_html,
)
from stock_data.fetcher.industry.chemicals.transforms.commodity_index import (
    materialize_commodity_index_to_curated,
)

SAMPLE_PTRADE_HTML = """
<!DOCTYPE html>
<html>
<head><title>PX商品指数表 - 生意社</title></head>
<body>
<center>
<table width="60%" border="1" cellspacing="1" cellpadding="0">
  <tr>
    <th>日期</th>
    <th>数值</th>
    <th>较前日涨跌幅</th>
    <th>↑↓</th>
    <th>累积增长点数</th>
    <th>累积涨幅</th>
  </tr>
  <tr>
    <td>2026-09-17</td>
    <td>76.80</td>
    <td>0.00%</td>
    <td>→</td>
    <td>6.40</td>
    <td>9.09%</td>
  </tr>
  <tr>
    <td>2026-09-11</td>
    <td>76.80</td>
    <td>6.67%</td>
    <td>↑</td>
    <td>6.40</td>
    <td>9.09%</td>
  </tr>
  <tr>
    <td>2026-09-10</td>
    <td>72.00</td>
    <td>-1.25%</td>
    <td>↓</td>
    <td>1.60</td>
    <td>-2.27%</td>
  </tr>
</table>
</center>
</body>
</html>
"""


def test_parse_100ppi_ptrade_html_normal() -> None:
    """测试正常 HTML 表格解析与字段转换。"""
    records = parse_100ppi_ptrade_html(
        html_text=SAMPLE_PTRADE_HTML,
        ppid=968,
        symbol="PX",
        product_name="对二甲苯(PX)",
    )
    assert len(records) == 3

    r0 = records[0]
    assert r0.trade_date == datetime.date(2026, 9, 17)
    assert r0.ppid == 968
    assert r0.symbol == "PX"
    assert r0.product_name == "对二甲苯(PX)"
    assert r0.ci_value == 76.80
    assert r0.pct_change_1d == 0.0
    assert r0.direction == "FLAT"
    assert r0.cumulative_points == 6.40
    assert r0.cumulative_change_pct == 0.0909
    assert r0.source == "100ppi_cindex"

    r1 = records[1]
    assert r1.trade_date == datetime.date(2026, 9, 11)
    assert r1.pct_change_1d == 0.0667
    assert r1.direction == "UP"

    r2 = records[2]
    assert r2.trade_date == datetime.date(2026, 9, 10)
    assert r2.pct_change_1d == -0.0125
    assert r2.direction == "DOWN"
    assert r2.cumulative_change_pct == -0.0227


def test_parse_100ppi_ptrade_html_empty_and_corrupted() -> None:
    """测试异常 HTML 容错处理。"""
    assert parse_100ppi_ptrade_html("", 968, "PX", "PX") == []
    assert parse_100ppi_ptrade_html("<html><body>无表格</body></html>", 968, "PX", "PX") == []
    corrupted = "<table><tr><th>只有一个表头</th></tr></table>"
    assert parse_100ppi_ptrade_html(corrupted, 968, "PX", "PX") == []


def test_collector_cache_first() -> None:
    """测试本地缓存命中时不发起网络请求。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        raw_dir = Path(tmp_dir)
        cindex_dir = raw_dir / "100ppi_cindex"
        cindex_dir.mkdir(parents=True)

        test_date = datetime.date(2026, 9, 18)
        cache_file = cindex_dir / f"ptrade-968-{test_date.isoformat()}.html"
        cache_file.write_text(SAMPLE_PTRADE_HTML, encoding="utf-8")

        mock_session = MagicMock()
        collector = CommodityIndexCollector(raw_dir=raw_dir, session=mock_session)

        # 执行下载
        snapshot_path, content = collector.download_ptrade_html(
            ppid=968, fetch_date=test_date, force=False
        )

        assert snapshot_path == cache_file
        assert content == SAMPLE_PTRADE_HTML
        # 确保网络请求未触发
        mock_session.get.assert_not_called()


def test_collector_hw_check_cookie_injection() -> None:
    """测试 WAF HW_CHECK Cookie 质询自适应注入流程。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        raw_dir = Path(tmp_dir)
        test_date = datetime.date(2026, 9, 18)

        waf_challenge_html = """
        <html><body>
        <script>
        (function(_0x1){
            var _0x2 = "token_abc123xyz";
            document.cookie = "HW_CHECK=" + _0x2;
        })();
        </script>
        </body></html>
        """

        mock_session = MagicMock()
        mock_cookies = MagicMock()
        mock_session.cookies = mock_cookies

        # 第一次返回质询，第二次返回真实内容
        resp_waf = MagicMock(status_code=200, text=waf_challenge_html)
        resp_data = MagicMock(status_code=200, text=SAMPLE_PTRADE_HTML)
        mock_session.get.side_effect = [resp_waf, resp_data]

        collector = CommodityIndexCollector(raw_dir=raw_dir, session=mock_session)
        snapshot_path, content = collector.download_ptrade_html(
            ppid=968, fetch_date=test_date, force=True
        )

        assert snapshot_path is not None
        assert snapshot_path.exists()
        assert content == SAMPLE_PTRADE_HTML
        # 验证 Cookie 注入
        mock_cookies.set.assert_called_with("HW_CHECK", "token_abc123xyz", domain=".100ppi.com")
        assert mock_session.get.call_count == 2


def test_materialize_commodity_index_idempotency() -> None:
    """测试商品定基指数 Curated 黄金事实表物化与主键幂等合并。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        curated_dir = Path(tmp_dir)

        # 第 1 批数据：PX 两个交易日
        batch1 = [
            CommodityIndexRow(
                trade_date=datetime.date(2026, 9, 17),
                ppid=968,
                symbol="PX",
                product_name="对二甲苯",
                ci_value=76.80,
                pct_change_1d=0.0,
                direction="FLAT",
                cumulative_points=6.40,
                cumulative_change_pct=0.0909,
            ),
            CommodityIndexRow(
                trade_date=datetime.date(2026, 9, 16),
                ppid=968,
                symbol="PX",
                product_name="对二甲苯",
                ci_value=76.80,
                pct_change_1d=0.0,
                direction="FLAT",
                cumulative_points=6.40,
                cumulative_change_pct=0.0909,
            ),
        ]

        net_added1, total1 = materialize_commodity_index_to_curated(batch1, curated_dir=curated_dir)
        assert net_added1 == 2
        assert total1 == 2

        out_file = curated_dir / "chemical_commodity_index.parquet"
        assert out_file.exists()

        df1 = pl.read_parquet(out_file)
        assert len(df1) == 2
        assert set(df1.columns) == {
            "trade_date",
            "ppid",
            "symbol",
            "product_name",
            "ci_value",
            "pct_change_1d",
            "direction",
            "cumulative_points",
            "cumulative_change_pct",
            "source",
            "source_url",
            "collected_at",
        }

        # 第 2 批数据：包含 1 条重叠 (9-17 更新值) + 1 条新日期 (9-18) + 1 条新品种 POY (9-17)
        batch2 = [
            CommodityIndexRow(
                trade_date=datetime.date(2026, 9, 17),
                ppid=968,
                symbol="PX",
                product_name="对二甲苯",
                ci_value=77.00,  # 数值被修正更新
                pct_change_1d=0.0026,
                direction="UP",
                cumulative_points=6.60,
                cumulative_change_pct=0.0938,
            ),
            CommodityIndexRow(
                trade_date=datetime.date(2026, 9, 18),
                ppid=968,
                symbol="PX",
                product_name="对二甲苯",
                ci_value=77.50,
                pct_change_1d=0.0065,
                direction="UP",
                cumulative_points=7.10,
                cumulative_change_pct=0.1008,
            ),
            CommodityIndexRow(
                trade_date=datetime.date(2026, 9, 17),
                ppid=1006,
                symbol="POY",
                product_name="涤纶长丝POY",
                ci_value=63.12,
                pct_change_1d=0.0094,
                direction="UP",
                cumulative_points=5.94,
                cumulative_change_pct=0.1039,
            ),
        ]

        net_added2, total2 = materialize_commodity_index_to_curated(batch2, curated_dir=curated_dir)
        # 原有 2 条，其中 (2026-09-17, 968) 覆盖更新，新增 (2026-09-18, 968) 与 (2026-09-17, 1006)，净增 2 条，总计 4 条
        assert net_added2 == 2
        assert total2 == 4

        df2 = pl.read_parquet(out_file)
        assert len(df2) == 4

        # 检查重叠键的最新值是否被成功更新为 77.00
        px_17 = df2.filter(
            (pl.col("trade_date") == datetime.date(2026, 9, 17)) & (pl.col("ppid") == 968)
        )
        assert px_17["ci_value"][0] == 77.00
        assert px_17["direction"][0] == "UP"
