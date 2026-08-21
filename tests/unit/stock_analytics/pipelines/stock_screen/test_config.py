"""个股排雷配置测试。"""

from pathlib import Path

from stock_reporting.interpretation.stock_screen.config import load_stock_screen_config


def test_load_stock_screen_config_keeps_enabled_switches(tmp_path: Path) -> None:
    path = tmp_path / "stock_screen.yaml"
    path.write_text(
        """
stock_screen:
  title: 测试排雷
  hard_exclusion:
    rules:
      - id: st_marked
        enabled: true
        scope: all_market
        params: {name_regex: ST}
  yellow_warn:
    rules:
      - id: margin_stress
        enabled: false
        scope: all_market
        note: 覆盖不足
  datasets:
    - data_source: tushare
      dataset: stock_basic
      required: true
    - data_source: tushare
      dataset: margin_detail
      enabled: false
""",
        encoding="utf-8",
    )

    config = load_stock_screen_config(path)

    assert config.title == "测试排雷"
    assert config.hard_exclusion[0].params["name_regex"] == "ST"
    assert not config.yellow_warn[0].enabled
    assert not config.datasets[1].enabled
