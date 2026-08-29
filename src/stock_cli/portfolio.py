"""CLI 入口：实盘与模拟盘账户持仓与交易账本管理。

用法:
    # 1. 列出所有账户
    uv run python -m stock_cli.portfolio --list

    # 2. 创建新账户
    uv run python -m stock_cli.portfolio --create --account-id live_main --name "实盘主账户" --strategy macro_rotation_v4_etf --capital 100000

    # 3. 查看指定账户持仓与资产
    uv run python -m stock_cli.portfolio --account-id live_main --show

    # 4. 账户入金 / 出金
    uv run python -m stock_cli.portfolio --account-id live_main --deposit 50000
    uv run python -m stock_cli.portfolio --account-id live_main --withdraw 20000

    # 5. 手动记账买入 / 卖出
    uv run python -m stock_cli.portfolio --account-id live_main --buy --symbol 510880.SH --name "红利ETF" --shares 10000 --price 3.461 --commission 3.5
    uv run python -m stock_cli.portfolio --account-id live_main --sell --symbol 510880.SH --name "红利ETF" --shares 5000 --price 3.520 --commission 2.0
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from stock_core.utils.logger import logger
from stock_strategy.state.portfolio_repo import PortfolioRepository


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="实盘/模拟盘账户资金与持仓账本管理工具 (SQLite ACID)",
    )
    parser.add_argument("--list", action="store_true", help="列出所有账户概览")
    parser.add_argument("--show", action="store_true", help="查看指定账户的详细持仓与资金")
    parser.add_argument("--create", action="store_true", help="创建新账户")
    parser.add_argument(
        "--account-id", type=str, default="live_main", help="账户唯一标识 (默认: live_main)"
    )
    parser.add_argument("--name", type=str, default=None, help="账户别名 (如: '实盘主账户')")
    parser.add_argument(
        "--strategy", type=str, default="macro_rotation_v4_etf", help="绑定的策略键名"
    )
    parser.add_argument("--capital", type=float, default=100_000.0, help="初始资金 (CNY)")

    # 资金出入
    parser.add_argument("--deposit", type=float, default=None, help="账户入金金额 (CNY)")
    parser.add_argument("--withdraw", type=float, default=None, help="账户出金金额 (CNY)")

    # 交易记账
    parser.add_argument("--buy", action="store_true", help="记录买入订单")
    parser.add_argument("--sell", action="store_true", help="记录卖出订单")
    parser.add_argument("--symbol", type=str, default=None, help="标的代码 (如: 510880.SH)")
    parser.add_argument("--symbol-name", type=str, default="", help="标的名称 (如: 红利ETF)")
    parser.add_argument("--shares", type=int, default=0, help="成交份数/股数")
    parser.add_argument("--price", type=float, default=0.0, help="成交均价 (CNY)")
    parser.add_argument("--commission", type=float, default=0.0, help="佣金手续费 (CNY)")
    parser.add_argument("--reason", type=str, default="手动调仓记账", help="交易原因")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    repo = PortfolioRepository()

    # 1. 列出所有账户
    if args.list:
        accounts = repo.list_accounts()
        if not accounts:
            print("目前暂无任何账户记录。可通过 --create 创建账户。")
            return
        print(f"=== 现有交易账户列表 ({len(accounts)} 个) ===")
        print(
            f"{'账户ID':<15} {'账户名称':<15} {'绑定策略':<25} {'总资产(元)':<15} {'可用现金(元)':<15}"
        )
        print("-" * 85)
        for acc in accounts:
            print(
                f"{acc['account_id']:<15} {acc['account_name']:<15} {acc['strategy_key']:<25} "
                f"¥{acc['total_capital']:>12,.2f}  ¥{acc['cash_available']:>12,.2f}"
            )
        return

    # 2. 创建新账户
    if args.create:
        acc_name = args.name or args.account_id
        acc = repo.get_or_create_account(
            account_id=args.account_id,
            account_name=acc_name,
            strategy_key=args.strategy,
            initial_capital=args.capital,
        )
        print(f"✅ 账户创建成功: {acc['account_id']} ({acc['account_name']})")
        print(f"  - 绑定策略: {acc['strategy_key']}")
        print(f"  - 初始资产: ¥{acc['total_capital']:,.2f}")
        return

    # 3. 入金 / 出金
    if args.deposit is not None:
        acc = repo.deposit_cash(args.account_id, args.deposit)
        print(
            f"✅ 入金成功！账户 [{args.account_id}] 当前可用现金: ¥{acc['cash_available']:,.2f}, 总资产: ¥{acc['total_capital']:,.2f}"
        )
        return

    if args.withdraw is not None:
        acc = repo.deposit_cash(args.account_id, -args.withdraw)
        print(
            f"✅ 出金成功！账户 [{args.account_id}] 当前可用现金: ¥{acc['cash_available']:,.2f}, 总资产: ¥{acc['total_capital']:,.2f}"
        )
        return

    # 4. 手动买卖记账
    if args.buy or args.sell:
        if not args.symbol or args.shares <= 0 or args.price <= 0:
            logger.error("买卖记账必须提供 --symbol, --shares (>0), --price (>0)")
            sys.exit(1)

        direction = "BUY" if args.buy else "SELL"
        order_id = repo.execute_order(
            account_id=args.account_id,
            symbol=args.symbol,
            symbol_name=args.symbol_name or args.symbol,
            trade_date=date.today(),
            direction=direction,
            target_weight=0.0,
            target_shares=args.shares,
            filled_shares=args.shares,
            filled_price=args.price,
            commission=args.commission,
            reason=args.reason,
        )
        print(
            f"✅ 交易流水记录成功: {order_id} ({direction} {args.symbol} {args.shares}份 @ ¥{args.price:.3f})"
        )
        return

    # 5. 查看账户持仓详情 (--show 或默认)
    acc_info = repo.get_account(args.account_id)
    if not acc_info:
        print(f"账户 [{args.account_id}] 不存在。可通过 --create 创建。")
        return

    positions = repo.get_positions(args.account_id)
    print("================================================================")
    print(f" 账户概览: {acc_info['account_name']} ({acc_info['account_id']})")
    print(f" 绑定策略: {acc_info['strategy_key']}")
    print(f" 总资产:   ¥{acc_info['total_capital']:,.2f}")
    print(
        f" 可用现金: ¥{acc_info['cash_available']:,.2f} ({(acc_info['cash_available'] / acc_info['total_capital']):.1%})"
    )
    print("================================================================")
    if not positions:
        print("当前无任何持仓 (100% 现金)。")
    else:
        print(
            f"{'标的代码':<12} {'标的名称':<15} {'持仓份额':<10} {'成本均价':<10} {'参考市价':<10} {'持仓市值':<15} {'仓位占比':<10}"
        )
        print("-" * 85)
        for pos in positions:
            p_weight = (
                (pos["market_value"] / acc_info["total_capital"])
                if acc_info["total_capital"] > 0
                else 0.0
            )
            print(
                f"{pos['symbol']:<12} {pos['symbol_name']:<15} {pos['shares']:<10} "
                f"¥{pos['cost_price']:<9.3f} ¥{pos['latest_price']:<9.3f} "
                f"¥{pos['market_value']:>12,.2f}  {p_weight:>7.1%}"
            )


if __name__ == "__main__":
    main()
