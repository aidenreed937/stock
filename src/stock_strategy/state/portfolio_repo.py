"""实盘与模拟盘账户持仓与交易账本仓储 (PortfolioRepository)。

严格遵守 ACID 事务准则：资金扣减、持仓增减与订单流水在单一事务内原子完成。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from stock_core.storage.sqlite_engine import SQLiteEngine, get_sqlite_engine


def _compute_trade_impact(
    direction: str,
    curr_shares: int,
    curr_cost: float,
    filled_shares: int,
    filled_price: float,
    commission: float,
    slippage_cost: float,
) -> tuple[int, float, float]:
    """计算成交后的新持仓份额、新成本均价与现金变动 (cash_delta)。"""
    trade_amount = filled_shares * filled_price
    friction = commission + slippage_cost

    if direction == "BUY":
        new_shares = curr_shares + filled_shares
        total_cost = (curr_shares * curr_cost) + trade_amount + friction
        new_cost = total_cost / new_shares if new_shares > 0 else filled_price
        cash_delta = -(trade_amount + friction)
    elif direction in {"SELL", "CLOSE"}:
        new_shares = max(0, curr_shares - filled_shares)
        new_cost = curr_cost if new_shares > 0 else 0.0
        cash_delta = trade_amount - friction
    else:
        raise ValueError(f"不支持的交易方向: {direction}")

    return new_shares, new_cost, cash_delta


class PortfolioRepository:
    """账户与持仓账本仓储。"""

    def __init__(self, engine: SQLiteEngine | None = None) -> None:
        self.engine = engine or get_sqlite_engine()

    def get_or_create_account(
        self,
        account_id: str,
        account_name: str,
        strategy_key: str,
        initial_capital: float = 100_000.0,
    ) -> dict[str, Any]:
        """获取或创建交易账户。"""
        with self.engine.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE account_id = ?;", (account_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)

            cursor.execute(
                """
                INSERT INTO accounts (account_id, account_name, strategy_key, total_capital, cash_available)
                VALUES (?, ?, ?, ?, ?);
                """,
                (account_id, account_name, strategy_key, initial_capital, initial_capital),
            )
            cursor.execute("SELECT * FROM accounts WHERE account_id = ?;", (account_id,))
            return dict(cursor.fetchone())

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        """获取指定账户信息。"""
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE account_id = ?;", (account_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_accounts(self) -> list[dict[str, Any]]:
        """获取所有账户列表。"""
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts ORDER BY created_at ASC;")
            return [dict(r) for r in cursor.fetchall()]

    def get_positions(self, account_id: str) -> list[dict[str, Any]]:
        """获取指定账户的所有持仓标的。"""
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM positions WHERE account_id = ? AND shares > 0 ORDER BY symbol ASC;",
                (account_id,),
            )
            return [dict(r) for r in cursor.fetchall()]

    def deposit_cash(self, account_id: str, amount: float) -> dict[str, Any]:
        """账户入金。"""
        if amount <= 0:
            raise ValueError(f"入金金额必须大于 0, 输入为: {amount}")
        with self.engine.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE accounts
                SET cash_available = cash_available + ?,
                    total_capital = total_capital + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ?;
                """,
                (amount, amount, account_id),
            )
            cursor.execute("SELECT * FROM accounts WHERE account_id = ?;", (account_id,))
            return dict(cursor.fetchone())

    def execute_order(
        self,
        *,
        account_id: str,
        symbol: str,
        symbol_name: str,
        trade_date: date | str,
        direction: str,  # 'BUY' | 'SELL' | 'CLOSE'
        target_weight: float,
        target_shares: int,
        filled_shares: int,
        filled_price: float,
        commission: float = 0.0,
        slippage_cost: float = 0.0,
        reason: str = "",
    ) -> str:
        """执行订单撮合并原子更新持仓与现金 (ACID)。"""
        direction = direction.upper()
        order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        with self.engine.transaction() as conn:
            cursor = conn.cursor()

            # 1. 插入订单流水
            cursor.execute(
                """
                INSERT INTO trade_orders (
                    order_id, account_id, symbol, trade_date, order_time, direction,
                    target_weight, target_shares, filled_shares, filled_price,
                    commission, slippage_cost, reason, status
                ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, 'FILLED');
                """,
                (
                    order_id,
                    account_id,
                    symbol,
                    str(trade_date),
                    direction,
                    target_weight,
                    target_shares,
                    filled_shares,
                    filled_price,
                    commission,
                    slippage_cost,
                    reason,
                ),
            )

            # 2. 查询当前持仓并计算增量
            cursor.execute(
                "SELECT shares, cost_price FROM positions WHERE account_id = ? AND symbol = ?;",
                (account_id, symbol),
            )
            pos_row = cursor.fetchone()
            curr_s = int(pos_row[0]) if pos_row else 0
            curr_c = float(pos_row[1]) if pos_row else 0.0

            new_shares, new_cost, cash_delta = _compute_trade_impact(
                direction, curr_s, curr_c, filled_shares, filled_price, commission, slippage_cost
            )

            # 3. 更新或插入持仓
            cursor.execute(
                """
                INSERT INTO positions (
                    account_id, symbol, symbol_name, shares, cost_price,
                    latest_price, market_value, weight, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(account_id, symbol) DO UPDATE SET
                    shares = excluded.shares,
                    cost_price = excluded.cost_price,
                    latest_price = excluded.latest_price,
                    market_value = excluded.market_value,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (
                    account_id,
                    symbol,
                    symbol_name,
                    new_shares,
                    new_cost,
                    filled_price,
                    new_shares * filled_price,
                    target_weight,
                ),
            )

            # 4. 更新现金并重算总资产
            cursor.execute(
                "UPDATE accounts SET cash_available = cash_available + ?, updated_at = CURRENT_TIMESTAMP WHERE account_id = ?;",
                (cash_delta, account_id),
            )
            cursor.execute(
                "SELECT SUM(market_value) FROM positions WHERE account_id = ? AND shares > 0;",
                (account_id,),
            )
            tot_pos_val = float(cursor.fetchone()[0] or 0.0)
            cursor.execute(
                "SELECT cash_available FROM accounts WHERE account_id = ?;", (account_id,)
            )
            cash_avail = float(cursor.fetchone()[0] or 0.0)

            cursor.execute(
                "UPDATE accounts SET total_capital = ? WHERE account_id = ?;",
                (tot_pos_val + cash_avail, account_id),
            )

            return order_id


__all__ = ["PortfolioRepository"]
