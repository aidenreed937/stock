"""CLI 入口：标的资产、多维特征标签与排雷风控黑名单管理。

用法:
    # 1. 从 YAML 初始化全量标的与默认标签
    uv run python -m stock_cli.universe --seed-from-yaml

    # 2. 查看所有标签及其标的数量
    uv run python -m stock_cli.universe --list-tags

    # 3. 按标签筛选标的 (如 '高股息', '核心宽基', '防守资产')
    uv run python -m stock_cli.universe --tag "高股息"

    # 4. 查看单个标的详情与所属标签
    uv run python -m stock_cli.universe --symbol 510880.SH --show

    # 5. 为标的打标签 / 移除标签
    uv run python -m stock_cli.universe --symbol 510880.SH --add-tag "高股息红利"
    uv run python -m stock_cli.universe --symbol 510880.SH --remove-tag "高股息红利"

    # 6. 风控排雷：加入黑名单 / 移出黑名单 / 查看黑名单
    uv run python -m stock_cli.universe --blacklist-add --symbol 000001.SZ --reason "立案调查"
    uv run python -m stock_cli.universe --list-blacklist
    uv run python -m stock_cli.universe --blacklist-remove --symbol 000001.SZ
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from stock_core.utils.logger import logger
from stock_strategy.state.universe_repo import BlacklistRepository, UniverseRepository


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="标的资产元数据、多维特征标签与排雷风控黑名单管理工具",
    )
    parser.add_argument(
        "--seed-from-yaml",
        action="store_true",
        help="从 config/universe/watchlist.yaml 同步初始标的与标签",
    )
    parser.add_argument("--list-tags", action="store_true", help="列出全库所有标签及包含的标的数量")
    parser.add_argument("--tag", type=str, default=None, help="按指定标签查询所有标的")
    parser.add_argument("--symbol", type=str, default=None, help="标的代码 (如: 510880.SH)")
    parser.add_argument("--show", action="store_true", help="查看指定标的详情")
    parser.add_argument("--add-tag", type=str, default=None, help="为指定标的添加标签")
    parser.add_argument("--remove-tag", type=str, default=None, help="从指定标的移除标签")

    # 黑名单管理
    parser.add_argument("--blacklist-add", action="store_true", help="将指定标的加入风控排雷黑名单")
    parser.add_argument("--blacklist-remove", action="store_true", help="从黑名单中解除指定标的")
    parser.add_argument(
        "--list-blacklist", action="store_true", help="列出当前生效的风控排雷黑名单"
    )
    parser.add_argument("--reason", type=str, default="风控排雷", help="拉黑原因 (默认: 风控排雷)")
    parser.add_argument(
        "--severity",
        type=str,
        choices=["CRITICAL", "WARNING"],
        default="CRITICAL",
        help="风控等级 (CRITICAL/WARNING)",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    repo = UniverseRepository()
    bl_repo = BlacklistRepository()

    # 1. 从 YAML 种子同步
    if args.seed_from_yaml:
        n = repo.seed_from_watchlist_yaml()
        print(f"✅ 成功从 watchlist.yaml 同步并打标 {n} 个核心标的！")
        return

    # 2. 列出所有标签
    if args.list_tags:
        tags = repo.list_all_tags()
        if not tags:
            print("目前暂无任何标签记录。可先运行 --seed-from-yaml。")
            return
        print(f"=== 全库标签统计 ({len(tags)} 个标签) ===")
        print(f"{'标签名称':<20} {'包含标的数':<10}")
        print("-" * 35)
        for t in tags:
            print(f"{t['tag_name']:<20} {t['symbol_count']:<10}")
        return

    # 3. 按标签筛选标的
    if args.tag:
        syms = repo.get_symbols_by_tag(args.tag)
        if not syms:
            print(f"未找到带有标签 [{args.tag}] 的标的。")
            return
        print(f"=== 标签 [{args.tag}] 下的有效标的 ({len(syms)} 个) ===")
        print(f"{'标的代码':<15} {'标的名称':<15} {'资产类型':<10} {'交易所':<10} {'基准日期':<12}")
        print("-" * 65)
        for s in syms:
            b_date = s["base_date"] or "—"
            print(
                f"{s['symbol']:<15} {s['name']:<15} {s['asset_type']:<10} {s['exchange']:<10} {b_date:<12}"
            )
        return

    # 4. 黑名单管理
    if args.blacklist_add:
        if not args.symbol:
            logger.error("加入黑名单必须提供 --symbol")
            sys.exit(1)
        b_id = bl_repo.add_to_blacklist(
            symbol=args.symbol,
            reason=args.reason,
            severity=args.severity,
            start_date=date.today(),
        )
        print(
            f"🚨 已将标的 [{args.symbol}] 加入风控黑名单 (ID: {b_id}, 原因: {args.reason}, 等级: {args.severity})！"
        )
        return

    if args.blacklist_remove:
        if not args.symbol:
            logger.error("解除黑名单必须提供 --symbol")
            sys.exit(1)
        n = bl_repo.remove_from_blacklist(args.symbol)
        print(f"✅ 已从黑名单中解除标的 [{args.symbol}] (影响记录数: {n})！")
        return

    if args.list_blacklist:
        with bl_repo.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM risk_blacklists ORDER BY start_date DESC;")
            rows = [dict(r) for r in cursor.fetchall()]
        if not rows:
            print("目前黑名单为空 (全库标的风控状态健康 ✅)。")
            return
        print(f"=== 当前风控排雷黑名单 ({len(rows)} 条记录) ===")
        print(f"{'ID':<6} {'标的代码':<15} {'风控等级':<10} {'生效起始日':<12} {'拉黑原因':<25}")
        print("-" * 75)
        for r in rows:
            print(
                f"{r['blacklist_id']:<6} {r['symbol']:<15} {r['severity']:<10} {r['start_date']:<12} {r['reason']:<25}"
            )
        return

    # 5. 标的标签维护
    if args.symbol and args.add_tag:
        # 确保标的存在
        if not repo.get_symbol(args.symbol):
            repo.upsert_symbol(args.symbol, args.symbol, "STOCK")
        repo.add_tag(args.symbol, args.add_tag)
        print(f"✅ 成功为标的 [{args.symbol}] 添加标签: [{args.add_tag}]！")
        return

    if args.symbol and args.remove_tag:
        repo.remove_tag(args.symbol, args.remove_tag)
        print(f"✅ 成功从标的 [{args.symbol}] 移除标签: [{args.remove_tag}]！")
        return

    # 6. 查看标的详情
    if args.symbol and args.show:
        info = repo.get_symbol(args.symbol)
        if not info:
            print(f"标的 [{args.symbol}] 未在元数据库中注册。")
            return
        is_bl, bl_reasons = bl_repo.is_blacklisted(args.symbol)
        bl_str = (
            "🚨 是 (" + "; ".join(r["reason"] for r in bl_reasons) + ")" if is_bl else "否 (正常)"
        )
        print("================================================================")
        print(f" 标的详情: {info['name']} ({info['symbol']})")
        print(f" 资产类型: {info['asset_type']} | 交易所: {info['exchange']}")
        print(f" 在市状态: {'有效在市' if info['is_active'] else '已退市/暂停'}")
        print(f" 黑名单:   {bl_str}")
        print(f" 所属标签: {', '.join(info['tags']) if info['tags'] else '无'}")
        if info["description"]:
            print(f" 标的描述: {info['description']}")
        print("================================================================")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
