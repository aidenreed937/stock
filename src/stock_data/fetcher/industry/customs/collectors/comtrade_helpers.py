"""UN Comtrade 采集器的参数校验与 RAW 文件辅助函数。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

_IMPORT_REQUIRED_PRODUCT_KEYS = frozenset({"polysilicon"})
_MAX_CMD_CODE_LENGTH = 600


def normalize_flow_code(flow_code: str) -> str:
    """校验并规范 Comtrade 的进口/出口方向参数。"""
    codes = {part.strip().upper() for part in flow_code.split(",") if part.strip()}
    if not codes or not codes <= {"M", "X"}:
        raise ValueError(f"不支持的 Comtrade flow_code: {flow_code!r}")
    return ",".join(code for code in ("M", "X") if code in codes)


def snapshot_exists(raw_dir: Path, year: int, flow_code: str) -> bool:
    """检查指定年度/方向的 RAW 快照，兼容历史无方向后缀命名。"""
    normalized = normalize_flow_code(flow_code)
    stems = [f"{year}_full"] if normalized == "X" else [f"{year}_full_M", f"{year}_full_M_X"]
    if normalized == "X":
        stems.extend([f"{year}_full_X", str(year)])
    return any(
        (raw_dir / f"{stem}{suffix}").exists() for stem in stems for suffix in (".json.gz", ".json")
    )


def chunk_hs_codes(hs_codes: list[str], max_length: int = _MAX_CMD_CODE_LENGTH) -> list[list[str]]:
    """按 cmdCode 查询参数长度拆分税号。"""
    chunks: list[list[str]] = []
    current: list[str] = []
    current_length = 0
    for code in hs_codes:
        code_length = len(code) + (1 if current else 0)
        if current and current_length + code_length > max_length:
            chunks.append(current)
            current = []
            current_length = 0
        current.append(code)
        current_length += code_length if current_length else len(code)
    if current:
        chunks.append(current)
    return chunks


def infer_csv_trade_direction(file_path: Path) -> str:
    """从手工下载文件名读取方向。"""
    name = file_path.name.lower()
    if any(marker in name for marker in ("_import", "-import", "_inbound", "进口")):
        return "import"
    if any(marker in name for marker in ("_export", "-export", "_outbound", "出口")):
        return "export"
    if name.startswith("gacc_"):
        return "export"
    return "export"


def calculate_periods(
    lookback_months: int = 12,
    start_month: str | None = None,
    end_month: str | None = None,
) -> list[str]:
    """计算 UN Comtrade 查询月份列表。"""
    periods: list[str] = []
    if start_month:
        s_clean = start_month.replace("-", "").strip()
        e_clean = (end_month or date.today().strftime("%Y%m")).replace("-", "").strip()
        sy, sm = int(s_clean[:4]), int(s_clean[4:6])
        ey, em = int(e_clean[:4]), int(e_clean[4:6])
        cur_y, cur_m = sy, sm
        while (cur_y, cur_m) <= (ey, em):
            periods.append(f"{cur_y}{cur_m:02d}")
            cur_m += 1
            if cur_m > 12:
                cur_m = 1
                cur_y += 1
    else:
        today = date.today()
        for i in range(lookback_months):
            year = today.year
            month = today.month - i
            while month <= 0:
                year -= 1
                month += 12
            periods.append(f"{year}{month:02d}")
    return periods


__all__ = [
    "_IMPORT_REQUIRED_PRODUCT_KEYS",
    "_MAX_CMD_CODE_LENGTH",
    "calculate_periods",
    "chunk_hs_codes",
    "infer_csv_trade_direction",
    "normalize_flow_code",
    "snapshot_exists",
]
