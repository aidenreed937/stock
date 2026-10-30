from datetime import date
from pathlib import Path

from scripts.cdp.mysteel_cdp_automation import (
    load_products_config,
    run_collection_for_product,
)

from stock_data.fetcher.industry.chemicals.parsers.mysteel_cdp import (
    parse_mysteel_article,
    parse_mysteel_tables,
)


def test_parse_mysteel_standard_table() -> None:
    """验证从标准 Mysteel 行情表格中提取海绵钛 0# 和 1# 报价。"""
    sample_html = """
    <html>
    <head><title>中国海绵钛市场主流报价_我的钢铁网</title></head>
    <body>
        <div class="time">发布日期: 2026-09-11 10:30:00</div>
        <table class="m-table">
            <thead>
                <tr>
                    <th>品名</th>
                    <th>规格</th>
                    <th>产地/品牌</th>
                    <th>价格(元/吨)</th>
                    <th>涨跌</th>
                    <th>发布日期</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>海绵钛</td>
                    <td>0# (Ti≥99.7%)</td>
                    <td>朝阳金达</td>
                    <td>45500</td>
                    <td>0</td>
                    <td>2026-09-11</td>
                </tr>
                <tr>
                    <td>海绵钛</td>
                    <td>1# (Ti≥99.6%)</td>
                    <td>遵义钛业</td>
                    <td>44500</td>
                    <td>-500</td>
                    <td>2026-09-11</td>
                </tr>
                <tr>
                    <td>钛白粉</td>
                    <td>金红石型</td>
                    <td>龙佰集团</td>
                    <td>14200</td>
                    <td>0</td>
                    <td>2026-09-11</td>
                </tr>
            </tbody>
        </table>
    </body>
    </html>
    """
    quotes = parse_mysteel_tables(
        html=sample_html,
        target_product="海绵钛",
        symbol="Ti_sponge",
        target_specs=["0#", "1#"],
    )

    assert len(quotes) == 2
    q0 = next(q for q in quotes if "0#" in q.spec)
    assert q0.price == 45500.0
    assert q0.product_name == "海绵钛"
    assert q0.trade_date == date(2026, 9, 11)
    assert q0.region == "朝阳金达"

    q1 = next(q for q in quotes if "1#" in q.spec)
    assert q1.price == 44500.0
    assert q1.region == "遵义钛业"


def test_parse_mysteel_range_and_wan_yuan_table() -> None:
    """验证表格中的价格区间中位数以及万元折算。"""
    sample_html = """
    <html>
    <body>
        <table>
            <tr><td>商品</td><td>规格</td><td>区域</td><td>价格(万元/吨)</td><td>日期</td></tr>
            <tr><td>海绵钛</td><td>0#</td><td>国内</td><td>4.5-4.6</td><td>2026-09-15</td></tr>
        </table>
    </body>
    </html>
    """
    quotes = parse_mysteel_tables(
        html=sample_html,
        target_product="海绵钛",
        symbol="Ti_sponge",
    )
    assert len(quotes) == 1
    assert quotes[0].price == 45500.0
    assert quotes[0].trade_date == date(2026, 9, 15)


def test_parse_mysteel_article_text() -> None:
    """验证从无表格的 Mysteel 研报/周评正文中智能抽取点位。"""
    article_html = """
    <html>
    <head><title>本周海绵钛市场盘点</title></head>
    <body>
        <span class="pub-date">2026-09-14 17:00</span>
        <div class="article-content">
            <p>本周国内海绵钛弱势盘整。截至9月13日，国内0#海绵钛出厂价格在 45000-46000 元/吨。</p>
            <p>下游钛材企业拿货谨慎，现货市场交投平淡。</p>
        </div>
    </body>
    </html>
    """
    quotes = parse_mysteel_article(
        html=article_html,
        target_product="海绵钛",
        symbol="Ti_sponge",
        target_specs=["0#"],
    )
    assert len(quotes) == 1
    rec = quotes[0]
    assert rec.price == 45500.0
    assert rec.product_name == "海绵钛"
    assert rec.spec == "0#"
    assert rec.trade_date == date(2026, 9, 13)
    assert rec.release_date == date(2026, 9, 14)


def test_parse_mysteel_article_noise_filtering() -> None:
    """验证正文中的涨跌幅噪点被安全过滤。"""
    article_html = """
    <div class="article-content">
        <p>海绵钛跌 500 元/吨，环比跌幅扩大至 2.5%。</p>
    </div>
    """
    quotes = parse_mysteel_article(
        html=article_html,
        target_product="海绵钛",
        symbol="Ti_sponge",
    )
    assert len(quotes) == 0


def test_products_yaml_loading() -> None:
    """验证 products.yaml 配置加载正常且包含预期品种。"""
    config = load_products_config()
    assert "Ti_sponge" in config
    assert "ilmenite" in config
    assert "Li2CO3" in config
    assert config["Ti_sponge"]["product_name"] == "海绵钛"
    assert config["Ti_sponge"]["category"] == "nonferrous"


def test_offline_html_run_collection(tmp_path: Path, monkeypatch) -> None:
    """验证离线 HTML 文本模式端到端解析、RAW 快照保存与 Curated 物化。"""
    # 隔离落地路径至 tmp_path
    survey_csv = tmp_path / "expert_prices_survey.csv"
    curated_dir = tmp_path / "curated"
    snap_dir = tmp_path / "snapshots"

    import scripts.cdp.mysteel_cdp_automation as mca

    monkeypatch.setattr(mca, "DEFAULT_SURVEY_CSV", survey_csv)
    monkeypatch.setattr(mca, "DEFAULT_CURATED_DIR", curated_dir)
    monkeypatch.setattr(mca, "DEFAULT_SNAPSHOT_DIR", snap_dir)

    sample_html = """
    <html>
    <head><span class="time">2026-09-15</span></head>
    <body>
        <table>
            <tr><th>品名</th><th>规格</th><th>产地</th><th>价格</th><th>日期</th></tr>
            <tr><td>海绵钛</td><td>0#</td><td>国内</td><td>45000</td><td>2026-09-15</td></tr>
        </table>
    </body>
    </html>
    """

    meta = {
        "product_name": "海绵钛",
        "symbol": "Ti_sponge",
        "target_specs": ["0#"],
        "unit": "元/吨",
    }
    quotes = run_collection_for_product(
        cdp=None,
        product_meta=meta,
        symbol="Ti_sponge",
        offline_html=sample_html,
    )

    assert len(quotes) == 1
    assert quotes[0].price == 45000.0

    # 验证 RAW 快照
    snapshots = list(snap_dir.glob("mysteel_Ti_sponge_*.html"))
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == sample_html

    # 验证 RAW survey CSV
    assert survey_csv.exists()
    content = survey_csv.read_text(encoding="utf-8")
    assert "Ti_sponge" in content
    assert "45000.0" in content

    # 验证 Curated Parquet
    parquet_path = curated_dir / "chemical_spot_price.parquet"
    assert parquet_path.exists()
    import polars as pl

    df = pl.read_parquet(parquet_path)
    sponge = df.filter(pl.col("symbol") == "Ti_sponge")
    assert len(sponge) >= 1
    row = sponge.row(0, named=True)
    assert row["spot_price_cny"] == 45000.0
    assert row["source"] == "Mysteel"
