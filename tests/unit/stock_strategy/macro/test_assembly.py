from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_core.exceptions import DataValidationError
from stock_strategy.macro import assembly


class _FakeCatalog:
    """按 symbol 返回预置 close 面板的假目录。"""

    def __init__(self, frames: dict[str, pl.DataFrame]) -> None:
        self._frames = frames

    def load_bars(self, *, symbol: str, dataset: str, columns: list[str]) -> pl.DataFrame:
        frame = self._frames.get(symbol, pl.DataFrame())
        if frame.is_empty():
            return frame
        return frame.select([c for c in columns if c in frame.columns])


def _patch_factors(monkeypatch, factors: pl.DataFrame) -> None:
    monkeypatch.setattr(
        assembly,
        "load_latest_risk_factors",
        lambda risk_root=None: (Path("."), factors, {}),
    )


def test_assemble_macro_panel_joins_and_forward_fills(monkeypatch) -> None:
    close = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1 + i) for i in range(5)],
            "close": [100.0, 101.0, 102.0, 103.0, 104.0],
        }
    )
    factors = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 2), date(2026, 1, 4)],
            "panic_index": [10.0, 20.0],
            "overheat_index": [30.0, 40.0],
        }
    )
    _patch_factors(monkeypatch, factors)
    panel = assembly.assemble_macro_panel(
        catalog=_FakeCatalog({"000985.CSI": close}),
        benchmark_symbol="000985.CSI",
    )
    assert set(panel.columns) == {"trade_date", "close", "panic_index", "overheat_index"}
    assert panel["trade_date"].to_list() == [date(2026, 1, 2 + i) for i in range(4)]
    assert panel["panic_index"].to_list() == [10.0, 10.0, 20.0, 20.0]
    assert panel["overheat_index"].to_list() == [30.0, 30.0, 40.0, 40.0]
    assert panel["close"].to_list() == [101.0, 102.0, 103.0, 104.0]


def test_assemble_macro_panel_passes_declared_extra_cols(monkeypatch) -> None:
    close = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1 + i) for i in range(5)],
            "close": [100.0, 101.0, 102.0, 103.0, 104.0],
        }
    )
    factors = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 2), date(2026, 1, 4)],
            "panic_index": [10.0, 20.0],
            "overheat_index": [30.0, 40.0],
            "smart_money_pct": [80.0, 60.0],
            "repurchase_score": [55.0, 65.0],
        }
    )
    _patch_factors(monkeypatch, factors)
    panel = assembly.assemble_macro_panel(
        catalog=_FakeCatalog({"000985.CSI": close}),
        benchmark_symbol="000985.CSI",
        extra_factor_cols=["smart_money_pct"],
    )
    assert set(panel.columns) == {
        "trade_date",
        "close",
        "panic_index",
        "overheat_index",
        "smart_money_pct",
    }
    assert panel["smart_money_pct"].to_list() == [80.0, 80.0, 60.0, 60.0]


def test_assemble_macro_panel_missing_declared_extra_cols_raises(monkeypatch) -> None:
    close = pl.DataFrame({"trade_date": [date(2026, 1, 1)], "close": [100.0]})
    factors = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1)],
            "panic_index": [10.0],
            "overheat_index": [30.0],
        }
    )
    _patch_factors(monkeypatch, factors)
    with pytest.raises(DataValidationError, match="策略声明透传列"):
        assembly.assemble_macro_panel(
            catalog=_FakeCatalog({"000985.CSI": close}),
            benchmark_symbol="000985.CSI",
            extra_factor_cols=["smart_money_pct"],
        )


def test_assemble_macro_panel_missing_factor_cols_raises(monkeypatch) -> None:
    factors = pl.DataFrame({"trade_date": [date(2026, 1, 1)], "panic_index": [10.0]})
    _patch_factors(monkeypatch, factors)
    close = pl.DataFrame({"trade_date": [date(2026, 1, 1)], "close": [100.0]})
    with pytest.raises(DataValidationError):
        assembly.assemble_macro_panel(
            catalog=_FakeCatalog({"000985.CSI": close}),
            benchmark_symbol="000985.CSI",
        )


def test_assemble_macro_panel_empty_close_raises(monkeypatch) -> None:
    factors = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1)],
            "panic_index": [10.0],
            "overheat_index": [30.0],
        }
    )
    _patch_factors(monkeypatch, factors)
    with pytest.raises(DataValidationError):
        assembly.assemble_macro_panel(
            catalog=_FakeCatalog({}),
            benchmark_symbol="000985.CSI",
        )


def test_load_price_panel_concats_symbols() -> None:
    frames = {
        "000922.CSI": pl.DataFrame(
            {"trade_date": [date(2026, 1, 1)], "symbol": ["000922.CSI"], "close": [10.0]}
        ),
        "399006.SZ": pl.DataFrame(
            {"trade_date": [date(2026, 1, 1)], "symbol": ["399006.SZ"], "close": [20.0]}
        ),
    }
    panel = assembly.load_price_panel(
        catalog=_FakeCatalog(frames),
        symbols=["000922.CSI", "399006.SZ"],
    )
    assert sorted(panel["symbol"].to_list()) == ["000922.CSI", "399006.SZ"]
    assert sorted(panel["close"].to_list()) == [10.0, 20.0]


def test_load_price_panel_etf_adjustment() -> None:
    class _FakeETFCatalog(_FakeCatalog):
        data_source = "tushare"
        runtime = None

        def load_dataset(self, dataset: str, symbols: list[str] | None = None) -> pl.DataFrame:
            if dataset == "fund_adj":
                return pl.DataFrame(
                    {
                        "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
                        "adj_factor": [1.5, 1.5],
                    }
                )
            return pl.DataFrame()

    frames = {
        "510880.SH": pl.DataFrame(
            {
                "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
                "symbol": ["510880.SH", "510880.SH"],
                "close": [10.0, 20.0],
            }
        ),
    }
    panel = assembly.load_price_panel(
        catalog=_FakeETFCatalog(frames),
        symbols=["510880.SH"],
    )
    assert panel["symbol"].to_list() == ["510880.SH", "510880.SH"]
    assert panel["close"].to_list() == [15.0, 30.0]


def test_load_price_panel_etf_adj_factor_forward_filled_when_latest_missing() -> None:
    """T 日缺复权因子时必须前向填充最近因子，不能回退原始价（否则产生除权级假暴跌）。"""

    class _FakeETFCatalogNoLatestAdj(_FakeCatalog):
        data_source = "tushare"
        runtime = None

        def load_dataset(self, dataset: str, symbols: list[str] | None = None) -> pl.DataFrame:
            if dataset == "fund_adj":
                # 只到 1-1，缺 1-2（模拟 fund_adj 未同步到最新交易日）
                return pl.DataFrame(
                    {
                        "trade_date": [date(2026, 1, 1)],
                        "adj_factor": [1.5],
                    }
                )
            return pl.DataFrame()

    frames = {
        "510880.SH": pl.DataFrame(
            {
                "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
                "symbol": ["510880.SH", "510880.SH"],
                "close": [10.0, 20.0],
            }
        ),
    }
    panel = assembly.load_price_panel(
        catalog=_FakeETFCatalogNoLatestAdj(frames),
        symbols=["510880.SH"],
    )
    assert panel["close"].to_list() == [15.0, 30.0]
