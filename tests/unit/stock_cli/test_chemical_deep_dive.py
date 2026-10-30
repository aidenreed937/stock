"""化工垂直深度爆破统一分发器 (chemical_deep_dive CLI) 单元测试。"""

from __future__ import annotations

import pytest

from stock_cli.chemical_deep_dive import main, normalize_commodity_symbol


def test_normalize_commodity_symbol() -> None:
    # 纯碱
    assert normalize_commodity_symbol("SA") == "soda_ash"
    assert normalize_commodity_symbol("soda_ash") == "soda_ash"
    assert normalize_commodity_symbol("纯碱") == "soda_ash"

    # PVC
    assert normalize_commodity_symbol("V") == "pvc"
    assert normalize_commodity_symbol("pvc") == "pvc"
    assert normalize_commodity_symbol("聚氯乙烯") == "pvc"

    # PTA & TiO2
    assert normalize_commodity_symbol("TA") == "pta"
    assert normalize_commodity_symbol("tio2") == "tio2"

    with pytest.raises(ValueError, match="未识别的化工品种"):
        normalize_commodity_symbol("UNKNOWN_PRODUCT")


def test_chemical_deep_dive_cli_json_pvc() -> None:
    # 验证通过命令行参数调用 PVC 并输出 JSON
    exit_code = main(["--symbol", "V", "--as-of", "2026-09-17", "--format", "json"])
    assert exit_code == 0
