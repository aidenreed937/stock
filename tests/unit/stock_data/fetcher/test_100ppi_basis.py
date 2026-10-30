"""生意社 100ppi 每日现期基差采集器与解析器单元测试。"""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.basis import (
    SpotFuturesBasisCollector,
)
from stock_data.fetcher.industry.chemicals.parsers.basis_table import (
    parse_100ppi_basis_html,
)
from stock_data.fetcher.industry.chemicals.transforms.basis import (
    materialize_basis_records_to_curated,
)

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>2026年03月05日商品现货与期货价格对比表</title></head>
<body>
<table width="100%" id="fdata">
  <tr>
    <td rowspan="2"><strong>商品</strong></td>
    <td><strong>现货 </strong></td>
    <td colspan="3"><strong>最近合约</strong></td>
    <td colspan="3"><strong>主力合约</strong></td>
  </tr>
  <tr>
    <td>价格 </td>
    <td>代码 </td>
    <td>价格 </td>
    <td>现期差1</td>
    <td>代码 </td>
    <td>价格 </td>
    <td>现期差2</td>
  </tr>
  <tr><td colspan="8">上海期货交易所</td></tr>
  <tr>
    <td>铜</td>
    <td>101608.33</td>
    <td>2603</td>
    <td>100870</td>
    <td><table><tr><td>738</td><td>0.73%</td></tr></table></td>
    <td>2604</td>
    <td>101080</td>
    <td><table><tr><td>528</td><td>0.52%</td></tr></table></td>
  </tr>
  <tr><td colspan="8">郑州商品交易所</td></tr>
  <tr>
    <td>PTA</td>
    <td>5702.43</td>
    <td>2603</td>
    <td>6002</td>
    <td><table><tr><td>-300</td><td>-4.99%</td></tr></table></td>
    <td>2605</td>
    <td>5820</td>
    <td><table><tr><td>-117</td><td>-2.05%</td></tr></table></td>
  </tr>
  <tr>
    <td>纯碱</td>
    <td>1202.86</td>
    <td>2603</td>
    <td>1204</td>
    <td><table><tr><td>-1.14</td><td>-0.09%</td></tr></table></td>
    <td>2605</td>
    <td>1225</td>
    <td><table><tr><td>-22.14</td><td>-1.81%</td></tr></table></td>
  </tr>
  <tr>
    <td>玻璃</td>
    <td>13.38</td>
    <td>2603</td>
    <td>972</td>
    <td><table><tr><td>98</td><td>10.0%</td></tr></table></td>
    <td>2605</td>
    <td>1055</td>
    <td><table><tr><td>15</td><td>1.40%</td></tr></table></td>
  </tr>
  <tr><td colspan="8">大连商品交易所</td></tr>
  <tr>
    <td>乙二醇</td>
    <td>4041.67</td>
    <td>2603</td>
    <td>3874</td>
    <td><table><tr><td>167</td><td>4.31%</td></tr></table></td>
    <td>2605</td>
    <td>4184</td>
    <td><table><tr><td>-142</td><td>-3.51%</td></tr></table></td>
  </tr>
