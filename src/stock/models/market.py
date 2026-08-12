from datetime import date

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class DailyBar(BaseModel):
    """单日 K 线数据结构模型与基本约束"""

    symbol: str = Field(description="股票或标的代码，例如 600000.SH 或 AAPL")
    trade_date: date = Field(description="交易日期")
    open: float = Field(gt=0, description="开盘价")
    high: float = Field(gt=0, description="最高价")
    low: float = Field(gt=0, description="最低价")
    close: float = Field(gt=0, description="收盘价")
    volume: float = Field(ge=0, description="成交量")
    amount: float = Field(default=0.0, ge=0, description="成交额")

    @field_validator("high")
    @classmethod
    def validate_high(cls, v: float, info: ValidationInfo) -> float:
        """验证最高价不低于开盘价和最低价。"""
        open_price = info.data.get("open")
        low_price = info.data.get("low")
        if open_price and v < open_price:
            raise ValueError("最高价不能低于开盘价")
        if low_price and v < low_price:
            raise ValueError("最高价不能低于最低价")
        return v


class QuoteSummary(BaseModel):
    """标的简要行情与描述"""

    symbol: str
    name: str
    last_price: float
    change_pct: float
    total_market_cap: float | None = None


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
