"""选股规则抽象协议与复合规则链。"""

from typing import Any, Protocol
import pandas as pd

from stock.utils.logger import logger


class FilterRule(Protocol):
    """单项选股规则协议。"""

    rule_name: str

    def apply(self, df: pd.DataFrame, context: dict[str, Any] | None = None) -> pd.DataFrame:
        """应用规则过滤 DataFrame 并返回筛选结果。"""
        ...


class CompositeRuleChain:
    """复合规则链，顺序执行子规则并记录各层淘汰指标。"""

    def __init__(self, rules: list[FilterRule] | None = None) -> None:
        self.rules = rules or []

    def add_rule(self, rule: FilterRule) -> "CompositeRuleChain":
        self.rules.append(rule)
        return self

    def apply(self, df: pd.DataFrame, context: dict[str, Any] | None = None) -> pd.DataFrame:
        filtered = df
        initial_count = len(df)
        for rule in self.rules:
            prev_count = len(filtered)
            filtered = rule.apply(filtered, context)
            eliminated = prev_count - len(filtered)
            logger.info(f"  └─ [{rule.rule_name}] 剩余: {len(filtered)} 只 (淘汰: {eliminated} 只)")
        logger.info(f"== 规则链执行完毕: 初始 {initial_count} 只 -> 最终剩余 {len(filtered)} 只 ==")
        return filtered
