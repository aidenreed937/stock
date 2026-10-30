"""GACC 税号目录派生测试。"""

from pathlib import Path

from stock_data.fetcher.industry.customs.parsers.gacc_catalog import (
    derive_gacc_code_catalog,
)


def test_gacc_catalog_is_derived_from_hs_catalog(tmp_path: Path) -> None:
    hs_catalog_path = tmp_path / "good_h8_codes.csv"
    hs_catalog_path.write_text(
        "product_key,product_name,hs_code,description,gacc_active\n"
        "inverter,逆变器,85044000,同品目父级,\n"
        "inverter,逆变器,85044030,现行八位码,\n"
        "air_conditioner,家用空调,84151000,同品目父级,\n"
        "air_conditioner,家用空调,84151010,现行八位码,\n"
        "vaccine,疫苗,30022000,HS2017 历史子目,\n"
        "cathode_material,正极材料,28419000,历史/代理口径,1\n"
        "disabled,禁用,12345678,显式禁用,0\n"
        "industrial,工业品,123456,六位国际码,\n",
        encoding="utf-8-sig",
    )

    derived = derive_gacc_code_catalog(hs_catalog_path)

    assert list(derived) == ["28419000", "30022000", "84151010", "85044030"]
    assert derived["28419000"]["source_evidence"] == "auto-derived from good_h8_codes.csv"
    assert derived["28419000"]["hs_parent_code"] == "284190"
