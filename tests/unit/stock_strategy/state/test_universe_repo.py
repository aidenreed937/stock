from datetime import date
from pathlib import Path

from stock_core.storage.sqlite_engine import SQLiteEngine
from stock_strategy.state.universe_repo import BlacklistRepository, UniverseRepository


def test_universe_symbol_and_tags_lifecycle(tmp_path: Path) -> None:
    db_file = tmp_path / "test_universe.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)
    repo = UniverseRepository(engine)

    # 1. 插入标的
    repo.upsert_symbol("510880.SH", "红利ETF", "ETF", description="高股息策略标杆")
    sym = repo.get_symbol("510880.SH")
    assert sym is not None
    assert sym["name"] == "红利ETF"
    assert sym["asset_type"] == "ETF"
    assert sym["exchange"] == "SSE"

    # 2. 打标签
    repo.add_tag("510880.SH", "高股息")
    repo.add_tag("510880.SH", "防守资产")

    sym_after = repo.get_symbol("510880.SH")
    assert sym_after is not None
    assert "高股息" in sym_after["tags"]
    assert "防守资产" in sym_after["tags"]

    # 3. 按标签查询
    dividend_syms = repo.get_symbols_by_tag("高股息")
    assert len(dividend_syms) == 1
    assert dividend_syms[0]["symbol"] == "510880.SH"

    # 4. 统计所有标签
    all_tags = repo.list_all_tags()
    tag_names = [t["tag_name"] for t in all_tags]
    assert "高股息" in tag_names
    assert "防守资产" in tag_names

    # 5. 移除标签
    repo.remove_tag("510880.SH", "防守资产")
    sym_removed = repo.get_symbol("510880.SH")
    assert sym_removed is not None
    assert "防守资产" not in sym_removed["tags"]


def test_universe_blacklist_filtering(tmp_path: Path) -> None:
    db_file = tmp_path / "test_bl.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)
    u_repo = UniverseRepository(engine)
    bl_repo = BlacklistRepository(engine)

    u_repo.upsert_symbol("000001.SZ", "平安银行", "STOCK")
    u_repo.upsert_symbol("600519.SH", "贵州茅台", "STOCK")

    # 初始状态：两只均未被拉黑
    active_syms = bl_repo.filter_active_symbols(["000001.SZ", "600519.SH"])
    assert set(active_syms) == {"000001.SZ", "600519.SH"}

    # 将 000001.SZ 加入黑名单
    bl_repo.add_to_blacklist(
        symbol="000001.SZ",
        reason="测试风控排雷",
        start_date=date(2026, 1, 1),
    )

    is_bl, reasons = bl_repo.is_blacklisted("000001.SZ")
    assert is_bl is True
    assert reasons[0]["reason"] == "测试风控排雷"

    # 过滤测试：000001.SZ 应被自动剔除
    filtered = bl_repo.filter_active_symbols(["000001.SZ", "600519.SH"])
    assert filtered == ["600519.SH"]

    # 移出黑名单
    bl_repo.remove_from_blacklist("000001.SZ")
    is_bl_after, _ = bl_repo.is_blacklisted("000001.SZ")
    assert is_bl_after is False

    recovered = bl_repo.filter_active_symbols(["000001.SZ", "600519.SH"])
    assert set(recovered) == {"000001.SZ", "600519.SH"}


def test_universe_seed_from_yaml(tmp_path: Path) -> None:
    db_file = tmp_path / "test_seed.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)
    repo = UniverseRepository(engine)

    n = repo.seed_from_watchlist_yaml("config/universe/watchlist.yaml")
    assert n > 0

    # 验证关键标的存在且被打标
    etf = repo.get_symbol("510880.SH")
    assert etf is not None
    assert "高股息" in etf["tags"]
    assert "防守资产" in etf["tags"]

    growth_etf = repo.get_symbol("159915.SZ")
    assert growth_etf is not None
    assert "成长进攻" in growth_etf["tags"]
