"""数据管道与采集调度专属常量定义。"""

from typing import Final

# 接口历史最早数据起始日校准表：自动将更早的无意义请求截断提升至真实上线首日
ENDPOINT_START_DATE_OVERRIDES: Final[dict[str, str]] = {
    "moneyflow_hsgt": "2014-11-17",
    "hsgt_top10": "2014-11-17",
    "margin": "2010-03-31",
    "margin_detail": "2010-03-31",
    "fund_daily": "1998-04-07",
    "sw_daily": "2014-01-02",
}

# 交易所特定业务上线首日表：精准拦截早于交易所上线时间的无用 API 请求
EXCHANGE_START_DATES: Final[dict[str, dict[str, str]]] = {
    "margin": {
        "SSE": "2010-03-31",
        "SZSE": "2010-03-31",
        "BSE": "2023-02-13",
    }
}
