"""垂直产业端点 registry 测试。"""

import pytest

from stock_data.fetcher.industry.registry import get_endpoint_spec, get_endpoint_specs


def test_industry_endpoint_specs_are_grouped_by_domain() -> None:
    specs = get_endpoint_specs()

    assert specs["semiconductor_sales"].domain == "semiconductor"
    assert specs["semiconductor_inventory_days"].domain == "semiconductor"
    assert specs["semiconductor_channel_inventory"].domain == "semiconductor"
    assert specs["semiconductor_memory_price"].domain == "semiconductor"
    assert specs["solar_supply_demand"].domain == "power"
    assert specs["chemical_spreads"].domain == "chemicals"
    assert specs["chemical_spot_price"].domain == "chemicals"
    assert specs["customs_trade"].domain == "customs"
    assert specs["coal_market"].domain == "coal"


def test_get_endpoint_spec_rejects_unknown_endpoint() -> None:
    with pytest.raises(KeyError, match="missing_industry_endpoint"):
        get_endpoint_spec("missing_industry_endpoint")


def test_semiconductor_models_are_exported_from_domain_package() -> None:
    from stock_data.fetcher.industry import models as root_models
    from stock_data.fetcher.industry.semiconductor import models as domain_models

    assert root_models.SemiconductorSalesRecord is domain_models.SemiconductorSalesRecord
    assert root_models.SemiconductorInventoryRecord is domain_models.SemiconductorInventoryRecord


def test_power_models_are_exported_from_domain_package() -> None:
    from stock_data.fetcher.industry.models import SolarCapacityRecord as RootCapacityRecord
    from stock_data.fetcher.industry.power import SolarCapacityRecord as PackageCapacityRecord
    from stock_data.fetcher.industry.power.models import SolarCapacityRecord as DomainCapacityRecord

    assert RootCapacityRecord is DomainCapacityRecord
    assert PackageCapacityRecord is DomainCapacityRecord


def test_semiconductor_sales_parser_is_exported_from_parser_package() -> None:
    from stock_data.fetcher.industry.semiconductor.parsers import (
        parse_sia_china_and_date as domain_parser,
    )
    from stock_data.fetcher.industry.semiconductor.parsers.sales import (
        parse_sia_china_and_date as sales_parser,
    )

    assert sales_parser is domain_parser


def test_semiconductor_domain_package_exposes_layered_modules() -> None:
    from stock_data.fetcher.industry import SemiconductorEquipmentRecord
    from stock_data.fetcher.industry.semiconductor import SeajEquipmentCollector
    from stock_data.fetcher.industry.semiconductor.collectors import SemiconductorCollector
    from stock_data.fetcher.industry.semiconductor.models import (
        SemiconductorEquipmentRecord as DomainEquipmentRecord,
    )
    from stock_data.fetcher.industry.semiconductor.schemas import SEMICONDUCTOR_SALES_SCHEMA
    from stock_data.fetcher.industry.semiconductor.transforms import (
        records_to_semiconductor_frame,
    )

    assert SemiconductorCollector.__module__.endswith(".collectors.sales")
    assert SeajEquipmentCollector.__module__.endswith(".collectors.seaj")
    assert SemiconductorEquipmentRecord is DomainEquipmentRecord
    assert records_to_semiconductor_frame.__module__.endswith(".transforms.facts")
    assert "trade_date" in SEMICONDUCTOR_SALES_SCHEMA


def test_power_domain_package_exposes_layered_modules() -> None:
    from stock_data.fetcher.industry.power.collectors import (
        NbsSolarCellCollector,
        SiliconBranchCollector,
        SolarCollector,
    )
    from stock_data.fetcher.industry.power.models import SolarCapacityRecord
    from stock_data.fetcher.industry.power.parsers import (
        InfoLinkSpotPriceHtmlParser,
        parse_silicon_branch_bulletin_text,
        parse_solar_capacity_from_text,
    )
    from stock_data.fetcher.industry.power.schemas import (
        SILICON_WAFER_RAW_SCHEMA,
        SOLAR_CAPACITY_RAW_SCHEMA,
        SOLAR_CAPACITY_SCHEMA,
    )
    from stock_data.fetcher.industry.power.transforms import (
        build_polysilicon_supply_from_silicon_frame,
        records_to_silicon_wafer_monthly_frame,
        records_to_solar_frame,
    )

    assert SolarCollector.__module__.endswith(".collectors.nea")
    assert NbsSolarCellCollector.__module__.endswith(".collectors.nbs")
    assert SiliconBranchCollector.__module__.endswith(".collectors.silicon")
    assert InfoLinkSpotPriceHtmlParser.__module__.endswith(".parsers.infolink")
    assert parse_solar_capacity_from_text.__module__.endswith(".parsers.nea")
    assert parse_silicon_branch_bulletin_text.__module__.endswith(".parsers.silicon")
    assert records_to_solar_frame.__module__.endswith(".transforms.facts")
    assert records_to_silicon_wafer_monthly_frame.__module__.endswith(".transforms.silicon")
    assert build_polysilicon_supply_from_silicon_frame.__module__.endswith(
        ".transforms.polysilicon"
    )
    assert SolarCapacityRecord.__module__.endswith(".power.models")
    assert "trade_date" in SOLAR_CAPACITY_SCHEMA
    assert "raw_content_sha256" in SOLAR_CAPACITY_RAW_SCHEMA
    assert "capacity_raw_snapshot_path" in SILICON_WAFER_RAW_SCHEMA
