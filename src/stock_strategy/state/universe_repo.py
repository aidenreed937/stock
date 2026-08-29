"""标的元数据、多维特征标签与排雷黑名单仓储。

拆分为单一职责的两大仓储：
1. UniverseRepository: 标的元数据与标签体系管理；
2. BlacklistRepository: 风控排雷黑名单与禁买过滤。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from stock_core.storage.sqlite_engine import SQLiteEngine, get_sqlite_engine


def _parse_exchange(symbol: str) -> str:
    """从标准标的代码解析交易所后缀。"""
    sym = symbol.upper()
    if sym.endswith(".SH"):
        return "SSE"
    if sym.endswith(".SZ"):
        return "SZSE"
    if sym.endswith(".BJ") or sym.endswith(".BSE"):
        return "BSE"
    return ""


class UniverseRepository:
    """标的资产元数据与多维标签仓储。"""

    def __init__(self, engine: SQLiteEngine | None = None) -> None:
        self.engine = engine or get_sqlite_engine()

    def upsert_symbol(
        self,
        symbol: str,
        name: str,
        asset_type: str,
        exchange: str = "",
        base_date: date | str | None = None,
        description: str = "",
        is_active: bool = True,
    ) -> None:
        """插入或更新标的元数据。"""
        exch = exchange or _parse_exchange(symbol)
        with self.engine.transaction() as conn:
            conn.execute(
                """
                INSERT INTO symbols_meta (symbol, name, asset_type, exchange, base_date, description, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(symbol) DO UPDATE SET
                    name = excluded.name,
                    asset_type = excluded.asset_type,
                    exchange = excluded.exchange,
                    base_date = COALESCE(excluded.base_date, symbols_meta.base_date),
                    description = excluded.description,
                    is_active = excluded.is_active,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (
                    symbol,
                    name,
                    asset_type.upper(),
                    exch,
                    str(base_date) if base_date else None,
                    description,
                    1 if is_active else 0,
                ),
            )

    def get_symbol(self, symbol: str) -> dict[str, Any] | None:
        """获取单个标的元数据与关联标签。"""
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM symbols_meta WHERE symbol = ?;", (symbol,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            cursor.execute(
                "SELECT tag_name FROM symbol_tags WHERE symbol = ? ORDER BY tag_name ASC;",
                (symbol,),
            )
            res["tags"] = [r[0] for r in cursor.fetchall()]
            return res

    def add_tag(self, symbol: str, tag_name: str) -> None:
        """为标的添加标签。"""
        with self.engine.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO symbol_tags (symbol, tag_name) VALUES (?, ?);",
                (symbol, tag_name.strip()),
            )

    def remove_tag(self, symbol: str, tag_name: str) -> None:
        """移除标的的指定标签。"""
        with self.engine.transaction() as conn:
            conn.execute(
                "DELETE FROM symbol_tags WHERE symbol = ? AND tag_name = ?;",
                (symbol, tag_name.strip()),
            )

    def get_symbols_by_tag(self, tag_name: str) -> list[dict[str, Any]]:
        """获取带有指定标签的所有有效标的。"""
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT s.* FROM symbols_meta s
                JOIN symbol_tags t ON s.symbol = t.symbol
                WHERE t.tag_name = ? AND s.is_active = 1
                ORDER BY s.symbol ASC;
                """,
                (tag_name.strip(),),
            )
            return [dict(r) for r in cursor.fetchall()]

    def list_all_tags(self) -> list[dict[str, Any]]:
        """获取全库所有标签及其包含的标的数量统计。"""
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT tag_name, COUNT(symbol) as symbol_count
                FROM symbol_tags
                GROUP BY tag_name
                ORDER BY symbol_count DESC, tag_name ASC;
                """
            )
            return [dict(r) for r in cursor.fetchall()]

    def seed_from_watchlist_yaml(
        self, config_path: Path | str = "config/universe/watchlist.yaml"
    ) -> int:
        """从 YAML 观察池批量同步初始标的与预设标签。"""
        cfg_file = Path(config_path)
        if not cfg_file.is_file():
            return 0
        data = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
        u_data = data.get("universe", {})
        count = 0

        # 同步股票
        for item in u_data.get("a_shares", {}).get("stocks", []):
            self.upsert_symbol(item["code"], item["name"], "STOCK", base_date=item.get("base_date"))
            self.add_tag(item["code"], "核心股票")
            count += 1

        # 同步指数
        for item in u_data.get("a_shares", {}).get("indices", []):
            self.upsert_symbol(
                item["code"],
                item["name"],
                "INDEX",
                base_date=item.get("base_date"),
                description=item.get("description", ""),
            )
            self.add_tag(item["code"], "核心指数")
            if "宽基" in item.get("description", ""):
                self.add_tag(item["code"], "核心宽基")
            count += 1

        # 同步 ETF / 基金
        fund_items = u_data.get("a_shares", {}).get("funds", []) or u_data.get("a_shares", {}).get(
            "etfs", []
        )
        for item in fund_items:
            self.upsert_symbol(
                item["code"],
                item["name"],
                "ETF",
                base_date=item.get("base_date"),
                description=item.get("description", ""),
            )
            self.add_tag(item["code"], "核心ETF")
            if "红利" in item["name"]:
                self.add_tag(item["code"], "高股息")
                self.add_tag(item["code"], "防守资产")
            if "创业板" in item["name"] or "科创" in item["name"]:
                self.add_tag(item["code"], "成长进攻")
            count += 1

        return count


