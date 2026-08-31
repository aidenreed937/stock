"""垂直产业景气指标 2-Tier ETL 统一同步管道。"""

import logging
from pathlib import Path

from stock_data.fetcher.industry.agriculture import (
    AgriculturePorkCollector,
    records_to_agriculture_pork_frame,
)
from stock_data.fetcher.industry.automotive import NevCollector, records_to_nev_frame
from stock_data.fetcher.industry.chemicals import (
    ChemicalsCollector,
    records_to_chemical_market_frame,
)
from stock_data.fetcher.industry.cloud import CloudCapexCollector, records_to_cloud_capex_frame
from stock_data.fetcher.industry.coal import (
    CoalMarketCollector,
    records_to_coal_market_frame,
)
from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.consumer import (
    LiquorWholesaleCollector,
    records_to_liquor_wholesale_frame,
)
from stock_data.fetcher.industry.customs import ComtradeCollector, records_to_customs_trade_frame
from stock_data.fetcher.industry.electronics import (
    ConsumerElectronicsCollector,
    records_to_consumer_electronics_frame,
)
from stock_data.fetcher.industry.machinery import MachineryCollector, records_to_machinery_frame
from stock_data.fetcher.industry.metals import NonFerrousCollector, records_to_metals_frame
from stock_data.fetcher.industry.pharma import PharmaBdCollector, records_to_pharma_bd_frame
from stock_data.fetcher.industry.power import (
    PvPriceChainCollector,
    SolarCollector,
    records_to_solar_frame,
    records_to_solar_price_chain_frame,
)
from stock_data.fetcher.industry.semiconductor import (
    SemiconductorCollector,
    TsmcLeadCollector,
    records_to_semiconductor_frame,
    records_to_semiconductor_lead_frame,
)
from stock_data.fetcher.industry.shipping import ShippingCollector, records_to_shipping_frame

logger = logging.getLogger(__name__)


