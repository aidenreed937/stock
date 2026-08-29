"""14:50 宏观信号推演审计与 Webhook 告警去重仓储 (SignalRepository)。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from stock_core.storage.sqlite_engine import SQLiteEngine, get_sqlite_engine
from stock_strategy.macro.live import LiveSignalInspectionResult


class SignalRepository:
    """信号审计与推送日志仓储。"""

    def __init__(self, engine: SQLiteEngine | None = None) -> None:
        self.engine = engine or get_sqlite_engine()

    def record_signal(self, res: LiveSignalInspectionResult) -> tuple[str, bool]:
        """记录 14:50 巡检信号 (支持基于内容哈希的幂等去重)。

        Returns:
            (signal_id, is_new): 信号唯一标识以及是否为首次记录的新信号
        """
        # 计算指令内容与策略维度的确定性哈希
        inst_payload = [
            {
                "symbol": inst.symbol,
                "direction": inst.direction,
                "target_weight": round(inst.target_weight, 4),
                "recommended_lots": inst.recommended_lots,
            }
            for inst in res.instructions
        ]
        inst_json = json.dumps(inst_payload, sort_keys=True)
        signal_content = f"{res.strategy_key}:{inst_json}"
        signal_hash = hashlib.sha256(signal_content.encode("utf-8")).hexdigest()[:16]

        trade_d = res.as_of_time.date().isoformat()
        signal_id = f"SIG-{trade_d.replace('-', '')}-{signal_hash[:8]}"

        with self.engine.connect() as conn:
            cursor = conn.cursor()
            # 检查是否已存在相同哈希的信号
            cursor.execute(
                "SELECT signal_id FROM signal_history WHERE strategy_key = ? AND trade_date = ? AND signal_hash = ?;",
                (res.strategy_key, trade_d, signal_hash),
            )
            existing = cursor.fetchone()
            if existing:
                return str(existing[0]), False

            # 插入新信号
            cursor.execute(
                """
                INSERT INTO signal_history (
                    signal_id, strategy_key, trade_date, generated_at, signal_hash,
                    has_rebalance, benchmark_symbol, benchmark_price, benchmark_ma20,
                    panic_index, overheat_index, instructions_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    signal_id,
                    res.strategy_key,
                    trade_d,
                    res.as_of_time.isoformat(),
                    signal_hash,
                    1 if res.has_rebalance else 0,
                    res.benchmark_symbol,
                    res.benchmark_price,
                    res.benchmark_ma20,
                    res.panic_index,
                    res.overheat_index,
                    json.dumps([inst.__dict__ for inst in res.instructions], ensure_ascii=False),
                ),
            )
            conn.commit()
            return signal_id, True

    def record_notification(
        self,
        *,
        signal_id: str | None,
        channel: str,
        title: str,
        content_md: str,
        is_alert: bool,
        sent_status: str,
        http_code: int | None = None,
        response_body: str | None = None,
    ) -> int:
        """记录 Webhook 发送日志。"""
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO notification_logs (
                    signal_id, channel, title, content_md, is_alert,
                    sent_status, http_code, response_body
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    signal_id,
                    channel,
                    title,
                    content_md,
                    1 if is_alert else 0,
                    sent_status,
                    http_code,
                    response_body,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def get_latest_signal(self, strategy_key: str) -> dict[str, Any] | None:
        """获取指定策略的最新一条信号记录。"""
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM signal_history
                WHERE strategy_key = ?
                ORDER BY generated_at DESC
                LIMIT 1;
                """,
                (strategy_key,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


__all__ = ["SignalRepository"]
