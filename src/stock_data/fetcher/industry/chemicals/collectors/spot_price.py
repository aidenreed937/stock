"""生意社 100ppi 现货出厂基准价采集器。

负责 agent-browser 浏览器采集、RAW JSON 快照落盘与 Curated 物化编排；
页面/JS 解析与 Packer 解包见 ``parsers.spot_price``，RAW/Curated 转换见
``transforms.spot_price``。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import requests

from stock_data.fetcher.industry.chemicals.models import ChemicalSpotPriceRecord
from stock_data.fetcher.industry.chemicals.parsers.spot_price import (
    COMMODITY_CATALOG,
    COMMODITY_CATALOG_ALIASES,
    parse_100ppi_chart_text,
    previous_weekday,
    unpack_100ppi_packer,
    validate_spot_extraction,
)
from stock_data.fetcher.industry.chemicals.paths import ChemicalsRawPaths
from stock_data.fetcher.industry.chemicals.transforms.spot_price import (
    materialize_spot_price_curated,
)

logger = logging.getLogger(__name__)

STATUS_ONLINE = "online"
STATUS_FALLBACK = "snapshot_fallback"
STATUS_REJECTED = "rejected"
STATUS_EMPTY = "empty"


def _build_chart_js(url: str) -> str:
    """构造在 agent-browser 页面内执行的 100ppi 图表提取脚本。"""
    return f"""(() => {{
        return fetch('{url}')
            .then(r => r.text())
            .then(text => {{
                const idx1 = text.indexOf('eval(');
                if (idx1 === -1) return {{ error: 'no eval', status: 200 }};
                // 从 eval( 起点做括号配平，不再假设最后一个右括号属于 eval
                let depth = 0;
                let end = -1;
                for (let i = idx1 + 4; i < text.length; i++) {{
                    const ch = text[i];
                    if (ch === '(') depth++;
                    else if (ch === ')') {{ depth--; if (depth === 0) {{ end = i; break; }} }}
                }}
                if (end === -1) return {{ error: 'unbalanced parens', status: 200 }};
                const inner = text.slice(idx1 + 5, end);
                let unpacked;
                try {{
                    unpacked = eval('(' + inner + ')');
                }} catch (e) {{
                    return {{ error: 'unpack eval failed: ' + e.message, status: 200 }};
                }}
                // 收集所有 xAxis/series 的 data 数组，取数据点最多的一段
                const collect = (pattern) => {{
                    const out = [];
                    const re = new RegExp(pattern.source, pattern.flags + 'g');
                    let m;
                    while ((m = re.exec(unpacked)) !== null) out.push(m[1]);
                    return out;
                }};
                const pickLongest = (list) => {{
                    if (!list.length) return null;
                    return list.reduce((a, b) => (b.length > a.length ? b : a));
                }};
                const parseArray = (raw) => {{
                    if (!raw) return [];
                    try {{ return eval(raw); }} catch (e) {{ return []; }}
                }};
                const xRaw = pickLongest(collect(/xAxis:[\\s\\S]*?data:\\s*(\\[[^\\]]+\\])/));
                const yRaw = pickLongest(collect(/series:[\\s\\S]*?data:\\s*(\\[[^\\]]+\\])/));
                return {{
                    dates: parseArray(xRaw),
                    prices: parseArray(yRaw)
                }};
            }})
            .catch(e => ({{ error: e.message }}));
    }})()"""


def save_spot_price_snapshot(
    ppi_dir: Path,
    symbol: str,
    dates: list[str],
    prices: list[float],
    meta: dict[str, Any],
) -> tuple[Path, str]:
    """将提取的完整序列保存为结构化 RAW JSON 快照并计算 SHA-256（原子写）。"""
    now_iso = datetime.now(UTC).isoformat()
    payload = {
        "symbol": symbol,
        "product_name": meta.get("product_name", symbol),
        "ppid": meta.get("ppid", 0),
        "spec": meta.get("spec", ""),
        "region": meta.get("region", "国内"),
        "unit": meta.get("unit", "元/吨"),
        "source": "100ppi",
        "source_url": f"https://www.100ppi.com/graph/cindex.php?f=graph_ave&ppid={meta.get('ppid', 0)}&type=1&mode=3",
        "collected_at": now_iso,
        "count": len(dates),
        "start_date": dates[0] if dates else None,
        "end_date": dates[-1] if dates else None,
        "dates": dates,
        "prices": prices,
    }
    content_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    sha256 = hashlib.sha256(content_bytes).hexdigest()
    snapshot_path = ppi_dir / f"{symbol}.json"
    tmp_path = snapshot_path.with_name(f".{symbol}.json.tmp")
    try:
        tmp_path.write_bytes(content_bytes)
        tmp_path.replace(snapshot_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return snapshot_path, sha256


def load_spot_price_snapshot(ppi_dir: Path, symbol: str) -> list[ChemicalSpotPriceRecord]:
    """从本地已有 RAW 快照回放数据。"""
    snapshot_path = ppi_dir / f"{symbol}.json"
    if not snapshot_path.exists():
        canonical = COMMODITY_CATALOG_ALIASES.get(symbol)
        if canonical:
            snapshot_path = ppi_dir / f"{canonical}.json"
        if not snapshot_path.exists():
            return []
    try:
        content_bytes = snapshot_path.read_bytes()
        sha256 = hashlib.sha256(content_bytes).hexdigest()
        data = json.loads(content_bytes.decode("utf-8"))
        dates = data.get("dates", [])
        prices = data.get("prices", [])
        meta = {
            "product_name": data.get("product_name", symbol),
            "spec": data.get("spec", ""),
            "region": data.get("region", "国内"),
            "unit": data.get("unit", "元/吨"),
            "ppid": data.get("ppid", 0),
        }
        records: list[ChemicalSpotPriceRecord] = []
        collected_at = data.get("collected_at", datetime.now(UTC).isoformat())
        source_url = data.get("source_url", "")
        for d_str, p_val in zip(dates, prices, strict=False):
            if not d_str or p_val is None or p_val == "-":
                continue
            try:
                t_date = date.fromisoformat(str(d_str).strip())
                price = float(p_val)
            except (ValueError, TypeError):
                continue
            records.append(
                ChemicalSpotPriceRecord(
                    product_name=meta["product_name"],
                    symbol=symbol,
                    trade_date=t_date,
                    spot_price_cny=price,
                    spec=meta["spec"],
                    region=meta["region"],
                    unit=meta["unit"],
                    source="100ppi",
                    source_url=source_url,
                    release_date=previous_weekday(t_date),
                    data_status="spot_benchmark",
                    collected_at=collected_at,
                    raw_content_sha256=sha256,
                    raw_snapshot_path=str(snapshot_path),
                )
            )
        return records
    except Exception as e:
        logger.debug("读取 RAW 快照失败 [%s]: %s", symbol, e)
        return []


def load_all_spot_price_snapshots(
    ppi_dir: Path,
    symbols: list[str] | None = None,
) -> list[ChemicalSpotPriceRecord]:
    """从本地 RAW JSON 快照回放全部品种（供离线重放计划使用）。"""
    targets = symbols or list(COMMODITY_CATALOG.keys())
    records: list[ChemicalSpotPriceRecord] = []
    for sym in targets:
        records.extend(load_spot_price_snapshot(ppi_dir, sym))
    return records


class ChemicalSpotPriceCollector:
    """100ppi 现货出厂基准价采集与落盘管理器。"""

    def __init__(
        self,
        raw_dir: Path | str,
        curated_dir: Path | str | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.curated_dir = Path(curated_dir) if curated_dir else self.raw_dir.parent / "curated"
        self.paths = ChemicalsRawPaths(self.raw_dir)
        self.ppi_dir = self.paths.ppi_dir
        self.ppi_dir.mkdir(parents=True, exist_ok=True)
        self.curated_dir.mkdir(parents=True, exist_ok=True)
        self.collection_status: dict[str, str] = {}

    def ensure_browser_session(self) -> bool:
        """确保 agent-browser 处于 100ppi.com 域，具备 WAF 挑战凭据与同源 Fetch 权限。"""
        browser_bin = shutil.which("agent-browser") or "agent-browser"
        try:
            check_proc = subprocess.run(  # noqa: S603
                [browser_bin, "eval", "location.origin"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            origin = check_proc.stdout.strip().replace('"', "")
            if "100ppi.com" in origin:
                return True
            open_proc = subprocess.run(  # noqa: S603
                [browser_bin, "open", "https://www.100ppi.com/"],
                capture_output=True,
                text=True,
                check=False,
                timeout=25,
            )
            return open_proc.returncode == 0
        except Exception as e:
            logger.debug("初始化 agent-browser 会话异常: %s", e)
            return False

    def fetch_via_browser(self, ppid: int) -> dict[str, Any] | None:
        """通过 agent-browser 执行浏览器沙箱提取 100ppi 图表数据；无浏览器会话时回退 HTTP 直连。"""
        if not self.ensure_browser_session():
            logger.debug("未能建立 100ppi.com 浏览器会话，回退 HTTP 直连")
            return self.fetch_via_http(ppid)

        url = f"https://www.100ppi.com/graph/cindex.php?f=graph_ave&ppid={ppid}&type=1&mode=3"
        browser_bin = shutil.which("agent-browser") or "agent-browser"
        try:
            cmd = [browser_bin, "eval", _build_chart_js(url)]
            proc = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if proc.returncode != 0:
                logger.debug("agent-browser 执行失败 [%s]: %s", ppid, proc.stderr)
                return None
            output = proc.stdout.strip()
            data = json.loads(output)
            if isinstance(data, dict) and "dates" in data and "prices" in data:
                return data
            return None
        except Exception as e:
            logger.debug("agent-browser 调度异常 [%s]: %s", ppid, e)
            return None

    def fetch_via_http(self, ppid: int) -> dict[str, Any] | None:
        """通过 requests 直接获取 100ppi 图表数据（自适应 HW_CHECK 质询）。"""
        url = f"https://www.100ppi.com/graph/cindex.php?f=graph_ave&ppid={ppid}&type=1&mode=3"
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )
        try:
            r = session.get(url, timeout=12)
            if "HW_CHECK" in r.text:
                m = re.search(r'var\s+_0x2\s*=\s*"([^"]+)"', r.text)
                if m:
                    session.cookies.set("HW_CHECK", m.group(1), domain=".100ppi.com")
                    r = session.get(url, timeout=12)
            if r.status_code != 200 or not r.text:
                return None
            unpacked = unpack_100ppi_packer(r.text)
            m_x = re.search(r"xAxis:[\s\S]*?data:\s*(\[[^\]]+\])", unpacked)
            m_y = re.search(r"series:[\s\S]*?data:\s*(\[[^\]]+\])", unpacked)
            if not m_x or not m_y:
                return None
            dates = json.loads(re.sub(r",\s*\]", "]", m_x.group(1).replace("'", '"')))
            prices = json.loads(re.sub(r",\s*\]", "]", m_y.group(1).replace("'", '"')))
            return {"dates": dates, "prices": prices}
        except Exception as exc:
            logger.debug("HTTP 抓取异常 [%s]: %s", ppid, exc)
            return None

    def save_raw_snapshot(
        self,
        symbol: str,
        dates: list[str],
        prices: list[float],
        meta: dict[str, Any],
    ) -> tuple[Path, str]:
        """将提取的完整序列保存为结构化 RAW JSON 快照（原子写）。"""
        return save_spot_price_snapshot(self.ppi_dir, symbol, dates, prices, meta)

    def load_from_raw_snapshot(self, symbol: str) -> list[ChemicalSpotPriceRecord]:
        """从本地已有 RAW 快照回放数据。"""
        return load_spot_price_snapshot(self.ppi_dir, symbol)

    def collect_symbol(
        self,
        symbol: str,
        use_network: bool = True,
    ) -> list[ChemicalSpotPriceRecord]:
        """采集单个品种现货基准价，若网络不可用或被禁用则回退到本地快照。"""
        records, _status = self._collect_symbol_with_status(symbol, use_network=use_network)
        return records

    def _collect_symbol_with_status(
        self,
        symbol: str,
        use_network: bool = True,
    ) -> tuple[list[ChemicalSpotPriceRecord], str]:
        """采集单个品种并返回 (records, status)，区分在线/回退/拒绝/空。"""
        canonical = COMMODITY_CATALOG_ALIASES.get(symbol, symbol)
        meta = COMMODITY_CATALOG.get(symbol) or COMMODITY_CATALOG.get(canonical)
        if not meta:
            self.collection_status[symbol] = STATUS_EMPTY
            return [], STATUS_EMPTY

        if not use_network:
            records = self.load_from_raw_snapshot(symbol)
            self.collection_status[symbol] = STATUS_FALLBACK
            return records, STATUS_FALLBACK

        res = self.fetch_via_browser(meta["ppid"])

        status = STATUS_FALLBACK
        if res is None:
            logger.warning("100ppi 在线抓取失败，回退本地快照 [%s]", symbol)
        elif "error" in res:
            logger.warning(
                "100ppi 在线抓取返回错误，回退本地快照 [%s]: %s",
                symbol,
                res.get("error"),
            )
        else:
            dates = res.get("dates") or []
            prices = res.get("prices") or []
            invalid_reason = validate_spot_extraction(dates, prices)
            if invalid_reason is not None:
                logger.warning(
                    "100ppi 在线抓取校验失败，拒绝覆盖旧快照 [%s]: %s",
                    symbol,
                    invalid_reason,
                )
                status = STATUS_REJECTED
            else:
                try:
                    self.save_raw_snapshot(symbol, dates, prices, meta)
                except Exception as e:
                    logger.warning("100ppi 快照落盘失败，保留旧快照 [%s]: %s", symbol, e)
                    status = STATUS_REJECTED
                else:
                    records = self.load_from_raw_snapshot(symbol)
                    self.collection_status[symbol] = STATUS_ONLINE
                    return records, STATUS_ONLINE

        records = self.load_from_raw_snapshot(symbol)
        self.collection_status[symbol] = status
        return records, status

    def collect_all(
        self,
        symbols: list[str] | None = None,
        use_network: bool = True,
    ) -> dict[str, list[ChemicalSpotPriceRecord]]:
        """批量采集品种现货价格，并填充 self.collection_status。"""
        targets = symbols or list(COMMODITY_CATALOG.keys())
        result: dict[str, list[ChemicalSpotPriceRecord]] = {}
        self.collection_status = {}
        for sym in targets:
            recs, status = self._collect_symbol_with_status(sym, use_network=use_network)
            result[sym] = recs
            self.collection_status[sym] = status
        return result

    def collect_result(
        self,
        symbols: list[str] | None = None,
        use_network: bool = True,
    ) -> list[ChemicalSpotPriceRecord]:
        """扁平化采集全部品种记录（供 registry record_endpoint 使用）。"""
        records_dict = self.collect_all(symbols=symbols, use_network=use_network)
        result: list[ChemicalSpotPriceRecord] = []
        for recs in records_dict.values():
            result.extend(recs)
        return result

    def materialize_curated(
        self,
        records_dict: dict[str, list[ChemicalSpotPriceRecord]],
    ) -> Any:
        """将采集记录转换并合并入 Curated chemical_spot_price.parquet。"""
        return materialize_spot_price_curated(records_dict, self.curated_dir)


__all__ = [
    "COMMODITY_CATALOG",
    "COMMODITY_CATALOG_ALIASES",
    "STATUS_EMPTY",
    "STATUS_FALLBACK",
    "STATUS_ONLINE",
    "STATUS_REJECTED",
    "ChemicalSpotPriceCollector",
    "load_all_spot_price_snapshots",
    "parse_100ppi_chart_text",
]