def sync_all_industry_metrics(
    raw_dir: Path | str = "data/raw/industry",
    curated_dir: Path | str = "data/curated/industry",
    metrics: list[str] | None = None,
) -> dict[str, int]:
    """统一同步并落盘垂直产业黄金事实表。

    调度:
    1. SemiconductorCollector -> semiconductor_sales.parquet
    2. NevCollector -> nev_monthly_sales.parquet
    3. SolarCollector -> solar_capacity.parquet
    4. NonFerrousCollector -> non_ferrous_metals.parquet
    5. PharmaBdCollector -> pharma_license_out.parquet
    6. CloudCapexCollector -> cloud_capex_quarterly.parquet
    7. MachineryCollector -> construction_machinery.parquet
    8. ShippingCollector -> shipping_indices.parquet
    9. ComtradeCollector -> customs_trade.parquet
    10. TsmcLeadCollector -> semiconductor_lead.parquet
    11. ChemicalsCollector -> chemical_market.parquet
    12. PvPriceChainCollector -> solar_price_chain.parquet
    13. AgriculturePorkCollector -> agriculture_pork.parquet
    14. LiquorWholesaleCollector -> liquor_wholesale.parquet
    15. ConsumerElectronicsCollector -> consumer_electronics.parquet
    16. CoalMarketCollector -> coal_market.parquet
    """
    raw_path = Path(raw_dir)
    curated_path = Path(curated_dir)
    curated_path.mkdir(parents=True, exist_ok=True)
    results: dict[str, int] = {}
    target_metrics = set(metrics) if metrics else None

    # 1. 全球半导体销售额
    if target_metrics is None or "semiconductor_sales" in target_metrics:
        semi_collector = SemiconductorCollector(raw_dir=raw_path)
        semi_records = semi_collector.collect()
        if semi_records:
            df_semi = records_to_semiconductor_frame(semi_records)
            count = save_curated_fact(df_semi, curated_path / "semiconductor_sales.parquet")
            results["semiconductor_sales"] = count

    # 2. 新能源汽车产销与渗透率
    if target_metrics is None or "nev_monthly_sales" in target_metrics:
        nev_collector = NevCollector(raw_dir=raw_path)
        nev_records = nev_collector.collect()
        if nev_records:
            df_nev = records_to_nev_frame(nev_records)
            count = save_curated_fact(df_nev, curated_path / "nev_monthly_sales.parquet")
            results["nev_monthly_sales"] = count

    # 3. 全国光伏装机容量
    if target_metrics is None or "solar_capacity" in target_metrics:
        solar_collector = SolarCollector(raw_dir=raw_path)
        solar_records = solar_collector.collect()
        if solar_records:
            df_solar = records_to_solar_frame(solar_records)
            count = save_curated_fact(df_solar, curated_path / "solar_capacity.parquet")
            results["solar_capacity"] = count

    # 4. 有色大宗与工业/能源金属
    if target_metrics is None or "non_ferrous_metals" in target_metrics:
        metals_collector = NonFerrousCollector(raw_dir=raw_path)
        metals_records = metals_collector.collect()
        if metals_records:
            df_metals = records_to_metals_frame(metals_records)
            count = save_curated_fact(
                df_metals,
                curated_path / "non_ferrous_metals.parquet",
                primary_keys=["trade_date"],
            )
            results["non_ferrous_metals"] = count

    # 5. 中国创新药海外 License-out (BD) 授权
    if target_metrics is None or "pharma_license_out" in target_metrics:
        pharma_collector = PharmaBdCollector(raw_dir=raw_path)
        pharma_records = pharma_collector.collect()
        if pharma_records:
            df_pharma = records_to_pharma_bd_frame(pharma_records)
            count = save_curated_fact(
                df_pharma,
                curated_path / "pharma_license_out.parquet",
                primary_keys=["report_month"],
            )
            results["pharma_license_out"] = count

    # 6. 北美四大云厂商 (CSP) 季度 AI 资本开支
    if target_metrics is None or "cloud_capex_quarterly" in target_metrics:
        capex_collector = CloudCapexCollector(raw_dir=raw_path)
        capex_records = capex_collector.collect()
        if capex_records:
            df_capex = records_to_cloud_capex_frame(capex_records)
            count = save_curated_fact(
                df_capex,
                curated_path / "cloud_capex_quarterly.parquet",
                primary_keys=["report_quarter"],
            )
            results["cloud_capex_quarterly"] = count

    # 7. 工程机械月度产销与小松开工小时数
    if target_metrics is None or "construction_machinery" in target_metrics:
        mach_collector = MachineryCollector(raw_dir=raw_path)
        mach_records = mach_collector.collect()
        if mach_records:
            df_mach = records_to_machinery_frame(mach_records)
            count = save_curated_fact(
                df_mach,
                curated_path / "construction_machinery.parquet",
                primary_keys=["report_month"],
            )
            results["construction_machinery"] = count

    # 8. 全球海运与油运日频运价指数 (BDI/BDTI/BCTI/SCFI)
    if target_metrics is None or "shipping_indices" in target_metrics:
        ship_collector = ShippingCollector(raw_dir=raw_path)
        ship_records = ship_collector.collect()
        if ship_records:
            df_ship = records_to_shipping_frame(ship_records)
            count = save_curated_fact(
                df_ship,
                curated_path / "shipping_indices.parquet",
                primary_keys=["trade_date"],
            )
            results["shipping_indices"] = count

    # 9. UN Comtrade / GACC 海关重点品类贸易事实 (39个HS8/36个HS6赛道黄金事实长表)
    if target_metrics is None or "customs_trade" in target_metrics:
        comtrade_raw = raw_path / "customs" / "comtrade"
        comtrade_collector = ComtradeCollector(raw_dir=comtrade_raw)
        comtrade_records = comtrade_collector.collect()
        if comtrade_records:
            df_customs = records_to_customs_trade_frame(comtrade_records)
            count = save_curated_fact(
                df_customs,
                curated_path / "customs_trade.parquet",
                primary_keys=["product_key", "hs_code", "report_month"],
            )
            results["customs_trade"] = count

    # 10. 台积电月度营运与 DRAM 现货先导指标
    if target_metrics is None or "semiconductor_lead" in target_metrics:
        tsmc_collector = TsmcLeadCollector(raw_dir=raw_path)
        tsmc_records = tsmc_collector.collect()
        if tsmc_records:
            df_tsmc = records_to_semiconductor_lead_frame(tsmc_records)
            count = save_curated_fact(
                df_tsmc,
                curated_path / "semiconductor_lead.parquet",
                primary_keys=["report_month"],
            )
            results["semiconductor_lead"] = count

    # 11. 基础化工重点大宗品供需开工率与价差
    if target_metrics is None or "chemical_market" in target_metrics:
        chem_collector = ChemicalsCollector(raw_dir=raw_path)
        chem_records = chem_collector.collect()
        if chem_records:
            df_chem = records_to_chemical_market_frame(chem_records)
            count = save_curated_fact(
                df_chem,
                curated_path / "chemical_market.parquet",
                primary_keys=["report_month"],
            )
            results["chemical_market"] = count

    # 12. 光伏产业链价格链条 (硅料/硅片/电池片/组件)
    if target_metrics is None or "solar_price_chain" in target_metrics:
        pv_collector = PvPriceChainCollector(raw_dir=raw_path)
        pv_records = pv_collector.collect()
        if pv_records:
            df_pv = records_to_solar_price_chain_frame(pv_records)
            count = save_curated_fact(
                df_pv,
                curated_path / "solar_price_chain.parquet",
                primary_keys=["report_date"],
            )
            results["solar_price_chain"] = count

    # 13. 农业农村部生猪产能与出栏价格
    if target_metrics is None or "agriculture_pork" in target_metrics:
        pork_collector = AgriculturePorkCollector(raw_dir=raw_path)
        pork_records = pork_collector.collect()
        if pork_records:
            df_pork = records_to_agriculture_pork_frame(pork_records)
            count = save_curated_fact(
                df_pork,
                curated_path / "agriculture_pork.parquet",
                primary_keys=["report_month"],
            )
            results["agriculture_pork"] = count

    # 14. 名优白酒周度一批价与动销
    if target_metrics is None or "liquor_wholesale" in target_metrics:
        liquor_collector = LiquorWholesaleCollector(raw_dir=raw_path)
        liquor_records = liquor_collector.collect()
        if liquor_records:
            df_liquor = records_to_liquor_wholesale_frame(liquor_records)
            count = save_curated_fact(
                df_liquor,
                curated_path / "liquor_wholesale.parquet",
                primary_keys=["report_date"],
            )
            results["liquor_wholesale"] = count

    # 15. 消费电子终端 (智能手机 / PC / AI 渗透率) 季度出货
    if target_metrics is None or "consumer_electronics" in target_metrics:
        elec_collector = ConsumerElectronicsCollector(raw_dir=raw_path)
        elec_records = elec_collector.collect()
        if elec_records:
            df_elec = records_to_consumer_electronics_frame(elec_records)
            count = save_curated_fact(
                df_elec,
                curated_path / "consumer_electronics.parquet",
                primary_keys=["report_quarter"],
            )
            results["consumer_electronics"] = count

    # 16. 煤炭行业动力煤港口平仓价与电厂日耗库存天数
    if target_metrics is None or "coal_market" in target_metrics:
        coal_collector = CoalMarketCollector(raw_dir=raw_path)
        coal_records = coal_collector.collect()
        if coal_records:
            df_coal = records_to_coal_market_frame(coal_records)
            count = save_curated_fact(
                df_coal,
                curated_path / "coal_market.parquet",
                primary_keys=["report_date"],
            )
            results["coal_market"] = count

    return results
