"""分析层 DataCatalog 兼容加载门面测试。"""

from datetime import date

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat as analytics_loader
from stock_data.catalog.compat import load_dataset_compat as canonical_loader


class _Loader:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: list[str] | None = None,
        **kwargs: object,
    ) -> pl.DataFrame:
        self.calls.append(
            {
                "dataset": dataset,
                "start_date": start_date,
                "end_date": end_date,
                "columns": columns,
                **kwargs,
            }
        )
        return pl.DataFrame(
            {
                "trade_date": [date(2026, 8, 1)],
                "value": [1.0],
                "extra": [2.0],
            }
        )


def test_analytics_facade_matches_canonical_loader_and_omits_none_kwargs() -> None:
    canonical = _Loader()
    analytics = _Loader()
    columns = ("trade_date", "value")

    canonical_frame = canonical_loader(
        canonical,
        "demo",
        start_date=date(2026, 8, 1),
        end_date=None,
        columns=columns,
    )
    analytics_frame = analytics_loader(
        analytics,
        "demo",
        start_date=date(2026, 8, 1),
        end_date=None,
        columns=columns,
    )

    assert canonical_frame.equals(analytics_frame)
    assert canonical.calls == analytics.calls
    assert canonical.calls == [
        {
            "dataset": "demo",
            "start_date": date(2026, 8, 1),
            "end_date": None,
            "columns": columns,
        }
    ]


def test_shared_loader_handles_narrow_signature_and_non_frame_result() -> None:
    class _Narrow:
        def load_dataset(self, dataset: str) -> pl.DataFrame:
            return pl.DataFrame({"value": [1.0], "extra": [2.0]})

    class _Bad:
        def load_dataset(self, dataset: str) -> list[object]:
            return [1, 2, 3]

    assert canonical_loader(_Narrow(), "demo", columns=["value"]).columns == ["value"]
    assert analytics_loader(_Narrow(), "demo", columns=["value"]).columns == ["value"]
    assert canonical_loader(_Bad(), "demo").is_empty()
    assert analytics_loader(_Bad(), "demo").is_empty()
