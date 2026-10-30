"""郑商所仓单官方下载/解析单元测试（逻辑已下沉到 official 模块）。"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from runpy import run_path

import pandas as pd

from stock_data.fetcher.industry.chemicals.collectors import official

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "backfill_czce_soda_ash_inventory.py"
)
_mod = run_path(str(_SCRIPT_PATH))
get_all_trading_dates = _mod["get_all_trading_dates"]
SA_FIRST_RECEIPT_DATE = _mod["SA_FIRST_RECEIPT_DATE"]
SA_LIST_DATE = _mod["SA_LIST_DATE"]

SA_META = {"name": "纯碱", "industry_code": "220200", "unit": "contracts"}


def test_get_all_trading_dates_valid() -> None:
    """验证交易日历提取起止有效且单调递增。"""
    dates = get_all_trading_dates()
    assert len(dates) > 1000
    assert dates[0] >= SA_LIST_DATE
    assert dates == sorted(dates)


def test_download_czce_inventory_file_reads_cache(tmp_path: Path) -> None:
    """验证当本地已存在缓存文件时，不发起网络请求直接返回缓存。"""
    cache_dir = tmp_path / "2024"
    cache_dir.mkdir(parents=True)
    cached_file = cache_dir / "20240603.xlsx"
    fake_content = b"fake_excel_bytes_larger_than_1024_" * 40
    cached_file.write_bytes(fake_content)

    res_d, path, ext, content = official.download_czce_inventory_file(
        date(2024, 6, 3), cache_dir=tmp_path
    )
    assert res_d == date(2024, 6, 3)
    assert path == cached_file
    assert ext == "xlsx"
    assert content == fake_content


def test_parse_czce_inventory_frame_no_sa() -> None:
    """当表格中不包含纯碱时，返回 (0.0, 0.0)。"""
    df = pd.DataFrame([["品种：白糖SR", "", ""], ["总计", "100", "0"]])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, header=False)

    parsed = official.parse_czce_inventory_frame(
        buf.getvalue(), ext="xlsx", commodities={"SA": SA_META}
    )["SA"]
    inv, chg = parsed
    assert inv == 0.0
    assert chg == 0.0


def test_parse_czce_inventory_frame_with_sa_total() -> None:
    """当表格中包含纯碱段和总计行时，正确提取仓单总数与增减。"""
    rows = [
        ["品种：纯碱SA", "单位：张", "日期：2026-06-01", ""],
        ["仓库编号", "仓库简称", "仓单数量", "当日增减"],
        ["0103", "藁城永安", 0, 0],
        ["2103", "河北一三四处", 500, 100],
        ["总计", "", 500, 100],
        ["品种：玻璃FG", "单位：张", "", ""],
    ]
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, header=False)

    parsed = official.parse_czce_inventory_frame(
        buf.getvalue(), ext="xlsx", commodities={"SA": SA_META}
    )["SA"]
    inv, chg = parsed
    assert inv == 500.0
    assert chg == 100.0
    assert date(2020, 4, 7) == SA_FIRST_RECEIPT_DATE
