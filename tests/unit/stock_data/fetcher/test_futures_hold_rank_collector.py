"""期货主力席位持仓龙虎榜采集器测试。"""

import sys
from datetime import date
from types import SimpleNamespace

import pandas as pd
import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.futures_hold_rank import (
    FuturesHoldRankCollector,
)


def test_futures_hold_rank_schema(monkeypatch, tmp_path):
    def _fake_rank(symbol: str, contract: str, date: str) -> pd.DataFrame:
        col = "多单持仓" if symbol == "多单持仓" else "空单持仓"
        return pd.DataFrame(
            {"会员简称": ["中信期货（代客）", "国泰君安（代客）"], col: [100.0, 50.0]}
        )

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(futures_hold_pos_sina=_fake_rank))

    collector = FuturesHoldRankCollector(raw_dir=tmp_path)
    res = collector.fetch_contract_rank(symbol="SA", contract="SA2409", query_date="20240828")

    assert res is not None
    assert res["symbol"] == "SA"
    assert res["name"] == "纯碱"
    assert res["top20_long_vol"] == 150.0
    assert res["top20_short_vol"] == 150.0
    assert res["top20_net_long_vol"] == 0.0
    assert res["top1_long_member"] == "中信期货（代客）"
    assert res["smart_money_bias"] in ["bullish", "neutral", "bearish"]
    # RAW 快照必须落在传入的 raw_dir，严禁写入生产 data/raw 目录
    assert (tmp_path / "chemicals" / "futures_hold_rank" / "SA_20240828.csv").exists()


def test_futures_hold_rank_skips_missing_volume(monkeypatch, tmp_path):
    def _fake_rank(symbol: str, contract: str, date: str) -> pd.DataFrame:
        col = "多单持仓" if symbol == "多单持仓" else "空单持仓"
        return pd.DataFrame({"会员简称": ["席位A"], col: [None]})

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(futures_hold_pos_sina=_fake_rank))

    collector = FuturesHoldRankCollector(raw_dir=tmp_path)
    res = collector.fetch_contract_rank(symbol="SA", contract="SA2409", query_date="20240828")
    assert res is None


def test_futures_hold_rank_resolves_current_contract(monkeypatch, tmp_path):
    def _fake_rank(symbol: str, contract: str, date: str) -> pd.DataFrame:
        col = "多单持仓" if symbol == "多单持仓" else "空单持仓"
        return pd.DataFrame({"会员简称": ["席位A"], col: [100.0]})

    realtime = pd.DataFrame(
        {
            "symbol": ["SA0", "SA2609", "SA2701"],
            "position": [999.0, 100.0, 200.0],
        }
    )
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            futures_hold_pos_sina=_fake_rank,
            futures_zh_realtime=lambda symbol: realtime,
        ),
    )

    collector = FuturesHoldRankCollector(raw_dir=tmp_path)
    query_date = date.today().strftime("%Y%m%d")
    result = collector.fetch_contract_rank(symbol="SA", query_date=query_date)

    assert result is not None
    assert result["contract"] == "SA2701"


def test_futures_hold_rank_rejects_historical_without_contract_override(monkeypatch, tmp_path):
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(futures_zh_realtime=lambda symbol: pd.DataFrame()),
    )

    collector = FuturesHoldRankCollector(raw_dir=tmp_path)

    assert collector.fetch_contract_rank(symbol="SA", query_date="20240828") is None


def test_futures_hold_rank_result_reports_unresolved_history(monkeypatch, tmp_path):
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(futures_zh_realtime=lambda symbol: pd.DataFrame()),
    )

    collector = FuturesHoldRankCollector(raw_dir=tmp_path)
    result = collector.collect_raw_result(
        start_date=date(2024, 8, 28),
        end_date=date(2024, 8, 28),
    )

    assert result.status == "MISSING_RANGE"
    assert result.missing_periods
    assert result.errors


def test_futures_hold_rank_resolves_historical_contract_from_official(monkeypatch, tmp_path):
    cache_dir = tmp_path / "chemicals" / "futures_daily" / "czce_daily_cache" / "2024"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fake_txt = (
        "郑州商品交易所期货每日行情表\n"
        "品种月份|昨结算|今开盘|最高价|最低价|今收盘|今结算|涨跌1|涨跌2|成交量(手)|空盘量|增减手|成交额(万元)|现价|交割结算价\n"
        "SA501|1500|1510|1520|1490|1505|1505|5|5|10000|50000|100|15000|1505|\n"
        "SA409|1600|1610|1620|1590|1605|1605|5|5|5000|10000|50|8000|1605|\n"
    )
    (cache_dir / "20240828.txt").write_text(fake_txt, encoding="utf-8")

    captured_contract: list[str] = []

    def _fake_rank(symbol: str, contract: str, date: str) -> pd.DataFrame:
        captured_contract.append(contract)
        col = "多单持仓" if symbol == "多单持仓" else "空单持仓"
        return pd.DataFrame({"会员简称": ["席位A"], col: [100.0]})

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            futures_hold_pos_sina=_fake_rank,
            futures_zh_realtime=lambda symbol: pd.DataFrame(),
        ),
    )

    collector = FuturesHoldRankCollector(raw_dir=tmp_path)
    res = collector.fetch_contract_rank(symbol="SA", query_date="20240828")

    assert res is not None
    assert res["contract"] == "SA2501"
    assert captured_contract == ["SA2501", "SA2501"]


def test_futures_hold_rank_accepts_date_specific_override(monkeypatch, tmp_path):
    captured_contract: list[str] = []

    def _fake_rank(symbol: str, contract: str, date: str) -> pd.DataFrame:
        captured_contract.append(contract)
        col = "多单持仓" if symbol == "多单持仓" else "空单持仓"
        return pd.DataFrame({"会员简称": ["席位A"], col: [100.0]})

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            futures_hold_pos_sina=_fake_rank,
            futures_zh_realtime=lambda symbol: pd.DataFrame(),
        ),
    )

    collector = FuturesHoldRankCollector(raw_dir=tmp_path)
    frame = collector.collect_raw(
        query_date="20240828",
        contract_overrides={"SA:20240828": "SA2409"},
    )

    assert not frame.is_empty()
    sa_rows = frame.filter(pl.col("symbol") == "SA")
    assert sa_rows["contract"][0] == "SA2409"
