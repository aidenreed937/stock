"""财联社（CLS）电报流动力电池装车量增量客户端。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from curl_cffi import requests

from stock_data.fetcher.industry.automotive.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.automotive.paths import AutomotiveRawPaths
from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

CLS_ROLL_API_URL = "https://www.cls.cn/v1/roll/get_roll_list"
CLS_DEFAULT_PARAMS = {
    "app": "CailianpressWeb",
    "category": "telegraph",
    "os": "web",
    "refresh_type": "1",
    "rn": "20",
    "sv": "8.4.6",
}
CLS_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=utf-8",
    "Referer": "https://www.cls.cn/telegraph",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# 动力电池月度装车量合理值域门禁 (GWh)
MIN_BATTERY_INSTALLATION_GWH = 40.0
MAX_BATTERY_INSTALLATION_GWH = 150.0


def generate_cls_sign(params: dict[str, Any]) -> str:
    """计算财联社 API 的双哈希签名 (sha1 -> md5)。"""
    sorted_pairs = sorted((k, str(v)) for k, v in params.items() if k != "sign")
    query_str = urlencode(sorted_pairs)
    sha1_hash = hashlib.sha1(query_str.encode("utf-8")).hexdigest()  # noqa: S324
    return hashlib.md5(sha1_hash.encode("utf-8")).hexdigest()  # noqa: S324


def parse_cls_telegraph_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """从单个财联社电报条目中解析动力电池装车量数据。"""
    title = str(item.get("title") or "")
    content = str(item.get("content") or "")
    combined = f"{title}\n{content}"

    if not ("动力电池" in combined or "中国汽车动力电池产业创新联盟" in combined):
        return None

    if "装车量" not in combined:
        return None

    ctime = item.get("ctime")
    if ctime:
        rel_dt = datetime.fromtimestamp(int(ctime), tz=UTC)
        release_date = rel_dt.date()
    else:
        release_date = date.today()

    month_match = re.search(
        r"(20\d\d)\s*年\s*(?:1-)?(\d{1,2})\s*月(?:份)?(?!\s*\d{1,2}\s*日)",
        combined,
    )
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))
    else:
        single_month_match = re.search(r"(\d{1,2})\s*月(?:份)?(?:，|我国|国内|动力电池)", combined)
        if not single_month_match:
            return None
        month = int(single_month_match.group(1))
        year = release_date.year if month <= release_date.month else release_date.year - 1

    report_month = f"{year:04d}-{month:02d}"

    battery_match = re.search(
        r"(?:我国)?(?:国内)?动力(?:和储能)?电池装车量(?:共计|达到|为)?\s*(\d+\.?\d*)\s*(?:GWh|吉瓦时|gwh)",
        combined,
    ) or re.search(
        r"装车量(?:共计|达到|为)?\s*(\d+\.?\d*)\s*(?:GWh|吉瓦时|gwh)",
        combined,
    )
    if not battery_match:
        return None

    gwh_val = float(battery_match.group(1))

    if not (MIN_BATTERY_INSTALLATION_GWH <= gwh_val <= MAX_BATTERY_INSTALLATION_GWH):
        logger.warning(
            "财联社电报装车量数值 %.2f GWh 越界 [%.1f, %.1f]，拒绝采信: %s",
            gwh_val,
            MIN_BATTERY_INSTALLATION_GWH,
            MAX_BATTERY_INSTALLATION_GWH,
            title,
        )
        return None

    yoy_match = re.search(
        r"装车量[^\d]*\d+\.?\d*\s*(?:GWh|吉瓦时|gwh)[^。！\n]{0,50}?(?:同比)?增长(?:约)?(\d+\.?\d*)%",
        combined,
    ) or re.search(
        r"装车量[^。！\n]{0,40}?(?:同比)?增长(?:约)?(\d+\.?\d*)%",
        combined,
    )
    yoy_val = round(float(yoy_match.group(1)) / 100.0, 4) if yoy_match else None

    item_id = item.get("id") or ""
    source_url = (
        f"https://www.cls.cn/detail/{item_id}" if item_id else "https://www.cls.cn/telegraph"
    )

    return {
        "report_month": report_month,
        "release_date": release_date,
        "battery_installation_gwh": round(gwh_val, 2),
        "battery_installation_gwh_raw": str(gwh_val),
        "yoy_growth": yoy_val,
        "yoy_growth_raw": f"{yoy_match.group(1)}%" if yoy_match else None,
        "source": "CABIA",
        "source_url": source_url,
        "collected_at": now_utc_iso(),
    }


def _in_date_range(report_month: str, start_date: date | None, end_date: date | None) -> bool:
    parts = report_month.split("-")
    y, m = int(parts[0]), int(parts[1])
    m_start = date(y, m, 1)
    if start_date and m_start < start_date.replace(day=1):
        return False
    if end_date and m_start > end_date:
        return False
    return True


class ClsBatteryClient:
    """监听财联社电报流，增量捕获 CABIA 动力电池装车量通报。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        *,
        timeout: int = 15,
        impersonate: str = "chrome120",
        api_url: str | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = AutomotiveRawPaths(self.raw_dir)
        self.timeout = timeout
        self.impersonate = impersonate
        self.api_url = api_url or os.getenv("STOCK_CLS_ROLL_API_URL") or CLS_ROLL_API_URL
        self.last_errors: tuple[str, ...] = ()
        self.last_fetched_periods: tuple[str, ...] = ()

    def fetch(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        max_pages: int = 3,
        initial_last_time: int | None = None,
    ) -> dict[str, dict[str, Any]]:
        """从财联社电报流拉取并解析最新的动力电池装车量记录。"""
        self.last_errors = ()
        self.last_fetched_periods = ()
        results: dict[str, dict[str, Any]] = {}
        last_time: int | None = initial_last_time

        for _page in range(1, max_pages + 1):
            params = dict(CLS_DEFAULT_PARAMS)
            if last_time is not None:
                params["last_time"] = str(last_time)

            params["sign"] = generate_cls_sign(params)

            try:
                response = requests.get(
                    self.api_url,
                    params=params,
                    headers=CLS_HEADERS,
                    timeout=self.timeout,
                    impersonate=self.impersonate,
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"财联社电报接口请求失败: {exc}"
                logger.warning(msg)
                self.last_errors = (*self.last_errors, msg)
                break

            status = getattr(response, "status_code", 0)
            if status != 200:
                msg = f"财联社电报接口返回非200状态码: {status}"
                logger.warning(msg)
                self.last_errors = (*self.last_errors, msg)
                break

            try:
                raw_text = getattr(response, "text", "")
                if isinstance(raw_text, str) and raw_text.strip():
                    payload = json.loads(raw_text)
                else:
                    json_fn = response.json
                    payload = json_fn()
            except Exception as exc:  # noqa: BLE001
                msg = f"财联社电报接口 JSON 解析失败: {exc}"
                logger.warning(msg)
                self.last_errors = (*self.last_errors, msg)
                break

            data = payload.get("data", {})
            roll_data = data.get("roll_data", [])
            if not roll_data:
                break

            for item in roll_data:
                parsed = parse_cls_telegraph_item(item)
                if parsed and _in_date_range(parsed["report_month"], start_date, end_date):
                    m_key = parsed["report_month"]
                    if m_key not in results:
                        # 保存原始快照到 2-Tier RAW
                        snapshot_name = f"cls_telegraph_{m_key}.json"
                        raw_bytes = json.dumps(item, ensure_ascii=False, indent=2).encode("utf-8")
                        content_hash = raw_content_sha256(raw_bytes)
                        snapshot_file = self.paths.cabia_dir / snapshot_name
                        snapshot_file.parent.mkdir(parents=True, exist_ok=True)
                        snapshot_file.write_bytes(raw_bytes)
                        parsed["raw_content_sha256"] = content_hash
                        parsed["raw_snapshot_path"] = raw_snapshot_path_value(
                            snapshot_file, self.raw_dir
                        )
                        results[m_key] = parsed
                        logger.info(
                            "财联社增量成功捕获动力电池装车量: %s -> %.2f GWh",
                            m_key,
                            parsed["battery_installation_gwh"],
                        )

            # 更新下一页的分页游标
            last_item = roll_data[-1]
            last_time = last_item.get("ctime")
            if not last_time:
                break

        if results:
            self.last_fetched_periods = tuple(sorted(results.keys()))
        return results

    # 兼容已有测试与调用方的别名方法
    _parse_telegraph_item = staticmethod(parse_cls_telegraph_item)


__all__ = [
    "MAX_BATTERY_INSTALLATION_GWH",
    "MIN_BATTERY_INSTALLATION_GWH",
    "ClsBatteryClient",
    "generate_cls_sign",
    "parse_cls_telegraph_item",
]
