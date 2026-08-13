"""动态股票池筛选器 (数据域兼容垫片)。"""

from stock.data.domain.universe import UniverseFilter

__all__ = ["UniverseFilter"]

if __name__ == "__main__":
    filter_engine = UniverseFilter()
    filter_engine.save_universe_snapshot()