class BlacklistRepository:
    """风控排雷黑名单仓储。"""

    def __init__(self, engine: SQLiteEngine | None = None) -> None:
        self.engine = engine or get_sqlite_engine()

    def add_to_blacklist(
        self,
        symbol: str,
        reason: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        severity: str = "CRITICAL",
    ) -> int:
        """将标的加入风控排雷黑名单。"""
        s_date = str(start_date or date.today())
        e_date = str(end_date) if end_date else None
        with self.engine.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO risk_blacklists (symbol, reason, severity, start_date, end_date)
                VALUES (?, ?, ?, ?, ?);
                """,
                (symbol, reason, severity.upper(), s_date, e_date),
            )
            return int(cursor.lastrowid or 0)

    def remove_from_blacklist(self, symbol: str, reason: str | None = None) -> int:
        """从黑名单中解除标的。"""
        with self.engine.transaction() as conn:
            cursor = conn.cursor()
            if reason:
                cursor.execute(
                    "DELETE FROM risk_blacklists WHERE symbol = ? AND reason = ?;",
                    (symbol, reason),
                )
            else:
                cursor.execute("DELETE FROM risk_blacklists WHERE symbol = ?;", (symbol,))
            return cursor.rowcount

    def is_blacklisted(
        self, symbol: str, as_of_date: date | str | None = None
    ) -> tuple[bool, list[dict[str, Any]]]:
        """检查标的是否在生效黑名单中。"""
        target_d = str(as_of_date or date.today())
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM risk_blacklists
                WHERE symbol = ?
                  AND start_date <= ?
                  AND (end_date IS NULL OR end_date >= ?);
                """,
                (symbol, target_d, target_d),
            )
            rows = [dict(r) for r in cursor.fetchall()]
            return len(rows) > 0, rows

    def filter_active_symbols(
        self, symbols: list[str], as_of_date: date | str | None = None
    ) -> list[str]:
        """批量过滤：剔除已下架或当前处于黑名单禁买的标的。"""
        target_d = str(as_of_date or date.today())
        if not symbols:
            return []
        placeholders = ",".join("?" for _ in symbols)
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT symbol FROM symbols_meta
                WHERE symbol IN ({placeholders})
                  AND is_active = 1
                  AND symbol NOT IN (
                      SELECT symbol FROM risk_blacklists
                      WHERE start_date <= ? AND (end_date IS NULL OR end_date >= ?)
                  );
                """,
                (*symbols, target_d, target_d),
            )
            return [str(r[0]) for r in cursor.fetchall()]


__all__ = ["BlacklistRepository", "UniverseRepository"]
