"""数据源与接口显式单位标准化器 (Unit Normalizer)。"""

from typing import Any
import polars as pl

from stock.utils.logger import logger

# 声明不同数据源与 API endpoint 的显式单位转换规则
# 映射结构: { data_source: { endpoint: { raw_column: (target_column, multiplier) } } }
UNIT_CONVERSION_RULES: dict[str, dict[str, dict[str, tuple[str, float]]]] = {
    "tushare": {
        "daily": {
            "vol": ("volume", 100.0),        # TuShare 原始 vol 单位为"手" -> 转换为"股" (* 100)
            "amount": ("amount", 1000.0),    # TuShare 原始 amount 单位为"千元" -> 转换为"元" (* 1000)
        },
        "daily_basic": {
            "total_mv": ("total_mv", 10000.0),  # TuShare 原始 total_mv 单位为"万元" -> 转换为"元" (* 10000)
            "circ_mv": ("circ_mv", 10000.0),    # TuShare 原始 circ_mv 单位为"万元" -> 转换为"元" (* 10000)
        },
        "moneyflow": {
            "buy_sm_vol": ("buy_sm_vol", 100.0),
            "sell_sm_vol": ("sell_sm_vol", 100.0),
            "buy_md_vol": ("buy_md_vol", 100.0),
            "sell_md_vol": ("sell_md_vol", 100.0),
            "buy_lg_vol": ("buy_lg_vol", 100.0),
            "sell_lg_vol": ("sell_lg_vol", 100.0),
            "buy_elg_vol": ("buy_elg_vol", 100.0),
            "sell_elg_vol": ("sell_elg_vol", 100.0),
            "buy_sm_amount": ("buy_sm_amount", 10000.0),
            "sell_sm_amount": ("sell_sm_amount", 10000.0),
            "buy_md_amount": ("buy_md_amount", 10000.0),
            "sell_md_amount": ("sell_md_amount", 10000.0),
            "buy_lg_amount": ("buy_lg_amount", 10000.0),
            "sell_lg_amount": ("sell_lg_amount", 10000.0),
            "buy_elg_amount": ("buy_elg_amount", 10000.0),
            "sell_elg_amount": ("sell_elg_amount", 10000.0),
            "net_mf_vol": ("net_mf_vol", 100.0),
            "net_mf_amount": ("net_mf_amount", 10000.0),
        },
    }
}


class UnitNormalizer:
    """显式单位标准化器，根据 data_source 和 endpoint 执行无歧义的单位倍率转换。"""

    def __init__(self, data_source: str, endpoint: str) -> None:
        """初始化单位标准化器。

        Args:
            data_source: 数据源标识 (如 tushare).
            endpoint: 接口名称 (如 daily, daily_basic).
        """
        self.data_source = data_source.lower()
        self.endpoint = endpoint.lower()
        self.rules = UNIT_CONVERSION_RULES.get(self.data_source, {}).get(self.endpoint, {})

    def normalize_units(self, df: pl.DataFrame) -> pl.DataFrame:
        """根据配置规则对 DataFrame 中的数值列应用单位转换。

        Args:
            df: 原始响应或提取出的 DataFrame。

        Returns:
            pl.DataFrame: 完成单位倍率转换后的 DataFrame。
        """
        if df.is_empty() or not self.rules:
            return df

        expressions: list[pl.Expr] = []
        applied_cols: set[str] = set()

        for raw_col, (target_col, multiplier) in self.rules.items():
            if raw_col in df.columns:
                # 转换类型为 Float64 并乘以倍率
                expr = (pl.col(raw_col).cast(pl.Float64, strict=False) * multiplier).alias(target_col)
                expressions.append(expr)
                applied_cols.add(raw_col)
                if raw_col != target_col and raw_col in df.columns:
                    applied_cols.add(raw_col)

        if not expressions:
            return df

        logger.debug(
            f"接口 [{self.data_source}/{self.endpoint}] 应用单位转换规则: {list(self.rules.keys())}"
        )

        # 应用表达式转换
        transformed = df.with_columns(expressions)

        # 若原始列名与目标列名不同，移除旧原始列
        cols_to_drop = [
            raw_col for raw_col, (target_col, _) in self.rules.items()
            if raw_col != target_col and raw_col in transformed.columns
        ]
        if cols_to_drop:
            transformed = transformed.drop(cols_to_drop)

        return transformed
