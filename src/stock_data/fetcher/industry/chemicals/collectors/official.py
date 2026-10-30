"""郑商所/大商所官方静态文件采集原语与 RAW 回填驱动。

将 ``scripts/backfill_czce_*`` / ``scripts/backfill_chemical_futures_daily``
中直连交易所官方接口（DFSStaticFiles 仓单日报、FutureDataDaily.txt、大商所
逐日行情导出）的下载与解析逻辑收编进 fetcher 层，供
``FuturesInventoryCollector`` / ``FuturesPriceCollector`` 在线补拉与回填脚本复用。

本模块只负责把官方快照物化为本地 RAW（缓存目录 + 按品种 CSV），
Curated 统一由 pipeline runner（``execute_single_industry_task``）物化。
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

CZCE_INVENTORY_URL = (
    "https://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{yyyymmdd}/FutureDataWhsheet.{ext}"
)
CZCE_DAILY_URL = (
    "http://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{yyyymmdd}/FutureDataDaily.txt"
)

CZCE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

DCE_DAILY_PAGE_URL = "http://www.dce.com.cn/publicweb/quotesdata/dayQuotesCh.html"
DCE_DAILY_EXPORT_URL = "http://www.dce.com.cn/publicweb/quotesdata/exportDayQuotesChData.html"
DCE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "http://www.dce.com.cn",
    "Referer": DCE_DAILY_PAGE_URL,
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# 各 DCE 化工品种上市日（官方源回填起点）
DCE_LISTING_DATES = {
    "L": date(2007, 7, 31),
    "V": date(2009, 5, 25),
    "PP": date(2014, 2, 28),
    "EB": date(2019, 9, 26),
    "EG": date(2018, 12, 10),
}

DAILY_FIELD_NAMES = [
    "symbol",
    "contract",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
    "open_interest",
    "unit",
    "exchange",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
    "raw_content_sha256",
    "raw_snapshot_path",
]

DCE_HEADER_ALIASES = {
    "合约代码": "contract",
    "合约": "contract",
    "今开盘": "open",
    "开盘价": "open",
    "今最高": "high",
    "最高价": "high",
    "今最低": "low",
    "最低价": "low",
    "今收盘": "close",
    "收盘价": "close",
    "今结算": "settle",
    "结算价": "settle",
    "成交量": "volume",
    "持仓量": "open_interest",
}


# ---------------------------------------------------------------- 通用工具


def _clean_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").replace("，", "").strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fmt_value(value: float | None, integer: bool = False) -> str:
    if value is None:
        return ""
    return f"{value:.0f}" if integer else f"{value:.2f}"


def _weekday_days(start: date, end: date) -> Any:
    """官方文件按自然日缓存，非交易日返回 None；这里只负责迭代工作日。"""
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


def snapshot_ref(local_path: Path, raw_dir: Path | str) -> str:
    """返回快照相对 RAW 根目录的血统引用路径。"""
    try:
        return str(Path(local_path).relative_to(Path(raw_dir)))
    except ValueError:
        return str(Path(local_path))


# ---------------------------------------------------------------- CZCE 仓单日报


def download_czce_inventory_file(
    trade_date: date,
    cache_dir: Path | str | None = None,
) -> tuple[date, Path | None, str | None, bytes | None]:
    """下载或读取缓存的郑商所仓单日报 (FutureDataWhsheet.xls|xlsx)。

    早期归档为 .xls，近期为 .xlsx；本地缓存存在且大于 1KB 时直接使用。
    404（非交易日或无报表日）直接熔断跳过，网络抖动做 3 次指数退避重试。
    """
    cache_root = Path(cache_dir) if cache_dir is not None else None
    d_str = trade_date.strftime("%Y%m%d")
    if cache_root is not None:
        for ext in ("xls", "xlsx"):
            cached_path = cache_root / str(trade_date.year) / f"{d_str}.{ext}"
            if cached_path.exists() and cached_path.stat().st_size > 1024:
                return trade_date, cached_path, ext, cached_path.read_bytes()

    for ext in ("xls", "xlsx"):
        url = CZCE_INVENTORY_URL.format(
            year=trade_date.year,
            yyyymmdd=d_str,
            ext=ext,
        )
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=CZCE_HEADERS, timeout=12)
                if resp.status_code == 200 and len(resp.content) > 1024:
                    if cache_root is not None:
                        local_path = cache_root / str(trade_date.year) / f"{d_str}.{ext}"
                        local_path.parent.mkdir(parents=True, exist_ok=True)
                        local_path.write_bytes(resp.content)
                    else:
                        local_path = None
                    return trade_date, local_path, ext, resp.content
                if resp.status_code == 404:
                    break
            except Exception as exc:
                if attempt == 2:
                    logger.debug("郑商所仓单日报下载失败 [%s %s]: %s", d_str, ext, exc)
                time.sleep(0.3 * (2**attempt))
    logger.warning("未能下载 %s 的郑商所仓单报表", d_str)
    return trade_date, None, None, None


def parse_czce_inventory_frame(
    content: bytes,
    ext: str,
    commodities: dict[str, dict[str, str]],
) -> dict[str, tuple[float | None, float | None]]:
    """解析单个郑商所仓单 Excel 中全部目标品种的仓单数量与当日增减。

    返回 ``{symbol: (仓单数量, 当日增减)}``；实测无数据段返回 (0.0, 0.0)，
    找到品种段但无总计行返回 (None, None)。
    """
    engine = "openpyxl" if ext == "xlsx" else "xlrd"
    try:
        try:
            df = pd.read_excel(io.BytesIO(content), header=None, engine=engine)
        except Exception:
            df = pd.read_excel(io.BytesIO(content), header=None)
    except Exception as exc:
        logger.warning("郑商所仓单 Excel 读取异常 (ext=%s): %s", ext, exc)
        return dict.fromkeys(commodities, (None, None))

    rows_text = [
        " ".join(str(cell) for cell in row if pd.notna(cell)) for row in df.itertuples(index=False)
    ]
    results: dict[str, tuple[float | None, float | None]] = {}

    for sym, meta in commodities.items():
        name = meta["name"]
        matched = [i for i, text in enumerate(rows_text) if name in text or sym in text]
        if not matched:
            results[sym] = (0.0, 0.0)
            continue

        start_idx = matched[0]
        tot_idx = None
        for idx in range(start_idx, min(start_idx + 150, len(rows_text))):
            text = rows_text[idx]
            if idx > start_idx and ("品种：" in text or "品种:" in text):
                break
            if "总计" in text:
                tot_idx = idx
                break

        if tot_idx is None:
            results[sym] = (None, None)
            continue

        inv_cols: list[int] = []
        chg_col: int | None = None
        for idx in range(start_idx, tot_idx):
            for column in df.columns:
                val_str = str(df.loc[idx, column])
                if "仓单数量" in val_str:
                    if column not in inv_cols:
                        inv_cols.append(column)
                elif ("当日增减" in val_str or "增减" in val_str) and chg_col is None:
                    chg_col = column

        inv_val: float | None = None
        if inv_cols:
            total = 0.0
            for column in inv_cols:
                if pd.notna(df.loc[tot_idx, column]):
                    try:
                        total += float(df.loc[tot_idx, column])
                    except (ValueError, TypeError):
                        pass
            inv_val = total

        chg_val: float | None = None
        if chg_col is not None and pd.notna(df.loc[tot_idx, chg_col]):
            try:
                chg_val = float(df.loc[tot_idx, chg_col])
            except (ValueError, TypeError):
                pass

        results[sym] = (inv_val, chg_val)

    return results


DEFAULT_DCE_INVENTORY_COMMODITIES: dict[str, dict[str, Any]] = {
    "EG": {"name": "乙二醇", "industry_code": "220400", "aliases": ("乙二醇", "EG")},
    "V": {"name": "聚氯乙烯", "industry_code": "220200", "aliases": ("聚氯乙烯", "PVC", "V")},
    "PP": {"name": "聚丙烯", "industry_code": "220500", "aliases": ("聚丙烯", "PP")},
    "L": {
        "name": "塑料",
        "industry_code": "220500",
        "aliases": ("线型低密度聚乙烯", "聚乙烯", "塑料", "LLDPE"),
    },
    "EB": {"name": "苯乙烯", "industry_code": "220400", "aliases": ("苯乙烯", "EB")},
}


def parse_dce_inventory_text(
    text: str,
    commodities: dict[str, dict[str, Any]] | None = None,
) -> dict[str, tuple[float | None, float | None]]:
    """解析大商所官方仓单日报文本或 HTML，按品种提取 (当日仓单量, 当日增减)。"""
    target_meta = commodities or DEFAULT_DCE_INVENTORY_COMMODITIES
    results: dict[str, tuple[float | None, float | None]] = dict.fromkeys(target_meta, (0.0, 0.0))
    if not text or not text.strip():
        return dict.fromkeys(target_meta, (None, None))

    clean_text = text
    if "<table" in text.lower() or "<tr" in text.lower():
        clean_text = re.sub(r"(?i)<tr[^>]*>", "\n", clean_text)
        clean_text = re.sub(r"(?i)</t[dh]>", "\t", clean_text)
        clean_text = re.sub(r"<[^>]+>", "", clean_text)

    lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
    if not lines:
        return dict.fromkeys(target_meta, (None, None))

    current_sym: str | None = None
    for line in lines:
        for sym, meta in target_meta.items():
            aliases = meta.get("aliases") or (meta.get("name", sym), sym)
            if any(alias in line for alias in aliases) and (
                "品种" in line or any(line.startswith(a) for a in aliases)
            ):
                current_sym = sym
                break

        if current_sym is not None and ("总计" in line or "合计" in line or "小计" in line):
            raw_nums = re.findall(r"-?\d+(?:,\d+)*(?:\.\d+)?", line)
            nums: list[float] = []
            for n_str in raw_nums:
                try:
                    nums.append(float(n_str.replace(",", "")))
                except ValueError:
                    pass
            if len(nums) >= 3:
                # 昨日仓单量, 今日仓单量, 增减
                results[current_sym] = (nums[1], nums[2])
            elif len(nums) == 2:
                # 今日仓单量, 增减
                results[current_sym] = (nums[0], nums[1])
            elif len(nums) == 1:
                results[current_sym] = (nums[0], 0.0)
            current_sym = None

    return results


def build_inventory_record(
    symbol: str,
    meta: dict[str, str],
    trade_date: date,
    inv_val: float | None,
    chg_val: float | None,
    ext: str,
    sha: str,
    rel_snap: str,
    now_iso: str,
) -> dict[str, str]:
    """将单日仓单解析结果转换为 RAW CSV 记录（值保真，不做类型收敛）。"""
    return {
        "trade_date": trade_date.isoformat(),
        "symbol": symbol,
        "name": meta["name"],
        "industry_code": meta["industry_code"],
        "inventory": str(inv_val) if inv_val is not None else "",
        "change": str(chg_val) if chg_val is not None else "",
        "unit": meta["unit"],
        "source": "Exchange_Official/CZCE",
        "source_url": CZCE_INVENTORY_URL.format(
            year=trade_date.year,
            yyyymmdd=trade_date.strftime("%Y%m%d"),
            ext=ext,
        ),
        "release_date": trade_date.isoformat(),
        "collected_at": now_iso,
        "raw_content_sha256": sha,
        "raw_snapshot_path": rel_snap,
    }


def czce_trading_dates(
    start_date: date | None,
    end_date: date | None,
) -> set[date] | None:
    """郑商所期货交易日历；本地 exchange_calendars 缺失时回退工作日。"""
    if start_date is None or end_date is None or start_date > end_date:
        return None
    try:
        import exchange_calendars as xcals

        for calendar_name in ("XZCE", "CZCE"):
            try:
                sessions = xcals.get_calendar(calendar_name).sessions_in_range(
                    start_date.isoformat(), end_date.isoformat()
                )
                return {session.date() for session in sessions}
            except Exception:
                continue
    except Exception as exc:
        logger.warning("读取郑商所交易日历失败: %s，回退到工作日", exc)
    dates: set[date] = set()
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5:
            dates.add(cursor)
        cursor += timedelta(days=1)
    return dates


# ---------------------------------------------------------------- CZCE 日度行情


def czce_daily_url(trade_date: date) -> str:
    return CZCE_DAILY_URL.format(
        year=trade_date.year,
        yyyymmdd=trade_date.strftime("%Y%m%d"),
    )


def download_czce_daily_text(trade_date: date, cache_dir: Path | str) -> str | None:
    """下载或读取缓存的郑商所官方日行情文本；非交易日/失败返回 None。"""
    cache_root = Path(cache_dir)
    yyyymmdd = trade_date.strftime("%Y%m%d")
    cache_file = cache_root / trade_date.strftime("%Y") / f"{yyyymmdd}.txt"
    if cache_file.exists() and cache_file.stat().st_size > 0:
        return cache_file.read_text(encoding="utf-8")

    url = czce_daily_url(trade_date)
    try:
        resp = requests.get(url, headers=CZCE_HEADERS, timeout=20)
        if resp.status_code != 200 or len(resp.content) < 1024:
            return None
        text = resp.content.decode("utf-8")
        if "郑州商品交易所期货每日行情表" not in text:
            return None
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")
        return text
    except Exception as exc:
        logger.debug("郑商所日行情下载失败 [%s]: %s", yyyymmdd, exc)
        return None


def parse_czce_daily_text(
    text: str,
    prefixes: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    """解析郑商所官方日行情文本，按品种返回逐合约行。

    返回 ``{symbol: [row, ...]}``，row 含开高低收/结算/量/仓等标准化字段。
    仅保留 prefixes 内品种的合约行，跳过"小计"与标题行。
    """
    result: dict[str, list[dict[str, Any]]] = {}
    for raw_line in text.splitlines():
        cells = [cell.strip() for cell in raw_line.split("|")]
        if not cells or not cells[0]:
            continue
        code = cells[0]
        prefix = re.match(r"^([A-Za-z]{1,3})\d+$", code)
        if prefix is None or prefix.group(1).upper() not in prefixes:
            continue
        symbol = prefix.group(1).upper()
        row = _parse_czce_contract_row(symbol, cells)
        if row is not None:
            result.setdefault(symbol, []).append(row)
    return result


def _parse_czce_contract_row(symbol: str, cells: list[str]) -> dict[str, Any] | None:
    if len(cells) < 11:
        return None
    try:
        settle = _clean_number(cells[6])
        oi = _clean_number(cells[10])
        volume = _clean_number(cells[9])
    except (ValueError, IndexError):
        return None
    if settle is None:
        settle = _clean_number(cells[5])  # 今结算缺失时回退今收盘
    return {
        "symbol": symbol,
        "contract": cells[0],
        "open": _clean_number(cells[2]),
        "high": _clean_number(cells[3]),
        "low": _clean_number(cells[4]),
        "close": _clean_number(cells[5]),
        "settle": settle,
        "volume": volume,
        "open_interest": oi,
    }


def pick_main_contract(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """按当日持仓量最大选主力合约；无持仓数据时按成交量最大回退。"""
    if not rows:
        return None
    traded = [row for row in rows if (row.get("open_interest") or 0) > 0]
    if not traded:
        traded = [row for row in rows if (row.get("volume") or 0) > 0]
    if not traded:
        return None
    return max(traded, key=lambda row: (row.get("open_interest") or 0, row.get("volume") or 0))


# ---------------------------------------------------------------- DCE 日度行情


def _decode_dce_response(content: bytes) -> str:
    """解码大商所导出内容，优先 UTF-8，回退 GBK/GB18030。"""
    for enc in ("utf-8-sig", "gbk", "gb18030"):
        try:
            text = content.decode(enc)
            if "合约" in text or "品种" in text or "开盘" in text:
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def _split_dce_line(line: str) -> list[str]:
    """按制表符切分大商所导出行；无制表符时按 CSV 或空白切分。"""
    line = line.strip().lstrip("\ufeff")
    if not line:
        return []
    if "\t" in line:
        return [cell.strip() for cell in line.split("\t")]
    if "," in line:
        return [cell.strip() for cell in next(csv.reader([line]))]
    return line.split()


def _find_dce_header_row(lines: list[str]) -> tuple[int, dict[str, int]] | None:
    """定位大商所导出的表头行，返回 (行号, 字段名->列号)。"""
    for idx, raw_line in enumerate(lines):
        cells = _split_dce_line(raw_line)
        if not cells:
            continue
        if "合约代码" in cells or (
            "合约" in cells and any("开盘" in c or "收盘" in c for c in cells)
        ):
            col_map: dict[str, int] = {}
            for col, cell in enumerate(cells):
                key = DCE_HEADER_ALIASES.get(cell)
                if key is not None and key not in col_map:
                    col_map[key] = col
            if "contract" in col_map:
                return idx, col_map
    return None


def _parse_dce_contract_row(
    symbol: str,
    cells: list[str],
    col_map: dict[str, int],
    contract: str,
) -> dict[str, Any] | None:
    def cell_value(key: str) -> float | None:
        col = col_map.get(key)
        if col is None or col >= len(cells):
            return None
        return _clean_number(cells[col])

    close = cell_value("close")
    settle = cell_value("settle")
    if settle is None:
        settle = close
    return {
        "symbol": symbol,
        "contract": contract,
        "open": cell_value("open"),
        "high": cell_value("high"),
        "low": cell_value("low"),
        "close": close,
        "settle": settle,
        "volume": cell_value("volume"),
        "open_interest": cell_value("open_interest"),
    }


def parse_dce_daily_text(
    text: str,
    prefixes: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    """解析大商所官方逐日行情导出，按品种返回逐合约行。

    仅保留 prefixes 内品种的合约行，跳过合计/期权等行。
    """
    result: dict[str, list[dict[str, Any]]] = {}
    lines = [line for line in text.splitlines() if line.strip()]
    header = _find_dce_header_row(lines)
    if header is None:
        return result
    header_idx, col_map = header
    for raw_line in lines[header_idx + 1 :]:
        cells = _split_dce_line(raw_line)
        if not cells:
            continue
        contract_col = col_map.get("contract")
        if contract_col is None or contract_col >= len(cells):
            continue
        code = cells[contract_col]
        match = re.match(r"^([A-Za-z]{1,2})\d+$", code)
        if match is None or match.group(1).upper() not in prefixes:
            continue
        symbol = match.group(1).upper()
        row = _parse_dce_contract_row(symbol, cells, col_map, code)
        if row is not None:
            result.setdefault(symbol, []).append(row)
    return result


def _dce_cache_candidates(cache_dir: Path, trade_date: date) -> list[Path]:
    """返回某交易日可用的官方缓存文件（.txt/.csv/.tsv 或任意同名后缀）。"""
    year_dir = cache_dir / trade_date.strftime("%Y")
    yyyymmdd = trade_date.strftime("%Y%m%d")
    candidates: list[Path] = []
    for ext in (".txt", ".csv", ".tsv"):
        candidate = year_dir / (yyyymmdd + ext)
        if candidate.exists() and candidate.stat().st_size > 0:
            candidates.append(candidate)
    if candidates:
        return candidates
    if year_dir.exists():
        return [
            p for p in sorted(year_dir.glob(yyyymmdd + "*")) if p.is_file() and p.stat().st_size > 0
        ]
    return []


def _has_dce_cache_files(cache_dir: Path) -> bool:
    """是否已有任何 DCE 官方缓存文件。"""
    cache_root = Path(cache_dir)
    if not cache_root.exists():
        return False
    return any(p.is_file() and p.stat().st_size > 0 for p in cache_root.rglob("*"))


def download_dce_daily_text(trade_date: date, cache_dir: Path | str) -> str | None:
    """下载或读取缓存的大商所官方日行情导出；非交易日/失败返回 None。"""
    cache_root = Path(cache_dir)
    for cache_file in _dce_cache_candidates(cache_root, trade_date):
        try:
            text = _decode_dce_response(cache_file.read_bytes())
            if parse_dce_daily_text(text, ("L", "V", "PP", "EB", "EG")):
                return text
        except OSError:
            continue

    yyyymmdd = trade_date.strftime("%Y%m%d")
    cache_file = cache_root / trade_date.strftime("%Y") / f"{yyyymmdd}.txt"

    payload = {
        "dayQuotes.product.variety": "all",
        "dayQuotes.product.trade_date": yyyymmdd,
        "dayQuotes.product.trade_type": "0",
    }
    try:
        resp = requests.post(DCE_DAILY_EXPORT_URL, data=payload, headers=DCE_HEADERS, timeout=20)
        if resp.status_code != 200 or len(resp.content) < 1024:
            return None
        text = _decode_dce_response(resp.content)
        if "合约" not in text and "品种" not in text:
            return None
        if not parse_dce_daily_text(text, ("L", "V", "PP", "EB", "EG")):
            logger.debug("大商所日行情 [%s] 无 DCE 化工合约行，跳过缓存", yyyymmdd)
            return None
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")
        return text
    except Exception as exc:
        logger.debug("大商所日行情下载失败 [%s]: %s", yyyymmdd, exc)
        return None


# ---------------------------------------------------------------- 日度 RAW 回填驱动


def build_daily_record(
    symbol: str,
    meta: dict[str, str],
    trade_date: date,
    main: dict[str, Any],
    source_sha256: str,
    now_iso: str,
    *,
    exchange: str = "CZCE",
    source: str = "Exchange_Official/CZCE",
    source_url: str | None = None,
    snapshot_dir: str = "czce_daily_cache",
) -> dict[str, str]:
    """将主力合约行转换为 RAW CSV 记录（contract 保持主力连续代码）。"""
    raw_snapshot = (
        f"industry/chemicals/futures_daily/{snapshot_dir}/"
        f"{trade_date.strftime('%Y')}/{trade_date.strftime('%Y%m%d')}.txt"
    )
    return {
        "symbol": symbol,
        "contract": meta.get("main_contract", f"{symbol}0"),
        "trade_date": trade_date.isoformat(),
        "open": _fmt_value(main.get("open")),
        "high": _fmt_value(main.get("high")),
        "low": _fmt_value(main.get("low")),
        "close": _fmt_value(main.get("close")),
        "settle": _fmt_value(main.get("settle")),
        "volume": _fmt_value(main.get("volume"), integer=True),
        "open_interest": _fmt_value(main.get("open_interest"), integer=True),
        "unit": "元/吨",
        "exchange": exchange,
        "source": source,
        "source_url": source_url or czce_daily_url(trade_date),
        "release_date": trade_date.isoformat(),
        "data_status": "actual",
        "collected_at": now_iso,
        "raw_content_sha256": source_sha256,
        "raw_snapshot_path": raw_snapshot,
    }


def read_daily_csv(path: Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with Path(path).open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_daily_csv(path: Path, rows: list[dict[str, str]]) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DAILY_FIELD_NAMES)
        writer.writeheader()
        writer.writerows(rows)


def merge_daily_rows(
    existing: list[dict[str, str]],
    new_rows: list[dict[str, str]],
    *,
    keep_sources: set[str] | None = None,
) -> list[dict[str, str]]:
    """增量场景：保留既有 CSV 历史行，按 trade_date 去重后以新行为准。

    keep_sources 非空时只保留来源命中的既有行（如切换后仅保留官方源行）。
    """
    by_date: dict[str, dict[str, str]] = {}
    for row in existing:
        if keep_sources is not None and row.get("source") not in keep_sources:
            continue
        by_date[row["trade_date"]] = row
    for row in new_rows:
        by_date[row["trade_date"]] = row
    return sorted(by_date.values(), key=lambda row: row["trade_date"])


def latest_daily_csv_date(path: Path) -> date | None:
    latest: date | None = None
    for row in read_daily_csv(path):
        try:
            latest = date.fromisoformat(row["trade_date"].strip())
        except (KeyError, ValueError):
            continue
    return latest


def symbol_csv_sources(path: Path) -> set[str]:
    return {row.get("source") or "" for row in read_daily_csv(path)}


def _next_backfill_start(
    symbols: list[str],
    fallback: date,
    daily_dir: Path,
) -> date:
    known_dates = [
        d
        for d in (latest_daily_csv_date(daily_dir / f"{symbol}.csv") for symbol in symbols)
        if d is not None
    ]
    latest = max(known_dates) if known_dates else None
    return (latest + timedelta(days=1)) if latest else fallback


def backfill_futures_daily_raw(
    daily_dir: Path | str,
    symbols_meta: dict[str, dict[str, str]],
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    full: bool = False,
) -> tuple[dict[str, int], set[str]]:
    """按官方逐日文件回填化工期货主力连续日行情（仅写 RAW），返回 (summary, fetched)。"""
    daily_root = Path(daily_dir)
    czce_cache = daily_root / "czce_daily_cache"
    dce_cache = daily_root / "dce_daily_cache"
    for directory in (daily_root, czce_cache, dce_cache):
        directory.mkdir(parents=True, exist_ok=True)

    czce_symbols = [
        symbol for symbol, meta in symbols_meta.items() if meta.get("exchange") == "CZCE"
    ]
    dce_symbols = [symbol for symbol, meta in symbols_meta.items() if meta.get("exchange") == "DCE"]

    today = date.today()
    if end_date is None:
        end_date = today

    # DCE 首次切换（CSV 仍为新浪源或缺文件）且未显式指定窗口时，强制全量官方回填
    dce_full = full or (
        start_date is None
        and any(
            "Exchange_Official/DCE" not in symbol_csv_sources(daily_root / f"{symbol}.csv")
            for symbol in dce_symbols
        )
    )

    if start_date is not None:
        czce_start = start_date
        dce_start = start_date
    elif full:
        czce_start = date(2019, 12, 6)  # 纯碱上市日，覆盖 CZCE 化工品种最早数据
        dce_start = min(DCE_LISTING_DATES.values())  # L 上市日 2007-07-31
    elif dce_full:
        czce_start = _next_backfill_start(czce_symbols, date(2019, 12, 6), daily_root)
        dce_start = min(DCE_LISTING_DATES.values())
    else:
        all_symbols = czce_symbols + dce_symbols
        czce_start = _next_backfill_start(all_symbols, date(2019, 12, 6), daily_root)
        dce_start = czce_start

    logger.info(
        "日行情 RAW 回填窗口 (CZCE: %s ~ %s, DCE: %s ~ %s, 模式: %s)",
        czce_start.isoformat(),
        end_date.isoformat(),
        dce_start.isoformat(),
        end_date.isoformat(),
        "全量" if full else ("DCE 切换全量" if dce_full else "增量"),
    )

    summary: dict[str, int] = {}
    fetched: set[str] = set()
    summary.update(
        _backfill_czce_days(
            daily_root,
            czce_cache,
            symbols_meta,
            czce_symbols,
            czce_start,
            end_date,
            incremental=not full,
            fetched=fetched,
        )
    )
    summary.update(
        _backfill_dce_days(
            daily_root,
            dce_cache,
            symbols_meta,
            dce_symbols,
            dce_start,
            end_date,
            incremental=not dce_full,
            fetched=fetched,
        )
    )
    return summary, fetched


def _backfill_czce_days(
    daily_dir: Path,
    cache_dir: Path,
    symbols_meta: dict[str, dict[str, str]],
    symbols: list[str],
    start_date: date,
    end_date: date,
    *,
    incremental: bool,
    fetched: set[str],
) -> dict[str, int]:
    rows_by_symbol: dict[str, list[dict[str, str]]] = {sym: [] for sym in symbols}
    now_iso = datetime.now().astimezone().isoformat()
    for trade_date in _weekday_days(start_date, end_date):
        if trade_date.weekday() >= 5:
            continue
        text = download_czce_daily_text(trade_date, cache_dir)
        if text is None:
            continue
        source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        daily = parse_czce_daily_text(text, tuple(symbols))
        for symbol in symbols:
            main = pick_main_contract(daily.get(symbol, []))
            if main is None:
                continue
            meta = symbols_meta[symbol]
            rows_by_symbol[symbol].append(
                build_daily_record(symbol, meta, trade_date, main, source_sha256, now_iso)
            )
            fetched.add(f"{symbol}:{trade_date.isoformat()}")

    summary: dict[str, int] = {}
    for symbol in symbols:
        new_rows = rows_by_symbol[symbol]
        if incremental:
            new_rows = merge_daily_rows(read_daily_csv(daily_dir / f"{symbol}.csv"), new_rows)
        if not new_rows:
            summary[symbol] = 0
            continue
        write_daily_csv(daily_dir / f"{symbol}.csv", new_rows)
        summary[symbol] = len(new_rows)
    return summary


def _backfill_dce_days(
    daily_dir: Path,
    cache_dir: Path,
    symbols_meta: dict[str, dict[str, str]],
    symbols: list[str],
    start_date: date,
    end_date: date,
    *,
    incremental: bool,
    fetched: set[str],
) -> dict[str, int]:
    rows_by_symbol: dict[str, list[dict[str, str]]] = {sym: [] for sym in symbols}
    now_iso = datetime.now().astimezone().isoformat()
    if not incremental and not _has_dce_cache_files(cache_dir):
        # 全量且无任何官方缓存时先探测：近 10 个自然日任一工作日可取到数据才继续，
        # 否则判定为官网反爬/不可达（412/400），跳过 DCE 回填以保护现有 CSV。
        reachable = False
        probe_end = min(end_date, date.today())
        for delta in range(10):
            probe_date = probe_end - timedelta(days=delta)
            if probe_date.weekday() >= 5:
                continue
            if download_dce_daily_text(probe_date, cache_dir) is not None:
                reachable = True
                break
        if not reachable:
            logger.warning(
                "DCE 官方源不可达（大商所官网反爬 412/400 或 dce_daily_cache 为空），"
                "本次跳过 DCE 回填，现有 CSV 保持不变；请先放置官方日行情文件到 %s 后重跑。",
                cache_dir,
            )
            return dict.fromkeys(symbols, 0)
    for trade_date in _weekday_days(start_date, end_date):
        if trade_date.weekday() >= 5:
            continue
        text = download_dce_daily_text(trade_date, cache_dir)
        if text is None:
            continue
        source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        daily = parse_dce_daily_text(text, tuple(symbols))
        for symbol in symbols:
            listing_date = DCE_LISTING_DATES.get(symbol)
            if listing_date is not None and trade_date < listing_date:
                continue
            main = pick_main_contract(daily.get(symbol, []))
            if main is None:
                continue
            meta = symbols_meta[symbol]
            rows_by_symbol[symbol].append(
                build_daily_record(
                    symbol,
                    meta,
                    trade_date,
                    main,
                    source_sha256,
                    now_iso,
                    exchange="DCE",
                    source="Exchange_Official/DCE",
                    source_url=DCE_DAILY_PAGE_URL,
                    snapshot_dir="dce_daily_cache",
                )
            )
            fetched.add(f"{symbol}:{trade_date.isoformat()}")

    summary: dict[str, int] = {}
    for symbol in symbols:
        new_rows = rows_by_symbol[symbol]
        if incremental:
            # 切换后只保留官方源行，避免历史新浪行混入
            new_rows = merge_daily_rows(
                read_daily_csv(daily_dir / f"{symbol}.csv"),
                new_rows,
                keep_sources={"Exchange_Official/DCE"},
            )
        if not new_rows:
            summary[symbol] = 0
            continue
        write_daily_csv(daily_dir / f"{symbol}.csv", new_rows)
        summary[symbol] = len(new_rows)
    return summary


__all__ = [
    "CZCE_DAILY_URL",
    "CZCE_HEADERS",
    "CZCE_INVENTORY_URL",
    "DAILY_FIELD_NAMES",
    "DCE_DAILY_EXPORT_URL",
    "DCE_DAILY_PAGE_URL",
    "DCE_HEADERS",
    "DCE_LISTING_DATES",
    "DEFAULT_DCE_INVENTORY_COMMODITIES",
    "backfill_futures_daily_raw",
    "build_daily_record",
    "build_inventory_record",
    "czce_daily_url",
    "czce_trading_dates",
    "download_czce_daily_text",
    "download_czce_inventory_file",
    "download_dce_daily_text",
    "latest_daily_csv_date",
    "merge_daily_rows",
    "parse_czce_daily_text",
    "parse_czce_inventory_frame",
    "parse_dce_daily_text",
    "parse_dce_inventory_text",
    "pick_main_contract",
    "read_daily_csv",
    "snapshot_ref",
    "symbol_csv_sources",
    "write_daily_csv",
]