</table>
</body>
</html>
"""


def test_parse_100ppi_basis_html() -> None:
    """测试从 100ppi 静态 HTML 表格中提取现期基差记录。"""
    t_date = datetime.date(2026, 3, 5)
    records = parse_100ppi_basis_html(SAMPLE_HTML, t_date)

    assert len(records) == 5
    symbols = {r.symbol: r for r in records}

    # 1. 验证 PTA
    assert "TA" in symbols
    pta = symbols["TA"]
    assert pta.product_name == "PTA"
    assert pta.spot_price_cny == 5702.43
    assert pta.near_contract == "2603"
    assert pta.near_contract_price == 6002.0
    assert pta.dom_contract == "2605"
    assert pta.dom_contract_price == 5820.0
    assert pta.basis_cny == -117.0
    assert pta.basis_rate_pct == -2.05
    assert pta.unit == "元/吨"

    # 2. 验证纯碱与玻璃单位
    assert "SA" in symbols
    assert symbols["SA"].spot_price_cny == 1202.86

    assert "FG" in symbols
    assert symbols["FG"].spot_price_cny == 13.38
    assert symbols["FG"].unit == "元/㎡"

    # 3. 验证品种过滤
    filtered = parse_100ppi_basis_html(SAMPLE_HTML, t_date, target_symbols={"TA", "MEG"})
    assert len(filtered) == 2
    f_syms = {r.symbol for r in filtered}
    assert f_syms == {"TA", "MEG"}


def test_collector_cache_and_waf_cookie() -> None:
    """测试采集器本地缓存与 HW_CHECK 自动质询响应。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        collector = SpotFuturesBasisCollector(raw_dir=tmp_dir)
        t_date = datetime.date(2026, 3, 5)

        # 1. 模拟网络响应触发 HW_CHECK 挑战，并在重发时返回真实 HTML
        mock_resp_challenge = MagicMock()
        mock_resp_challenge.status_code = 200
        mock_resp_challenge.text = """
        <html><body><script>
        var _0x2 = "fake_waf_token_123456";
        document.cookie = "HW_CHECK=" + _0x2;
        </script>正在进行安全检查</body></html>
        """

        mock_resp_real = MagicMock()
        mock_resp_real.status_code = 200
        mock_resp_real.text = SAMPLE_HTML

        collector.session.get = MagicMock(side_effect=[mock_resp_challenge, mock_resp_real])  # type: ignore

        snapshot_path, content = collector.download_daily_html(t_date)

        assert snapshot_path is not None
        assert snapshot_path.exists()
        assert content is not None
        assert "PTA" in content
        assert collector.session.cookies.get("HW_CHECK") == "fake_waf_token_123456"

        # 2. 再次读取时应命中缓存，不再发起网络请求
        collector.session.get.reset_mock()
        snap2, c2 = collector.download_daily_html(t_date)
        assert snap2 == snapshot_path
        assert c2 == content
        collector.session.get.assert_not_called()


def test_materialize_basis_records_to_curated() -> None:
    """测试基差记录物化至 chemical_futures_basis 与 chemical_spot_price。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        c_dir = Path(tmp_dir)

        # 预制旧版 chemical_spot_price
        old_spot = pl.DataFrame(
            {
                "trade_date": [datetime.date(2026, 3, 4)],
                "product_name": ["PTA"],
                "symbol": ["TA"],
                "spot_price_cny": [5650.0],
                "spec": ["优等品"],
                "region": ["国内"],
                "unit": ["元/吨"],
                "source": ["100ppi"],
                "source_url": ["https://example.com"],
                "release_date": [datetime.date(2026, 3, 4)],
                "data_status": ["spot_benchmark"],
                "collected_at": ["2026-03-04T00:00:00Z"],
            }
        )
        old_spot.write_parquet(c_dir / "chemical_spot_price.parquet")

        t_date = datetime.date(2026, 3, 5)
        records = parse_100ppi_basis_html(SAMPLE_HTML, t_date)

        _spot_inc, total_basis = materialize_basis_records_to_curated(
            records=records,
            curated_dir=c_dir,
            update_spot_price=True,
        )

        assert total_basis == 5
        # 验证文件物理落盘
        assert (c_dir / "chemical_futures_basis.parquet").exists()
        assert (c_dir / "chemical_futures_basis.csv").exists()
        assert (c_dir / "chemical_spot_price.parquet").exists()

        basis_df = pl.read_parquet(c_dir / "chemical_futures_basis.parquet")
        assert len(basis_df) == 5
        assert "basis_rate_pct" in basis_df.columns
        assert "dom_contract" in basis_df.columns

        spot_df = pl.read_parquet(c_dir / "chemical_spot_price.parquet")
        # 原有 1 行 + 新增 5 行 = 6 行
        assert len(spot_df) == 6
        assert "TA" in spot_df.get_column("symbol").to_list()

        # 验证幂等性：重复物化相同记录行数不变
        s_inc2, t_basis2 = materialize_basis_records_to_curated(
            records=records,
            curated_dir=c_dir,
            update_spot_price=True,
        )
        assert s_inc2 == 0
        assert t_basis2 == 5
