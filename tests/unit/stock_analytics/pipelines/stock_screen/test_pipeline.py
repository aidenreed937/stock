"""个股排雷管线测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.stock_screen.pipeline import run_stock_screen


class _MemoryCatalog:
    def __init__(self, frames: dict[str, pl.DataFrame], latest: date) -> None:
        self.frames = frames
        self.latest = latest

    def latest_trade_dates(self, dataset: str = "stock_daily_bar", n: int = 1, **_: object):
        return [self.latest][:n]

    def load_dataset(self, dataset: str, **_: object) -> pl.DataFrame:
        return self.frames.get(dataset, pl.DataFrame())


def test_run_stock_screen_writes_three_way_snapshot(tmp_path: Path) -> None:
    as_of = date(2026, 8, 20)
    config_path = tmp_path / "stock_screen.yaml"
    config_path.write_text(
        """
stock_screen:
  title: 测试排雷
  artifact_root: data/analytics/stock_screen
  hard_exclusion:
    rules:
      - id: st_marked
        enabled: true
        scope: all_market
        params: {name_regex: ST}
      - id: penny_stock_face_value
        enabled: true
        scope: all_market
        params: {min_close_price: 2.0}
  yellow_warn:
    rules: []
  datasets:
    - data_source: tushare
      dataset: stock_basic
      required: true
      static: true
    - data_source: tushare
      dataset: daily_basic
      required: true
      date_column: trade_date
""",
        encoding="utf-8",
    )
    catalog = _MemoryCatalog(
        {
            "stock_basic": pl.DataFrame(
                {
                    "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
                    "name": ["正常公司", "ST公司", "低价公司"],
                    "list_date": [date(2020, 1, 1)] * 3,
                    "list_status": ["L"] * 3,
                    "market": ["CN"] * 3,
                }
            ),
            "daily_basic": pl.DataFrame(
                {
                    "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
                    "trade_date": [as_of] * 3,
                    "close": [10.0, 10.0, 1.99],
                }
            ),
        },
        as_of,
    )

    result = run_stock_screen(
        target_date=as_of,
        config_path=config_path,
        output_root=tmp_path / "artifacts",
        catalogs={"tushare": catalog},
    )

    assert result.scores["population_size"] == 3
    assert set(result.tables["excluded"]["symbol"].to_list()) == {"000002.SZ", "000003.SZ"}
    assert result.tables["passed"]["symbol"].to_list() == ["000001.SZ"]
    assert result.paths.report_md.exists()
    assert any(
        item["rule_id"] == "audit_opinion" and item["status"] == "not_supported"
        for item in result.scores["missing_gates"]
    )
    assert any(
        item["rule_id"] == "regulatory_measures_and_inquiry"
        and item["status"] == "registered_pending_backfill"
        for item in result.scores["missing_gates"]
    )
    assert any(
        item["rule_id"] == "litigation" and item["status"] == "not_supported"
        for item in result.scores["missing_gates"]
    )


def test_run_stock_screen_caps_passed_artifact_but_keeps_full_count(tmp_path: Path) -> None:
    as_of = date(2026, 8, 20)
    config_path = tmp_path / "stock_screen.yaml"
    config_path.write_text(
        """
stock_screen:
  title: 测试排雷
  output: {top_passed: 1, max_warn_rows: 1}
  hard_exclusion: {rules: []}
  yellow_warn: {rules: []}
  datasets:
    - data_source: tushare
      dataset: stock_basic
      required: true
      static: true
""",
        encoding="utf-8",
    )
    catalog = _MemoryCatalog(
        {
            "stock_basic": pl.DataFrame(
                {
                    "symbol": ["000001.SZ", "000002.SZ"],
                    "name": ["公司1", "公司2"],
                    "list_date": [date(2020, 1, 1)] * 2,
                    "list_status": ["L"] * 2,
                }
            )
        },
        as_of,
    )

    result = run_stock_screen(
        target_date=as_of,
        config_path=config_path,
        output_root=tmp_path / "artifacts",
        catalogs={"tushare": catalog},
    )

    assert result.scores["passed_count"] == 2
    assert result.tables["passed"].height == 2
    assert result.paths.passed.read_text(encoding="utf-8").count("00000") == 1
