"""核心行情数据模型与实体适用粒度定义。"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class EntityType(StrEnum):
    """标的或实体适用粒度。"""

    MARKET = "market"  # 全市场级别（A股大盘）
    INDEX = "index"  # 指数级别（如 000300.SH）
    INDUSTRY = "industry"  # 行业级别（如 申万一级行业）
    STOCK = "stock"  # 个股级别
    ETF = "etf"  # 场内基金/ETF 级别
    MACRO = "macro"  # 宏观级别（如 美联储利率、国债收益率、M1/M2）


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
