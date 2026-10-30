#!/usr/bin/env python3
"""DRAMeXchange 历史价格页可行性验证脚本（评估能否补全 memory_benchmark / memory_price 缺口）。

背景：`semiconductor_memory_benchmark`（44 月，缺 16 月到 5Y 门槛）与
`semiconductor_memory_price`（仅 2 个交易日覆盖式快照）是半导体黄金表仅有的两块
5Y 分位缺口。候选低成本渠道之一是 DRAMeXchange（集邦旗下）官方历史价格页
`dramexchange.com/intelligence/historical_price`（页面含月份区间选择器，个人非商业
下载声明允许）。本脚本验证该渠道是否真正可行：能否访问、能否回补历史、口径能否
与本地 Curated 表对齐。

页面机制（源自页面内嵌 JS，已人工核对）：
- `GET /Intelligence/getHistoricalFormData?Source=HistoryPriceItem&SpotItemType=N`
  返回可选价格项目表 `data.table[{id, Name}]`
  （N=1 DRAM Spot / 2 DRAM Contract / 3 Flash Spot / 4 Flash Contract / 5 Memory Card）
- `GET /Intelligence/getHistorcalQuery?sBeginDate=&sEndDate=&sItemID=&SpotItemType=&rnd=`
  返回区间价格 `data.table[{price_datex, price_hi, price_lo, price_avg}]`
- `GET /Intelligence/getHistorcalDownloadLink?SpotItemType=&sItemID=` 生成下载链接

实测结论（2026-09-11）：**项目列表端点公开**（`getHistoricalFormData` 带
`SpotItemType` 参数时无登录即返回 JSON 项目表，共 19 个 DRAM Spot 项目）；但
**历史价格查询与 DXI 指数需登录**（`getHistorcalQuery` 返回 `NotLogin`、
`/Market/DXI` 重定向到 `/Member/Login`）。故无登录时可枚举可用价格序列，但无法
回补历史数值；带 `--cookie` 时才可做数据级验证与本地口径对账。

用法：
  uv run python scripts/probe_dramexchange_history.py
  uv run python scripts/probe_dramexchange_history.py --cookie "ASP.NET_SessionId=...; .AspNetCore.Cookies=..."
  uv run python scripts/probe_dramexchange_history.py --interval-start 2021-08-01 --interval-end 2022-11-30
  uv run python scripts/probe_dramexchange_history.py --output data/analytics/industry/probe_dramexchange.json

登录 Cookie 的读取顺序：--cookie 参数 > 环境变量 DRAMEXCHANGE_COOKIE > 项目 .env 文件
（.env 不入库，配置示例见 .env.example 中 DRAMEXCHANGE_COOKIE 条目）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from curl_cffi import requests

BASE_URL = "https://www.dramexchange.com"
FORM_DATA_URL = f"{BASE_URL}/Intelligence/getHistoricalFormData"
QUERY_URL = f"{BASE_URL}/Intelligence/getHistorcalQuery"
DOWNLOAD_URL = f"{BASE_URL}/Intelligence/getHistorcalDownloadLink"
DXI_URL = f"{BASE_URL}/Market/DXI"

ENV_COOKIE = "DRAMEXCHANGE_COOKIE"

SPOT_ITEM_TYPES: dict[str, str] = {
    "1": "DRAM Spot",
    "2": "DRAM Contract",
    "3": "Flash Spot",
    "4": "Flash Contract",
    "5": "Memory Card",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/intelligence/historical_price",
}

LOCAL_BENCHMARK = Path(
    "data/curated/industry/semiconductor/price/semiconductor_memory_benchmark.parquet"
)


def _read_cookie_from_env_file() -> str:
    """从项目根 .env 解析 DRAMEXCHANGE_COOKIE（同 settings._read_env_no_proxy 风格）。

    独立脚本不加载 pydantic-settings，这里显式解析 .env 单键，
    与项目"密钥放 .env、不入库"的约定保持一致。
    """
    env_file = Path(".env")
    if not env_file.exists():
        return ""
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{ENV_COOKIE}="):
                return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        return ""
    return ""


def _get(url: str, cookie: str | None) -> tuple[Any | None, str | None]:
    """GET 请求；返回 (响应对象, 错误信息)。"""
    headers = dict(HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    try:
        resp = requests.get(url, headers=headers, impersonate="chrome120", timeout=20)
    except Exception as exc:  # noqa: BLE001
        return None, f"request_error: {exc}"
    if resp.status_code != 200:
        return resp, f"http_{resp.status_code}"
    return resp, None


def probe_login_gate(cookie: str | None) -> list[dict[str, str]]:
    """探测各端点登录门槛（无 cookie 时即为可行性结论的主体）。"""
    results: list[dict[str, str]] = []

    # 1. 项目列表端点
    resp, err = _get(f"{FORM_DATA_URL}?Source=HistoryPriceItem&SpotItemType=1", cookie)
    if err:
        results.append({"endpoint": "getHistoricalFormData", "verdict": "error", "detail": err})
    elif "錯誤" in resp.text or "<html" in resp.text[:200].lower():
        results.append(
            {
                "endpoint": "getHistoricalFormData",
                "verdict": "login_required",
                "detail": "未登录返回错误页（HTML），项目列表不公开",
            }
        )
    else:
        results.append(
            {
                "endpoint": "getHistoricalFormData",
                "verdict": "public",
                "detail": f"返回 {resp.text[:120]!r}",
            }
        )

    # 2. 历史价格查询端点
    resp, err = _get(
        f"{QUERY_URL}?sBeginDate=2022-08-01&sEndDate=2022-11-30&sItemID=1&SpotItemType=1&rnd=1",
        cookie,
    )
    if err:
        results.append({"endpoint": "getHistorcalQuery", "verdict": "error", "detail": err})
    elif resp.text.strip() == "NotLogin":
        results.append(
            {
                "endpoint": "getHistorcalQuery",
                "verdict": "login_required",
                "detail": "返回 NotLogin，历史价格查询不公开",
            }
        )
    elif resp.text.strip().startswith("{"):
        results.append(
            {
                "endpoint": "getHistorcalQuery",
                "verdict": "public",
                "detail": f"返回 JSON：{resp.text[:160]!r}",
            }
        )
    else:
        results.append(
            {
                "endpoint": "getHistorcalQuery",
                "verdict": "unknown",
                "detail": f"返回 {resp.text[:160]!r}",
            }
        )

    # 3. DXI 市场页（历史指数入口）
    resp, err = _get(DXI_URL, cookie)
    if err:
        results.append({"endpoint": "/Market/DXI", "verdict": "error", "detail": err})
    elif resp.status_code in (301, 302) or "Member/Login" in resp.text:
        results.append(
            {
                "endpoint": "/Market/DXI",
                "verdict": "login_required",
                "detail": f"HTTP {resp.status_code} 重定向到登录页，DXI 历史不公开",
            }
        )
    else:
        results.append(
            {"endpoint": "/Market/DXI", "verdict": "public", "detail": f"HTTP {resp.status_code}"}
        )
    return results


def fetch_items(cookie: str, spot_type: str) -> list[dict[str, str]]:
    """拉取某 SpotItemType 的价格项目列表。"""
    resp, err = _get(f"{FORM_DATA_URL}?Source=HistoryPriceItem&SpotItemType={spot_type}", cookie)
    if err or resp is None:
        return []
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        return []
    return [
        {"id": str(item.get("id")), "name": str(item.get("Name"))}
        for item in payload.get("table", [])
        if item.get("id")
    ]


def fetch_history(
    cookie: str, spot_type: str, item_id: str, start: date, end: date
) -> list[dict[str, Any]]:
    """按日期区间拉取单项目历史价格。"""
    url = (
        f"{QUERY_URL}?sBeginDate={start.isoformat()}&sEndDate={end.isoformat()}"
        f"&sItemID={item_id}&SpotItemType={spot_type}&rnd=1"
    )
    resp, err = _get(url, cookie)
    if err or resp is None:
        return []
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        return []
    return payload.get("table", [])


def reconcile_with_local(
    rows: list[dict[str, Any]], spot_type: str, item_name: str
) -> dict[str, Any]:
    """DRAMeXchange 日度价 vs 本地月度 benchmark：聚合月度均值并对比重叠月份量级。

    仅当外部序列与本地 benchmark 有重叠月份时才能做量级对账；
    无重叠（如只拉 2021-08~2022-11 缺口区间）时输出时间覆盖结论并跳过量级比。
    """
    if not rows:
        return {"item": item_name, "rows": 0, "note": "无数据"}

    ext = pl.DataFrame(rows).with_columns(pl.col("price_datex").str.to_date().alias("trade_date"))
    ext = ext.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("month"))
    ext_monthly = (
        ext.group_by("month")
        .agg(pl.col("price_avg").cast(pl.Float64).mean().alias("avg_price_usd"))
        .sort("month")
    )

    result: dict[str, Any] = {
        "item": item_name,
        "spot_type": spot_type,
        "rows": len(rows),
        "coverage": f"{ext['trade_date'].min()} .. {ext['trade_date'].max()}",
        "months": ext_monthly["month"].to_list(),
        "monthly_avg_samples": [
            {"month": m, "avg_price_usd": round(float(p), 3)} for m, p in ext_monthly.iter_rows()
        ][:6],
    }

    # 与本地 benchmark 重叠月份对账
    if LOCAL_BENCHMARK.exists() and "avg_price_usd" in ext_monthly.columns:
        local = pl.read_parquet(LOCAL_BENCHMARK)
        # 外部 Spot 类型只对 benchmark 的现货类指标做量级对比
        if "product_family" in local.columns and "report_month" in local.columns:
            local_monthly = (
                local.select(["report_month", "price_usd"])
                .with_columns(pl.col("report_month").cast(pl.Utf8).alias("month"))
                .group_by("month")
                .agg(pl.col("price_usd").mean().alias("local_price_usd"))
            )
            joined = ext_monthly.join(local_monthly, on="month", how="inner")
            if joined.is_empty():
                result["reconcile"] = "无重叠月份（本地 benchmark 起始 2022-12），无法量级对账"
            else:
                joined = joined.with_columns(
                    (pl.col("avg_price_usd") / pl.col("local_price_usd")).alias("ratio")
                )
                ratios = joined["ratio"].to_list()
                result["reconcile"] = {
                    "overlap_months": len(joined),
                    "ratio_min": round(min(ratios), 3),
                    "ratio_max": round(max(ratios), 3),
                    "ratio_median": round(float(pl.Series(ratios).median()), 3),
                    "samples": [
                        {
                            "month": m,
                            "ext": round(float(e), 3),
                            "local": round(float(lv), 3),
                            "ratio": round(float(r), 3),
                        }
                        for m, e, lv, r in joined.iter_rows()
                    ][:5],
                }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="DRAMeXchange 历史价格页可行性验证")
    parser.add_argument(
        "--cookie",
        default=None,
        help=f"DRAMeXchange 登录 Cookie（可选；缺省读环境变量 {ENV_COOKIE}）",
    )
    parser.add_argument(
        "--interval-start",
        default="2021-08-01",
        help="回补验证区间起点（默认 2021-08-01，即 benchmark 5Y 缺口起点）",
    )
    parser.add_argument(
        "--interval-end",
        default="2022-11-30",
        help="回补验证区间终点（默认 2022-11-30，即 benchmark 现有 44 月之前）",
    )
    parser.add_argument("--output", default=None, help="可选：结果 JSON 落盘路径")
    parser.add_argument(
        "--max-items",
        type=int,
        default=2,
        help="带登录态验证时每类 SpotItemType 最多做历史查询的项目数（默认 2，控制耗时）",
    )
    args = parser.parse_args()

    # Cookie 读取顺序：--cookie 参数 > 环境变量 > 项目 .env 文件
    cookie = args.cookie or os.environ.get(ENV_COOKIE) or _read_cookie_from_env_file() or None

    start = date.fromisoformat(args.interval_start)
    end = date.fromisoformat(args.interval_end)

    print("== Step 1: 登录门槛探测 ==")
    gates = probe_login_gate(cookie)
    for g in gates:
        print(f"  [{g['endpoint']}] {g['verdict']} — {g['detail']}")
    query_gate = next(g for g in gates if g["endpoint"] == "getHistorcalQuery")
    query_locked = query_gate["verdict"] == "login_required"

    report: dict[str, Any] = {"gates": gates}

    if not cookie:
        print("\n== 结论（无登录态）==")
        if query_locked:
            print(
                "项目列表端点公开（可枚举可用价格序列），但历史价格查询与 DXI 指数\n"
                "要求登录，免费公开无法回补历史数值。该渠道不是'零成本'通道：需要\n"
                "DRAMeXchange 账号（TrendForce 系，通常随订阅/会员开通）才能取历史\n"
                "序列。若要继续验证数据可用性与口径，请登录后传 --cookie 重跑。"
            )
        else:
            print("历史查询端点公开，可低成本回补（可用性以实际响应为准，见上）。")
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"报告已写入 {args.output}")
        return 0

    print("\n== Step 2: 带登录态数据验证 ==")
    for st, st_name in SPOT_ITEM_TYPES.items():
        items = fetch_items(cookie, st)
        print(f"\n[{st_name}] 项目数={len(items)}")
        for item in items[: args.max_items]:
            rows = fetch_history(cookie, st, item["id"], start, end)
            r = reconcile_with_local(rows, st, item["name"])
            print(f"  item={item['name']} rows={r['rows']} coverage={r.get('coverage', '-')}")
            if "reconcile" in r:
                print(f"    对账: {r['reconcile']}")
            report.setdefault("data", []).append(r)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\n报告已写入 {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
