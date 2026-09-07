"""Comtrade 在线 API 与 Tariffline 调用能力。"""

from __future__ import annotations

import gzip
import json
import logging
from collections.abc import Sequence
from typing import Any, cast

from stock_data.fetcher.industry.customs.collectors.comtrade_helpers import (
    _MAX_CMD_CODE_LENGTH,
    chunk_hs_codes,
    normalize_flow_code,
)
from stock_data.fetcher.industry.customs.collectors.tariffline import (
    _MAX_RECORDS,
    fetch_tariffline_snapshot,
)
from stock_data.fetcher.industry.customs.models import CustomsTradeRecord
from stock_data.fetcher.industry.customs.parsers.catalog import (
    get_hs6_query_list,
    parse_comtrade_items,
)

logger = logging.getLogger(__name__)


class ComtradeApiMixin:
    """为 ComtradeCollector 提供在线 API 方法。"""

    def parse_api_records(self: Any, items: list[dict[str, Any]]) -> list[CustomsTradeRecord]:
        """将 API 返回的字典列表转换为标准记录。"""
        return parse_comtrade_items(items, self._catalog_map)

    def fetch_api(
        self: Any,
        period: str | list[str],
        output_name: str | None = None,
        flow_code: str = "X",
    ) -> list[dict[str, Any]]:
        """调用 UN Comtrade 官方 SDK 并保存 RAW Gzip 快照。"""
        try:
            import comtradeapicall
        except ImportError:
            logger.error("未安装 comtradeapicall，请先执行 `pip install comtradeapicall`")
            return []

        hs_codes = get_hs6_query_list(self.catalog_path)
        if not hs_codes:
            logger.warning("HS 编码列表为空，取消请求")
            return []

        normalized_flow = normalize_flow_code(flow_code)
        period_param = ",".join(period) if isinstance(period, list | tuple) else str(period)
        save_stem = output_name or period_param.replace(",", "_")
        snapshot_suffix = f"_{normalized_flow.replace(',', '_')}"
        hs_code_chunks = chunk_hs_codes(hs_codes, _MAX_CMD_CODE_LENGTH)
        logger.info(
            "正在请求 UN Comtrade 官方 API: periods=%s, flow=%s, cmdCodes=%d 个, batches=%d",
            period_param,
            normalized_flow,
            len(hs_codes),
            len(hs_code_chunks),
        )

        records_dict: list[dict[str, Any]] = []
        for batch_index, hs_code_chunk in enumerate(hs_code_chunks, start=1):
            cmd_param = ",".join(hs_code_chunk)
            try:
                frame = comtradeapicall.getFinalData(
                    subscription_key=self.subscription_key,
                    typeCode="C",
                    freqCode="M",
                    clCode="HS",
                    period=period_param,
                    reporterCode="156",
                    cmdCode=cmd_param,
                    flowCode=normalized_flow,
                    partnerCode="0",
                    partner2Code="0",
                    customsCode="C00",
                    motCode="0",
                    maxRecords=250000,
                    format_output="JSON",
                )
                if frame is None or frame.empty:
                    logger.warning(
                        "Comtrade API 返回空数据: period=%s, batch=%d/%d",
                        period,
                        batch_index,
                        len(hs_code_chunks),
                    )
                    continue
                records_dict.extend(cast("list[dict[str, Any]]", frame.to_dict(orient="records")))
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Comtrade API 请求失败: period=%s, batch=%d/%d, error=%s",
                    period,
                    batch_index,
                    len(hs_code_chunks),
                    exc,
                )

        if not records_dict:
            return []
        logger.info("Comtrade API 查询成功: period=%s, records=%d", period, len(records_dict))
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = self.raw_dir / f"{save_stem}{snapshot_suffix}.json.gz"
        with gzip.open(snapshot_file, "wt", encoding="utf-8") as file_obj:
            json.dump({"data": records_dict}, file_obj, ensure_ascii=False)
        return records_dict

    def fetch_tariffline_api(
        self: Any,
        period: str | list[str],
        output_name: str | None = None,
        flow_code: str = "X",
        cmd_codes: Sequence[str] | None = None,
        max_records: int = _MAX_RECORDS,
    ) -> list[dict[str, Any]]:
        """拉取并保存 UN Comtrade Tariffline 原始八位税则线快照。"""
        query_codes = self.get_tariffline_query_list() if cmd_codes is None else list(cmd_codes)
        return fetch_tariffline_snapshot(
            subscription_key=self.subscription_key or "",
            raw_dir=self.tariffline_raw_dir,
            period=period,
            flow_code=flow_code,
            cmd_codes=query_codes,
            output_name=output_name,
            max_records=max_records,
        )


__all__ = ["ComtradeApiMixin"]
