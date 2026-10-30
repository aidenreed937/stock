"""Mysteel 历史周报列表解析与正文价格智能抽取单元测试。"""

from __future__ import annotations

from datetime import date

from stock_data.fetcher.industry.chemicals.parsers.mysteel_cdp import (
    MysteelArticleMeta,
    parse_mysteel_article,
    parse_mysteel_article_list,
    parse_mysteel_html,
)

SAMPLE_WEEKLY_LIST_HTML = """
<!DOCTYPE html>
<html>
<head><title>周评-我的钢铁网</title></head>
<body>
<div class="news-list">
  <ul>
    <li>
      <span class="date">[09-11]</span>
      <a href="https://thj.mysteel.com/a/26091115/8DFF7F35ACF6088B.html">Mysteel周报：钛系供强需弱格局延续 各品种承压分化</a>
    </li>
    <li>
      <span class="date">[09-04]</span>
      <a href="https://thj.mysteel.com/a/26090416/1ACE9196E406EE56.html">Mysteel周报：国内钛市整体弱势 市场悲观情绪浓厚（8.28-9.4）</a>
    </li>
    <li>
      <span class="date">[09-11]</span>
      <a href="https://thj.mysteel.com/a/26091117/1904DE784AFCF428.html">Mysteel周报：本周硅锰市场处于回调阶段</a>
    </li>
    <li>
      <a href="https://thj.mysteel.com/feedback.html">意见反馈</a>
    </li>
  </ul>
</div>
</body>
</html>
"""

SAMPLE_WEEKLY_ARTICLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Mysteel周报：钛系供强需弱格局延续 各品种承压分化_我的钢铁网</title>
</head>
<body>
  <div class="head">
    <h1>Mysteel周报：钛系供强需弱格局延续 各品种承压分化</h1>
    <span class="time">2026-09-11 16:45</span>
    <span class="source">来源：我的钢铁网(Mysteel)</span>
  </div>
  <div class="content">
    <p>国内钛精矿市场整体呈现供强需弱、价格承压下行的格局。</p>
    <p>国产矿方面，价格持续走弱。8月攀枝花地区46%品位钛精矿价格已降至1180-1230元/吨，当前国产矿山普遍亏损，开工率维持低位。</p>
    <p>进口矿方面，价格同步承压且库存压力更为突出。莫桑比克46%矿价1260-1270元/吨，港口现货成交清淡。</p>
  </div>
</body>
</html>
"""


def test_parse_mysteel_article_list() -> None:
    keywords = ["钛", "钛矿", "钛精矿", "钛系"]
    articles = parse_mysteel_article_list(SAMPLE_WEEKLY_LIST_HTML, keywords=keywords)
    assert len(articles) == 2
    assert isinstance(articles[0], MysteelArticleMeta)
    assert "钛系供强需弱格局延续" in articles[0].title
    assert articles[0].url == "https://thj.mysteel.com/a/26091115/8DFF7F35ACF6088B.html"
    assert articles[0].publish_date == date(date.today().year, 9, 11)

    assert "国内钛市整体弱势" in articles[1].title
    assert articles[1].url == "https://thj.mysteel.com/a/26090416/1ACE9196E406EE56.html"


def test_parse_mysteel_article_quotes() -> None:
    quotes = parse_mysteel_article(
        html=SAMPLE_WEEKLY_ARTICLE_HTML,
        target_product="钛精矿",
        symbol="ilmenite",
        source_url="https://thj.mysteel.com/a/26091115/8DFF7F35ACF6088B.html",
        target_specs=["46%", "47%"],
    )
    assert len(quotes) >= 1
    panxi = [q for q in quotes if q.region == "攀西" or "46%" in q.spec]
    assert len(panxi) >= 1
    quote = panxi[0]
    assert quote.symbol == "ilmenite"
    assert quote.product_name == "钛精矿"
    assert 1180.0 <= quote.price <= 1230.0
    assert quote.spec == "46%"
    assert quote.trade_date == date(2026, 9, 11)


def test_parse_mysteel_html_facade() -> None:
    meta = {
        "product_name": "钛精矿",
        "symbol": "ilmenite",
        "target_specs": ["46%"],
        "unit": "元/吨",
    }
    quotes = parse_mysteel_html(
        html=SAMPLE_WEEKLY_ARTICLE_HTML,
        product_meta=meta,
        source_url="https://thj.mysteel.com/a/26091115/8DFF7F35ACF6088B.html",
    )
    assert len(quotes) >= 1
    assert any(q.price == 1205.0 for q in quotes)
