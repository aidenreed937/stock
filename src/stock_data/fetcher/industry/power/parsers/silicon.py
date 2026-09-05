"""硅业分会/安泰科通报解析器。"""

from __future__ import annotations

import re
from typing import Any


def parse_silicon_branch_bulletin_text(text: str) -> dict[str, Any]:
    """从月度通报或周评文本中抽取产出、开工率与库存关键指标。"""
    results: dict[str, Any] = {
        "polysilicon_output_w_tons": None,
        "polysilicon_output_yoy": None,
        "polysilicon_operating_rate": None,
        "wafer_output_gw": None,
        "wafer_output_yoy": None,
        "wafer_operating_rate": None,
        "polysilicon_inventory_w_tons": None,
    }

    poly_month_m = re.search(
        r"(\d{1,2})月[^。；]{0,30}多晶硅产量(?:约|达|为)?\s*([\d.]+)\s*万吨",
        text,
    )
    poly_m = (
        poly_month_m
        or re.search(r"多晶硅产量为?\s*([\d.]+)\s*万吨", text)
        or re.search(r"多晶硅产出\s*([\d.]+)\s*万吨", text)
    )
    if poly_m is None:
        poly_m = re.search(
            r"(?:\d{4}年)?(\d{1,2})月(?:国内)?多晶硅产量(?:约|达|为)?\s*([\d.]+)\s*万吨", text
        )
    if poly_m:
        try:
            results["polysilicon_output_w_tons"] = float(
                poly_m.group(2) if poly_month_m is not None else poly_m.group(poly_m.lastindex or 1)
            )
        except ValueError:
            pass

    wafer_month_m = re.search(
        r"(\d{1,2})月[^。；]{0,30}硅片产量(?:约|达|为)?\s*([\d.]+)\s*GW",
        text,
        re.IGNORECASE,
    )
    wafer_m = (
        wafer_month_m
        or re.search(r"硅片产出\s*([\d.]+)\s*GW", text, re.IGNORECASE)
        or re.search(r"硅片产量为?\s*([\d.]+)\s*GW", text, re.IGNORECASE)
    )
    if wafer_m is None:
        wafer_m = re.search(
            r"(?:\d{4}年)?(\d{1,2})月(?:同期)?硅片产量(?:约|达|为)?\s*([\d.]+)\s*GW",
            text,
            re.IGNORECASE,
        )
    if wafer_m:
        try:
            results["wafer_output_gw"] = float(
                wafer_m.group(2)
                if wafer_month_m is not None
                else wafer_m.group(wafer_m.lastindex or 1)
            )
        except ValueError:
            pass

    poly_op_m = re.search(r"多晶硅.*?开工率为?\s*([\d.]+)%", text)
    if poly_op_m:
        try:
            results["polysilicon_operating_rate"] = float(poly_op_m.group(1))
        except ValueError:
            pass

    wafer_op_m = re.search(r"硅片.*?开工率(?:在|为)?\s*([\d.]+)%", text)
    if wafer_op_m:
        try:
            results["wafer_operating_rate"] = float(wafer_op_m.group(1))
        except ValueError:
            pass

    inv_m = re.search(r"多晶硅库存.*?(?:至|累计约|约)\s*([\d.]+)\s*万吨", text)
    if inv_m is None:
        inv_m = re.search(r"全行业库存累计约\s*([\d.]+)\s*万吨", text)
    if inv_m:
        try:
            results["polysilicon_inventory_w_tons"] = float(inv_m.group(1))
        except ValueError:
            pass

    if results["polysilicon_output_w_tons"] is not None:
        month_match = poly_month_m or re.search(r"(?:\d{4}年)?(\d{1,2})月(?:国内)?多晶硅产量", text)
        if month_match:
            results["report_month_number"] = int(month_match.group(1))
    if results["wafer_output_gw"] is not None and "report_month_number" not in results:
        month_match = wafer_month_m or re.search(r"(?:\d{4}年)?(\d{1,2})月(?:同期)?硅片产量", text)
        if month_match:
            results["report_month_number"] = int(month_match.group(1))

    return results


__all__ = ["parse_silicon_branch_bulletin_text"]
