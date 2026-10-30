#!/usr/bin/env python3
"""大连商品交易所 (DCE) Chrome CDP 自动化采集器。

针对大商所全站部署瑞数动态安全（412 JS 挑战）机制，复用本机 Chrome CDP 调试实例
（端口 9222），在真实浏览器环境中执行导出与抓取，打通日度行情与交割仓单双通道，
补全 EG（乙二醇）、V（PVC）、EB（苯乙烯）、PP、L 等大宗化工期货数据。

用法:
    # 采集单日全部数据 (行情 + 仓单)
    uv run python scripts/cdp/dce_cdp_automation.py --date 2026-09-15 --mode all

    # 采集区间仓单并自动触发 2-Tier 物化
    uv run python scripts/cdp/dce_cdp_automation.py --start-date 2026-01-01 --end-date 2026-09-15 --mode inventory --sync

    # 探测 CDP 连接状态 (不写盘)
    uv run python scripts/cdp/dce_cdp_automation.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from datetime import time as time_cls
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import websocket  # noqa: E402

from stock_data.fetcher.industry.chemicals.collectors.futures_price import (  # noqa: E402
    FuturesPriceCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.inventory import (  # noqa: E402
    FuturesInventoryCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.official import (  # noqa: E402
    DEFAULT_DCE_INVENTORY_COMMODITIES,
    parse_dce_daily_text,
    parse_dce_inventory_text,
)

logger = logging.getLogger("dce_cdp")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

DEFAULT_CDP_PORT = 9222
DEFAULT_RAW_DIR = _ROOT / "data" / "raw" / "industry"
DCE_REPORT_SPA_URL = (
    "http://www.dce.com.cn/frontend/dcereport/#/zh/dayFuturesQuotation?variety=all&tradeType=1"
)
TARGET_CHEMICAL_PREFIXES = ("EG", "V", "PP", "L", "EB")


class CdpClient:
    """轻量同步 Chrome DevTools Protocol (CDP) 客户端。"""

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self._seq = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """向 CDP 发送方法指令并等待响应。"""
        self._seq += 1
        msg_id = self._seq
        payload = {"id": msg_id, "method": method, "params": params or {}}
        self.ws.send(json.dumps(payload))
        while True:
            raw = self.ws.recv()
            if not isinstance(raw, str):
                continue
            data = json.loads(raw)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"CDP error on {method}: {data['error']}")
                return dict(data.get("result", {}))

    def evaluate(self, expression: str) -> Any:
        """在页面上下文执行 JavaScript 并返回结果值。"""
        res = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
        result_obj = res.get("result", {})
        if result_obj.get("subtype") == "error":
            raise RuntimeError(f"JS eval error: {result_obj.get('description')}")
        return result_obj.get("value")

    def navigate(self, url: str) -> None:
        """导航至指定 URL 并等待初始加载。"""
        self.call("Page.navigate", {"url": url})
        time.sleep(2.5)

    def close(self) -> None:
        """关闭 WebSocket 连接。"""
        try:
            self.ws.close()
        except Exception:
            pass


def find_chrome_ws_url(port: int = DEFAULT_CDP_PORT) -> str:
    """发现本机运行中 Chrome 的 WebSocket 调试地址。"""
    url = f"http://127.0.0.1:{port}/json"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            targets = json.loads(resp.read().decode())
    except Exception as exc:
        raise ConnectionRefusedError(
            f"无法连接到 Chrome CDP 调试端口 {port}。请先在宿主机启动带 GUI 的 Chrome 调试实例（严禁使用 --headless）：\n"
            f"/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
            f"--remote-debugging-port={port} "
            f"--user-data-dir=/Users/mac/.chrome_cdp_profile "
            f"--disable-blink-features=AutomationControlled\n"
            f"提示：若在沙箱或受限自动化环境中运行，必须确保具有宿主机权限以避免 SingletonLock 权限拒绝。"
        ) from exc

    for t in targets:
        if t.get("type") == "page" and "webSocketDebuggerUrl" in t:
            return str(t["webSocketDebuggerUrl"])
    if targets and "webSocketDebuggerUrl" in targets[0]:
        return str(targets[0]["webSocketDebuggerUrl"])
    raise RuntimeError(f"未在端口 {port} 找到可用的 Chrome Page 调试目标")


def ensure_dce_session(cdp: CdpClient, timeout_sec: int = 40) -> bool:
    """确保 Chrome 当前处于大商所前端环境并完成瑞数动态挑战。"""
    # 1. 显式检测 Headless 状态，避免在无头模式下因瑞数拦截而静默失败
    try:
        is_headless = bool(
            cdp.evaluate(
                "Boolean(navigator.webdriver || /HeadlessChrome/.test(navigator.userAgent))"
            )
        )
        if is_headless:
            logger.error(
                "【致命警告】检测到 Chrome 运行在 Headless (无头) 模式！\n"
                "大商所部署了瑞数动态安全防护 (Bot Detection)，无头模式会被永久拦截在 JS 动态 challenge 页面，导致数据接口全部返回空。\n"
                "请务必在宿主机启动带界面的原生 Chrome 实例（严禁携带 --headless 参数）！"
            )
    except Exception:
        pass

    try:
        cur_url = str(cdp.evaluate("window.location.href") or "")
        ready = cdp.evaluate("document.readyState")
        title = str(cdp.evaluate("document.title") or "")
        has_app = bool(cdp.evaluate("Boolean(document.querySelector('#app'))"))
        # 必须排除瑞数动态 challenge 验证页（通常 URL 携带 2kiG 参数且无真实标题/APP 容器）
        if "dcereport" in cur_url and ready == "complete" and has_app and bool(title):
            logger.info("Chrome 当前已处于大商所报表前端: %s (标题: %s)", cur_url, title)
            return True
    except Exception:
        pass

    logger.info("正在导航至大商所报表平台验证环境与会话有效性...")
    cdp.navigate(DCE_REPORT_SPA_URL)
    start = time.time()
    while time.time() - start < timeout_sec:
        time.sleep(1.0)
        try:
            status = cdp.evaluate("document.readyState")
            title = str(cdp.evaluate("document.title") or "")
            cur_url = str(cdp.evaluate("window.location.href") or "")
            has_app = bool(cdp.evaluate("Boolean(document.querySelector('#app'))"))
            # 严格确保 Vue SPA 核心 DOM (#app) 与标题已真实渲染，而非停留在瑞数 412 动态 challenge
            if status == "complete" and has_app and bool(title) and "dcereport" in cur_url:
                logger.info("大商所页面就绪，会话通过: %s (URL: %s)", title, cur_url)
                return True
        except Exception:
            continue
    logger.warning(
        "大商所页面加载未在预定时间内确认通过（可能卡在瑞数 challenge）。"
        "若采集返回为空，请在打开的 Chrome 窗口中手动刷新一次大商所报表页面完成初始人机挑战。"
    )
    return False


def format_dce_quotes_tsv(items: list[dict[str, Any]]) -> str:
    """将大商所日行情 REST API 返回的合约列表转换为标准 TSV 文本格式。

    完全兼容下游 parse_dce_daily_text 的表头与字段提取规则。
    """
    lines = ["合约代码\t今开盘\t今最高\t今最低\t今收盘\t今结算\t成交量\t持仓量"]
    for item in items:
        contract_id = str(item.get("contractId") or item.get("contract_id") or "").strip()
        if not contract_id:
            continue
        open_val = item.get("open") or ""
        high_val = item.get("high") or ""
        low_val = item.get("low") or ""
        close_val = item.get("close") or ""
        settle_val = item.get("clearPrice") or item.get("settle") or close_val or ""
        vol_val = item.get("volumn") if item.get("volumn") is not None else item.get("volume") or ""
        oi_val = (
            item.get("openInterest")
            if item.get("openInterest") is not None
            else item.get("open_interest") or ""
        )
        lines.append(
            f"{contract_id}\t{open_val}\t{high_val}\t{low_val}\t{close_val}\t{settle_val}\t{vol_val}\t{oi_val}"
        )
    return "\n".join(lines) + "\n"


def format_dce_inventory_text(entity_list: list[dict[str, Any]]) -> str:
    """将大商所仓单日报 REST API 返回的 entityList 转换为标准官方日报文本。

    完全兼容下游 parse_dce_inventory_text 的品种定位与总计行提取规则。
    """
    by_variety: dict[str, list[dict[str, Any]]] = {}
    for item in entity_list:
        raw_name = str(item.get("variety") or "").strip()
        order = str(item.get("varietyOrder") or "").strip().lower()
        clean_name = raw_name.replace("小计", "").replace("总计", "").replace("合计", "").strip()
        if not clean_name and order:
            clean_name = order.upper()
        if not clean_name:
            continue
        by_variety.setdefault(clean_name, []).append(item)

    output_blocks: list[str] = []
    for v_name, items in by_variety.items():
        subtotal_item = next(
            (x for x in items if "计" in str(x.get("variety") or "") or not x.get("whAbbr")),
            None,
        )
        block_lines = [
            f"品种：{v_name}",
            "仓库/分库\t昨日仓单量\t今日仓单量\t增减",
        ]
        has_warehouse_rows = False
        tot_last = 0
        tot_today = 0
        tot_diff = 0

        for it in items:
            if it is subtotal_item:
                continue
            wh = str(it.get("whAbbr") or "").strip()
            if not wh:
                continue
            has_warehouse_rows = True
            last_q = int(it.get("lastWbillQty") or 0)
            today_q = int(it.get("wbillQty") or 0)
            diff_q = int(it.get("diff")) if it.get("diff") is not None else (today_q - last_q)
            tot_last += last_q
            tot_today += today_q
            tot_diff += diff_q
            block_lines.append(f"{wh}\t{last_q}\t{today_q}\t{diff_q}")

        if subtotal_item is not None:
            sub_last = int(subtotal_item.get("lastWbillQty") or 0)
            sub_today = int(subtotal_item.get("wbillQty") or 0)
            sub_diff = (
                int(subtotal_item.get("diff"))
                if subtotal_item.get("diff") is not None
                else (sub_today - sub_last)
            )
            block_lines.append(f"总计\t{sub_last}\t{sub_today}\t{sub_diff}")
        elif has_warehouse_rows:
            block_lines.append(f"总计\t{tot_last}\t{tot_today}\t{tot_diff}")

        output_blocks.append("\n".join(block_lines))

    return "\n\n".join(output_blocks) + "\n"


def fetch_dce_quotes_via_cdp(cdp: CdpClient, trade_date: date) -> str | None:
    """通过浏览器环境异步调用日行情 REST API 并格式化为标准 TSV 文本快照。"""
    yyyymmdd = trade_date.strftime("%Y%m%d")
    js = f"""(async () => {{
        const payload = JSON.stringify({{
            varietyId: "all",
            tradeDate: "{yyyymmdd}",
            tradeType: "1",
            contractId: "",
            lang: "zh",
            optionSeries: "",
            statisticsType: 0
        }});
        const res = await fetch("/dcereport/publicweb/dailystat/dayQuotes", {{
            method: "POST",
            headers: {{
                "Content-Type": "application/json;charset=UTF-8",
                "Accept": "application/json, text/plain, */*"
            }},
            body: payload
        }});
        if (res.status !== 200) return null;
        return await res.json();
    }})()"""
    try:
        raw_res = cdp.evaluate(js)
        if not raw_res or not isinstance(raw_res, dict):
            return None
        code = str(raw_res.get("code") or "")
        if code != "200":
            logger.debug(
                "[%s] 日行情 API 响应码非 200: %s (%s)", yyyymmdd, code, raw_res.get("msg")
            )
            return None
        data = raw_res.get("data")
        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("entityList") or []
        if not items:
            logger.debug("[%s] 日行情接口返回空列表（非交易日或未发布）", yyyymmdd)
            return None

        tsv_text = format_dce_quotes_tsv(items)
        parsed = parse_dce_daily_text(tsv_text, TARGET_CHEMICAL_PREFIXES)
        if not parsed:
            logger.debug("[%s] 日行情导出无目标化工合约", yyyymmdd)
            return None
        return tsv_text
    except Exception as exc:
        logger.warning("[%s] 导出日行情异常: %s", yyyymmdd, exc)
        return None


def fetch_dce_inventory_via_cdp(cdp: CdpClient, trade_date: date) -> str | None:
    """通过浏览器环境异步调用仓单日报 REST API 并格式化为标准官方日报文本快照。"""
    yyyymmdd = trade_date.strftime("%Y%m%d")
    js = f"""(async () => {{
        const payload = JSON.stringify({{
            varietyId: "all",
            tradeDate: "{yyyymmdd}"
        }});
        const res = await fetch("/dcereport/publicweb/dailystat/wbillWeeklyQuotes", {{
            method: "POST",
            headers: {{
                "Content-Type": "application/json;charset=UTF-8",
                "Accept": "application/json, text/plain, */*"
            }},
            body: payload
        }});
        if (res.status !== 200) return null;
        return await res.json();
    }})()"""
    try:
        raw_res = cdp.evaluate(js)
        if not raw_res or not isinstance(raw_res, dict):
            return None
        code = str(raw_res.get("code") or "")
        if code != "200":
            logger.debug(
                "[%s] 仓单日报 API 响应码非 200: %s (%s)", yyyymmdd, code, raw_res.get("msg")
            )
            return None
        data = raw_res.get("data") or {}
        entities = data.get("entityList") or []
        if not entities:
            logger.debug("[%s] 仓单日报接口返回空列表（非交易日或未发布）", yyyymmdd)
            return None

        inv_text = format_dce_inventory_text(entities)
        parsed = parse_dce_inventory_text(inv_text, DEFAULT_DCE_INVENTORY_COMMODITIES)
        valid_items = {k: v for k, v in parsed.items() if v[0] is not None or v[1] is not None}
        if not valid_items:
            logger.debug("[%s] 仓单日报导出无有效化工仓单记录", yyyymmdd)
            return None
        return inv_text
    except Exception as exc:
        logger.warning("[%s] 导出仓单日报异常: %s", yyyymmdd, exc)
        return None


def save_raw_quotes(raw_dir: Path, trade_date: date, content: str) -> Path:
    """将日行情文本保存至标准 2-Tier 缓存路径。"""
    cache_file = (
        raw_dir
        / "chemicals"
        / "futures_daily"
        / "dce_daily_cache"
        / trade_date.strftime("%Y")
        / f"{trade_date.strftime('%Y%m%d')}.txt"
    )
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(content, encoding="utf-8")
    return cache_file


def save_raw_inventory(raw_dir: Path, trade_date: date, content: str) -> Path:
    """将仓单日报文本保存至标准 2-Tier 缓存路径。"""
    cache_file = (
        raw_dir
        / "chemicals"
        / "futures_inventory"
        / "dce"
        / trade_date.strftime("%Y")
        / f"{trade_date.strftime('%Y%m%d')}.txt"
    )
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(content, encoding="utf-8")
    return cache_file


def generate_date_range(start_date: date, end_date: date) -> list[date]:
    """生成自然日列表（自动过滤周末）。"""
    curr = start_date
    dates: list[date] = []
    while curr <= end_date:
        if curr.weekday() < 5:
            dates.append(curr)
        curr += timedelta(days=1)
    return dates


def get_local_cached_dates(raw_dir: Path, subpath: str) -> set[date]:
    """扫描指定 RAW 缓存目录中已存在且大小有效的快照日期。"""
    cache_root = raw_dir / "chemicals" / subpath
    dates: set[date] = set()
    if not cache_root.exists():
        return dates
    for file in cache_root.glob("*/*.txt"):
        if file.is_file() and file.stat().st_size > 100:
            stem = file.stem
            try:
                d = date(int(stem[:4]), int(stem[4:6]), int(stem[6:8]))
                dates.add(d)
            except ValueError:
                continue
    return dates


def is_publish_time_ready(t_date: date, mode: str, now: datetime | None = None) -> tuple[bool, str]:
    """检查指定日期的数据在当前时间是否已在交易所发布。

    规则:
    1. 非工作日（周六周日）直接判定跳过；
    2. 历史交易日（早于今天）均已发布；
    3. 针对当天 (today):
       - 日行情一般在 15:30 以后产生；
       - 仓单日报一般在 16:30 以后产生。
    """
    if t_date.weekday() >= 5:
        return False, f"{t_date} 为周末非交易日"

    current = now or datetime.now()
    today = current.date()
    if t_date < today:
        return True, "历史交易日，已归档"
    if t_date > today:
        return False, f"{t_date} 为未来日期"

    cur_time = current.time()
    quotes_pub_time = time_cls(15, 30)
    inventory_pub_time = time_cls(16, 30)

    if mode == "quotes" and cur_time < quotes_pub_time:
        return False, f"大商所日行情通常在 15:30 后发布（当前 {cur_time.strftime('%H:%M')}）"
    if mode == "inventory" and cur_time < inventory_pub_time:
        return False, f"大商所仓单日报通常在 16:30 后发布（当前 {cur_time.strftime('%H:%M')}）"
    if mode == "all" and cur_time < quotes_pub_time:
        return False, f"今日大商所尚未收盘结算（当前 {cur_time.strftime('%H:%M')}）"

    return True, "已过发布窗口，可拉取"


def resolve_smart_harvest_plan(
    raw_dir: Path,
    mode: str,
    explicit_date: date | None = None,
    explicit_start: date | None = None,
    explicit_end: date | None = None,
    fill_gaps: bool = False,
    force: bool = False,
    now: datetime | None = None,
) -> tuple[list[date], dict[str, Any]]:
    """智能解析并规划采集日期队列。

    支持三种场景:
    1. 显式单日或区间 (--date / --start-date & --end-date)；
    2. 缺口自愈探测模式 (--fill-gaps)：扫描历史区间找出所有漏采的工作日；
    3. 默认全自动智能增量 (未传日期)：自动探查本地最高水位，从 Watermark + 1 追赶至今日。
    """
    cached_quotes = get_local_cached_dates(raw_dir, "futures_daily/dce_daily_cache")
    cached_inv = get_local_cached_dates(raw_dir, "futures_inventory/dce")
    current_dt = now or datetime.now()
    today = current_dt.date()

    meta: dict[str, Any] = {
        "cached_quotes_count": len(cached_quotes),
        "cached_inv_count": len(cached_inv),
        "max_quotes_date": max(cached_quotes).isoformat() if cached_quotes else None,
        "max_inv_date": max(cached_inv).isoformat() if cached_inv else None,
    }

    if explicit_date:
        return [explicit_date], meta

    if explicit_start and explicit_end:
        candidates = generate_date_range(explicit_start, explicit_end)
    elif fill_gaps:
        all_cached = cached_quotes | cached_inv
        earliest_cached = min(all_cached) if all_cached else (today - timedelta(days=365))
        candidates = generate_date_range(earliest_cached, today)
    else:
        watermark_dates: list[date] = []
        if mode in ("all", "quotes") and cached_quotes:
            watermark_dates.append(max(cached_quotes))
        if mode in ("all", "inventory") and cached_inv:
            watermark_dates.append(max(cached_inv))

        if watermark_dates:
            watermark = min(watermark_dates)
            start_d = watermark + timedelta(days=1)
        else:
            start_d = today - timedelta(days=30)

        candidates = generate_date_range(start_d, today)

    final_dates: list[date] = []
    skipped_cache: list[date] = []
    skipped_timing: list[date] = []

    for d in candidates:
        ready, _ = is_publish_time_ready(d, mode, now=current_dt)
        if not ready:
            skipped_timing.append(d)
            continue

        has_q = d in cached_quotes
        has_i = d in cached_inv
        is_fully_cached = (
            (has_q and has_i) if mode == "all" else (has_q if mode == "quotes" else has_i)
        )

        if is_fully_cached and not force:
            skipped_cache.append(d)
        else:
            final_dates.append(d)

    meta["candidate_dates_count"] = len(candidates)
    meta["planned_dates_count"] = len(final_dates)
    meta["skipped_cached_count"] = len(skipped_cache)
    meta["skipped_timing_count"] = len(skipped_timing)

    return sorted(final_dates), meta


def run_cdp_harvest(
    cdp: CdpClient,
    target_dates: list[date],
    mode: str,
    raw_dir: Path,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[int, int]:
    """执行批量采集调度循环（支持单项缓存命中跳过）。"""
    quotes_count = 0
    inventory_count = 0

    cached_quotes = get_local_cached_dates(raw_dir, "futures_daily/dce_daily_cache")
    cached_inv = get_local_cached_dates(raw_dir, "futures_inventory/dce")

    ensure_dce_session(cdp)

    for idx, t_date in enumerate(target_dates, 1):
        d_str = t_date.isoformat()
        logger.info("[%d/%d] 正在处理交易日: %s", idx, len(target_dates), d_str)

        # 1. 行情采集
        if mode in ("all", "quotes"):
            if t_date in cached_quotes and not force:
                logger.info("  -> 行情命中本地快照 [CACHE HIT]，跳过请求")
            else:
                quotes_text = fetch_dce_quotes_via_cdp(cdp, t_date)
                if quotes_text:
                    if not dry_run:
                        saved = save_raw_quotes(raw_dir, t_date, quotes_text)
                        logger.info("  -> 行情已保存: %s (%d 字节)", saved.name, len(quotes_text))
                        cached_quotes.add(t_date)
                    else:
                        logger.info("  -> [DRY-RUN] 行情命中 (%d 字节)", len(quotes_text))
                    quotes_count += 1
                else:
                    logger.debug("  -> 行情无数据或非交易日")

        # 2. 仓单采集
        if mode in ("all", "inventory"):
            if t_date in cached_inv and not force:
                logger.info("  -> 仓单命中本地快照 [CACHE HIT]，跳过请求")
            else:
                inv_text = fetch_dce_inventory_via_cdp(cdp, t_date)
                if inv_text:
                    if not dry_run:
                        saved = save_raw_inventory(raw_dir, t_date, inv_text)
                        logger.info("  -> 仓单已保存: %s (%d 字节)", saved.name, len(inv_text))
                        cached_inv.add(t_date)
                    else:
                        logger.info("  -> [DRY-RUN] 仓单命中 (%d 字节)", len(inv_text))
                    inventory_count += 1
                else:
                    logger.debug("  -> 仓单无数据或非交易日")

        time.sleep(0.5)

    return quotes_count, inventory_count


def main() -> int:
    parser = argparse.ArgumentParser(description="大商所 (DCE) Chrome CDP 自动化采集器")
    parser.add_argument("--date", type=date.fromisoformat, help="采集指定日期 YYYY-MM-DD")
    parser.add_argument("--start-date", type=date.fromisoformat, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", type=date.fromisoformat, help="结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--mode",
        choices=["all", "quotes", "inventory"],
        default="all",
        help="采集模式: all(全部), quotes(仅日行情), inventory(仅仓单)",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_CDP_PORT, help="Chrome CDP 端口")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="RAW 根目录（默认 data/raw/industry）",
    )
    parser.add_argument("--dry-run", action="store_true", help="探测模式，不写盘")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="采集完成后自动执行 FuturesPrice / Inventory 2-Tier 物化与 Parquet 更新",
    )
    parser.add_argument(
        "--fill-gaps",
        action="store_true",
        help="自愈模式: 自动扫描历史工作日缺口并补全漏采数据",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制模式: 忽略本地已存在的快照缓存，强制重新请求外网",
    )
    args = parser.parse_args()

    target_dates, plan_meta = resolve_smart_harvest_plan(
        raw_dir=args.raw_dir,
        mode=args.mode,
        explicit_date=args.date,
        explicit_start=args.start_date,
        explicit_end=args.end_date,
        fill_gaps=args.fill_gaps,
        force=args.force,
    )

    logger.info(
        "智能增量规划: 候选=%d, 待采集=%d, 本地已缓存跳过=%d, 未到发布时效跳过=%d",
        plan_meta.get("candidate_dates_count", 0),
        len(target_dates),
        plan_meta.get("skipped_cached_count", 0),
        plan_meta.get("skipped_timing_count", 0),
    )
    logger.info(
        "本地最高水位: 行情=%s (%d 份), 仓单=%s (%d 份)",
        plan_meta.get("max_quotes_date") or "无",
        plan_meta.get("cached_quotes_count", 0),
        plan_meta.get("max_inv_date") or "无",
        plan_meta.get("cached_inv_count", 0),
    )

    if not target_dates:
        logger.info("本地数据已是最新水位，无须重复请求外网。")
        return 0

    try:
        ws_url = find_chrome_ws_url(port=args.port)
        logger.info("成功连接 Chrome CDP 调试目标: %s", ws_url)
    except Exception as exc:
        logger.error(str(exc))
        return 1

    cdp = CdpClient(ws_url)
    try:
        q_cnt, inv_cnt = run_cdp_harvest(
            cdp=cdp,
            target_dates=target_dates,
            mode=args.mode,
            raw_dir=args.raw_dir,
            dry_run=args.dry_run,
            force=args.force,
        )
    finally:
        cdp.close()

    print("\n" + "=" * 60)
    print(" 大商所 CDP 采集结果汇总")
    print("=" * 60)
    print(f"计划采集交易日数: {len(target_dates)}")
    print(f"有效日行情产出:   {q_cnt} 份")
    print(f"有效仓单日报产出: {inv_cnt} 份")
    print("=" * 60)

    if len(target_dates) > 0 and q_cnt == 0 and inv_cnt == 0:
        logger.warning(
            "【数据产出为 0 风险排查提示】\n"
            "1. 请确认 Chrome 是否误启用了 --headless 模式；大商所瑞数安全会拦截无头浏览器导致 API 返回空。\n"
            "2. 若浏览器为有头模式，请切换至 Chrome 窗口手动刷新一次大商所报表页面完成初始人机验证。\n"
            "3. 请确认目标日期是否为交易日，且是否已过收盘发布时间（行情 15:30 以后，仓单 16:30 以后）。"
        )

    if args.sync and not args.dry_run and (q_cnt > 0 or inv_cnt > 0):
        logger.info("正在执行 2-Tier 本地物化与 Parquet 更新...")
        sync_start = min(target_dates)
        sync_end = max(target_dates)
        if q_cnt > 0:
            p_coll = FuturesPriceCollector(raw_dir=args.raw_dir)
            p_summary, _ = p_coll.backfill_raw(start_date=sync_start, end_date=sync_end)
            logger.info("期货行情 RAW CSV 物化汇总: %s", p_summary)
        if inv_cnt > 0:
            i_coll = FuturesInventoryCollector(raw_dir=args.raw_dir)
            i_summary, _ = i_coll.backfill_raw(
                start_date=sync_start, end_date=sync_end, download=False
            )
            logger.info("期货仓单 RAW CSV 物化汇总: %s", i_summary)

        if q_cnt > 0 or inv_cnt > 0:
            try:
                from stock_data.fetcher.industry.common import save_curated_fact

                curated_dir = args.raw_dir.parent.parent / "curated" / "industry"
                curated_dir.mkdir(parents=True, exist_ok=True)
                if q_cnt > 0:
                    p_coll = FuturesPriceCollector(raw_dir=args.raw_dir)
                    daily_df = p_coll.build_curated_frame()
                    save_curated_fact(
                        daily_df,
                        curated_dir / "futures_daily.parquet",
                        primary_keys=["symbol", "contract", "trade_date"],
                    )
                if inv_cnt > 0:
                    i_coll = FuturesInventoryCollector(raw_dir=args.raw_dir)
                    inv_df = i_coll.load_from_raw()
                    save_curated_fact(
                        inv_df,
                        curated_dir / "futures_inventory.parquet",
                        primary_keys=["symbol", "trade_date"],
                    )
                logger.info("Curated Parquet 表物化完成")
            except Exception as exc:
                logger.warning("触发 Curated 物化异常: %s", exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
