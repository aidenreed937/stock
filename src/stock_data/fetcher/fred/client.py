import io
import logging
from typing import Any

import pandas as pd
from curl_cffi import requests

from stock_core.exceptions import DataFetchError

logger = logging.getLogger(__name__)


class FredClient:
    """FRED (Federal Reserve Economic Data) 官方宏观经济数据客户端。"""

    BASE_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    def __init__(self, proxy: str | None = None) -> None:
        """初始化 FRED 客户端。

        Args:
            proxy: 可选的 HTTP/HTTPS 代理服务配置
        """
        self.proxy = proxy
        self.session: Any = requests.Session(impersonate="chrome")
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

    def fetch_series_raw(self, series_id: str) -> pd.DataFrame:
        """根据 FRED series_id (如 FEDFUNDS, CPIAUCSL) 下载完整历史数据表。"""
        params = {"id": series_id}
        try:
            logger.debug(f"正在从 FRED 请求宏观序列: {series_id}...")
            response = self.session.get(self.BASE_CSV_URL, params=params, timeout=15)
            response.raise_for_status()

            # 将 CSV 内容转为 Pandas DataFrame
            csv_file = io.StringIO(response.text)
            df = pd.read_csv(csv_file)
            # FRED 返回字段: observation_date 或 DATE, {series_id}
            df.columns = [c.strip() for c in df.columns]
            date_col = "observation_date" if "observation_date" in df.columns else "DATE"
            if date_col not in df.columns:
                raise DataFetchError(f"FRED 响应缺少日期列 [{series_id}]")

            if date_col != "DATE":
                df = df.rename(columns={date_col: "DATE"})

            # 转换数值类型 (处理 '.' 缺失值)
            val_col = series_id.upper()
            if val_col not in df.columns:
                raise DataFetchError(f"FRED 响应缺少序列列 [{series_id}/{val_col}]")
            df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
            df = df.dropna(subset=[val_col])

            return df
        except DataFetchError:
            raise
        except Exception as e:
            logger.error(f"FRED 请求宏观序列失败 [{series_id}]: {e}")
            raise DataFetchError(f"FRED 请求宏观序列失败 [{series_id}]: {e}") from e

    def get(self, endpoint: str, **kwargs: Any) -> pd.DataFrame:
        """通用查询入口，兼容标准 Client 接口。"""
        return self.fetch_series_raw(series_id=endpoint)
