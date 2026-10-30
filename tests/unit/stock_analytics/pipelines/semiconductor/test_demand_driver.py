"""测试半导体分时期需求驱动配置加载器与年份路由。"""

from stock_analytics.pipelines.semiconductor.demand_driver import (
    load_demand_drivers_config,
)


def test_load_demand_drivers_config() -> None:
    cfg = load_demand_drivers_config()
    assert cfg.schema_version == 1
    assert len(cfg.eras) >= 5
    assert cfg.default_cross_cycle is not None


def test_demand_driver_era_routing() -> None:
    cfg = load_demand_drivers_config()

    # 1. 1995 年 -> PC 时代
    era_1995 = cfg.get_era_by_year(1995)
    assert era_1995 is not None
    assert era_1995.id == "pc_era"
    assert "PC" in era_1995.name
    assert any("x86" in chip for chip in era_1995.key_chips)

    # 2. 2005 年 -> 功能机与泛消费电子
    era_2005 = cfg.get_era_by_year(2005)
    assert era_2005 is not None
    assert era_2005.id == "consumer_electronics_era"

    # 3. 2015 年 -> 智能手机与 4G 移动互联网
    era_2015 = cfg.get_era_by_year(2015)
    assert era_2015 is not None
    assert era_2015.id == "smartphone_mobile_cloud_era"
    assert any("智能手机" in ind.name for ind in era_2015.leading_indicators)

    # 4. 2021 年 -> 疫情居家与缺芯
    era_2021 = cfg.get_era_by_year(2021)
    assert era_2021 is not None
    assert era_2021.id == "covid_iot_automotive_era"
    assert any("交期" in ind.name for ind in era_2021.leading_indicators)

    # 5. 2024 / 2026 年 -> AI 与 HPC 时代
    era_2024 = cfg.get_era_by_year(2024)
    assert era_2024 is not None
    assert era_2024.id == "ai_hpc_era"
    assert any("云厂商" in ind.name for ind in era_2024.leading_indicators)
    assert "CapEx" in era_2024.transmission_chain

    # 6. 未知极早期年份 -> None (走兜底)
    era_1980 = cfg.get_era_by_year(1980)
    assert era_1980 is None
