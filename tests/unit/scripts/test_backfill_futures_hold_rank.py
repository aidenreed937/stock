"""席位龙虎榜批量回填脚本单元测试。"""

import sys
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from scripts.backfill_futures_hold_rank import backfill_hold_rank, main


def test_backfill_hold_rank_fetches_and_saves_snapshot(monkeypatch, tmp_path):
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"
    cache_dir = raw_dir / "chemicals" / "futures_daily" / "czce_daily_cache" / "2024"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fake_txt = (
        "郑州商品交易所期货每日行情表\n"
        "品种月份|昨结算|今开盘|最高价|最低价|今收盘|今结算|涨跌1|涨跌2|成交量(手)|空盘量|增减手|成交额(万元)|现价|交割结算价\n"
        "SA501|1500|1510|1520|1490|1505|1505|5|5|10000|50000|100|15000|1505|\n"
    )
    (cache_dir / "20240828.txt").write_text(fake_txt, encoding="utf-8")

    def _fake_rank(symbol: str, contract: str, date: str) -> pd.DataFrame:
        col = "多单持仓" if symbol == "多单持仓" else "空单持仓"
        return pd.DataFrame({"会员简称": ["中信期货（代客）"], col: [100.0]})

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            futures_hold_pos_sina=_fake_rank,
            futures_zh_realtime=lambda symbol: pd.DataFrame(),
        ),
    )

    res = backfill_hold_rank(
        start_date=date(2024, 8, 28),
        end_date=date(2024, 8, 28),
        symbols=["SA"],
        raw_dir=raw_dir,
        curated_dir=curated_dir,
        delay=0.0,
        force=True,
        sync=False,
    )

    assert res["fetched"] == 1
    assert res["cached"] == 0
    assert res["missing"] == 0

    snapshot_file = raw_dir / "chemicals" / "futures_hold_rank" / "SA_20240828.csv"
    assert snapshot_file.exists()


def test_backfill_hold_rank_skips_existing_when_not_force(monkeypatch, tmp_path):
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"
    rank_dir = raw_dir / "chemicals" / "futures_hold_rank"
    rank_dir.mkdir(parents=True, exist_ok=True)
    (rank_dir / "SA_20240828.csv").write_text("existing_data", encoding="utf-8")

    res = backfill_hold_rank(
        start_date=date(2024, 8, 28),
        end_date=date(2024, 8, 28),
        symbols=["SA"],
        raw_dir=raw_dir,
        curated_dir=curated_dir,
        delay=0.0,
        force=False,
        sync=False,
    )

    assert res["fetched"] == 0
    assert res["cached"] == 1
    assert res["missing"] == 0


def test_backfill_hold_rank_rejects_unknown_symbol(tmp_path):
    with pytest.raises(ValueError, match="未知品种"):
        backfill_hold_rank(
            start_date=date(2024, 8, 28),
            end_date=date(2024, 8, 28),
            symbols=["UNKNOWN_SYMBOL"],
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
        )


def test_main_cli_returns_nonzero_on_inverted_date(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["backfill_futures_hold_rank.py", "--start-date", "2024-08-30", "--end-date", "2024-08-28"],
    )
    assert main() == 1
