"""Yahoo Finance 抓取器专属数据模型。"""

from datetime import date

from pydantic import BaseModel, Field


class IndexValuation(BaseModel):
    """指数/ETF 估值数据模型"""

    symbol: str = Field(description="ETF 标的代码，如 SPY, QQQ")
    target_index: str = Field(description="对应指数代码，如 ^GSPC, ^IXIC")
    trade_date: date = Field(description="估值日期")
    trailing_pe: float | None = Field(default=None, description="滚动市盈率 (PE-TTM)")
    forward_pe: float | None = Field(default=None, description="预测市盈率 (Forward PE)")
    price_to_book: float | None = Field(default=None, description="市净率 (PB)")
    price_to_sales: float | None = Field(default=None, description="市销率 (PS)")
    dividend_yield: float | None = Field(default=None, description="股息率 (%)")
    market_cap: float | None = Field(default=None, description="基金规模/总市值")
