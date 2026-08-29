from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_core.storage.sqlite_engine import SQLiteEngine
from stock_strategy.macro.live import LiveOrderInstruction, LiveSignalInspectionResult
from stock_strategy.state.signal_repo import SignalRepository

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def test_signal_repository_record_and_deduplicate(tmp_path: Path) -> None:
    db_file = tmp_path / "test_state.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)
    repo = SignalRepository(engine)

    # 构造信号结果
    inst1 = LiveOrderInstruction(
        symbol="510880.SH",
        name="红利ETF",
        direction="BUY",
        target_weight=0.5,
        current_weight=0.0,
        delta_weight=0.5,
        latest_price=3.46,
        target_amount=50000.0,
        recommended_lots=144,
        reason="测试买入",
    )
    res = LiveSignalInspectionResult(
        strategy_key="macro_rotation_v4_etf",
        strategy_class="MacroRotationV4Strategy",
        as_of_time=datetime(2026, 8, 29, 14, 50, 0, tzinfo=_SHANGHAI_TZ),
        has_rebalance=True,
        benchmark_symbol="000985.CSI",
        benchmark_price=5930.0,
        benchmark_ma20=5920.0,
        panic_index=55.0,
        overheat_index=62.0,
        instructions=[inst1],
        markdown_card="测试卡片",
    )

    # 首次插入：应成功且 is_new = True
    sig_id, is_new = repo.record_signal(res)
    assert is_new is True
    assert sig_id.startswith("SIG-20260829-")

    # 相同内容再次插入：应幂等去重且 is_new = False
    sig_id_2, is_new_2 = repo.record_signal(res)
    assert is_new_2 is False
    assert sig_id_2 == sig_id

    # 记录 Webhook 日志
    log_id = repo.record_notification(
        signal_id=sig_id,
        channel="feishu",
        title="调仓提醒",
        content_md="测试内容",
        is_alert=True,
        sent_status="SUCCESS",
        http_code=200,
    )
    assert log_id > 0

    # 查询最新信号
    latest = repo.get_latest_signal("macro_rotation_v4_etf")
    assert latest is not None
    assert latest["signal_id"] == sig_id
    assert latest["has_rebalance"] == 1
