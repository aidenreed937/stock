"""郑商所多品种仓单解析单元测试（逻辑已下沉到 official 模块）。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from stock_data.fetcher.industry.chemicals.collectors import official
from stock_data.fetcher.industry.chemicals.collectors.inventory import (
    CHEMICAL_FUTURES_SYMBOLS,
)

COMMODITIES = {
    symbol: meta
    for symbol, meta in CHEMICAL_FUTURES_SYMBOLS.items()
    if meta.get("exchange") == "CZCE"
}


def test_parse_czce_inventory_frame_multi_symbol(tmp_path: Path) -> None:
    """验证多品种（含完税/保税分列）仓单解析准确性。"""
    rows = [
        ["品种：纯碱SA", "单位：张", "日期：2026-06-01", "", "", ""],
        ["仓库编号", "仓库简称", "仓单数量", "当日增减", "", ""],
        ["0103", "仓库A", 500, 50, "", ""],
        ["总计", "", 500, 50, "", ""],
        ["品种：玻璃FG", "单位：张", "日期：2026-06-01", "", "", ""],
        ["仓库编号", "仓库简称", "仓单数量", "当日增减", "", ""],
        ["0201", "仓库B", 200, -10, "", ""],
        ["总计", "", 200, -10, "", ""],
        ["品种：PTA", "单位：张", "日期：2026-06-01", "", "", ""],
        ["仓库编号", "仓库简称", "品牌", "仓单数量(完税)", "仓单数量(保税)", "当日增减"],
        ["0301", "仓库C", "牌A", 1000, 200, 15],
        ["总计", "", "", 1000, 200, 15],
    ]
    df = pd.DataFrame(rows)
    fake_excel = tmp_path / "20260601.xlsx"
    with pd.ExcelWriter(fake_excel, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, header=False)

    results = official.parse_czce_inventory_frame(
        fake_excel.read_bytes(), ext="xlsx", commodities=COMMODITIES
    )
    assert results["SA"] == (500.0, 50.0)
    assert results["FG"] == (200.0, -10.0)
    # PTA 完税(1000) + 保税(200) = 1200
    assert results["TA"] == (1200.0, 15.0)
    # 未出现的品种默认 (0.0, 0.0)
    assert results["SH"] == (0.0, 0.0)
    assert results["UR"] == (0.0, 0.0)
    assert results["MA"] == (0.0, 0.0)
