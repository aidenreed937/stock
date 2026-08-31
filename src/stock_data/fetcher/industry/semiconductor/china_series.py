"""中国半导体月度销售额推算引擎 (China Absolute Series Reconstructor)。

从 SIA 新闻提取各月 China YoY/MoM 与年度绝对值锚点，构建连续月度绝对值序列并校验。
输出: data/curated/industry/semiconductor_china_series.parquet
"""

from __future__ import annotations

import calendar
import logging
import re
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.semiconductor.collector import (
    parse_sia_china_and_date,
)

logger = logging.getLogger(__name__)

CHINA_SERIES_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "china_sales_usd": pl.Float64,
    "china_yoy_growth": pl.Float64,
    "china_mom_growth": pl.Float64,
    "anchor_flag": pl.Boolean,
    "calc_flag": pl.String,
    "yoy_check_diff": pl.Float64,
    "check_status": pl.String,
    "source_url": pl.String,
}

_YEAR_ABS_PATTERNS = (
    r"China[^.]{0,160}?(?:sales|revenue|market)[^.]{0,80}?\$?([\d.]+)\s*billion",
    r"China[^.]{0,120}?(?:were|totaled|was|reached)[^.]{0,60}?\$?([\d.]+)\s*billion",
)


def _extract_year_anchor(text: str, year: int) -> float | None:
    """从 SIA 新闻文本中提取指定年份的中国半导体年度销售额 (十亿美元)。

    同时校验数值量级 (30~400B 为合理年度区间), 避免误命中 (如 CPU/GPU/FPGA 子行业 $1B)。
    """
    for pat in _YEAR_ABS_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = float(m.group(1))
            if 30.0 <= val <= 400.0:
                return round(val, 1)
    return None


def parse_sia_china_enriched(
    html_text: str,
    source_url: str,
) -> dict[str, object] | None:
    """增强版 SIA China 解析: 月度 YoY/MoM + 年度绝对值锚点。"""
    base = parse_sia_china_and_date(html_text, source_url)
    if base is None:
        return None
    out: dict[str, object] = dict(base)

    # 尝试提取新闻所属年份的年度锚点 (报告月所在年, 及其前后一年)
    rm = str(base["report_month"])
    y = int(rm[:4])
    for cand_year in (y, y - 1, y + 1):
        val = _extract_year_anchor(html_text, cand_year)
        if val is not None:
            out["anchor_year"] = cand_year
            out["china_year_sales_usd"] = val
            break
    else:
        out["anchor_year"] = None
        out["china_year_sales_usd"] = None
    return out


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _iter_months(start: tuple[int, int], end: tuple[int, int]) -> Iterator[tuple[int, int]]:
    """在 (start_year, start_month) ~ (end_year, end_month) 内按月递增。"""
    y, m = start
    ey, em = end
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def _prev_month(y: int, m: int) -> tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)


def _next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def build_china_series(
    records: Sequence[dict[str, object]],
    start_month: str = "2012-01",
    end_month: str | None = None,
) -> pl.DataFrame:
    """从 SIA 解析记录构建连续月度 China 销售额序列。

    Args:
        records: parse_sia_china_enriched 的输出列表 (可含月度增速与年度锚点)。
        start_month: 推算区间起始月 (YYYY-MM, 默认 2012-01)。
        end_month: 推算区间结束月 (YYYY-MM, 默认取记录中最新月份)。

    Returns:
        pl.DataFrame: CHINA_SERIES_SCHEMA 结构的推算序列。
    """
    # ---- 1. 聚合月度 YoY/MoM (同月多条新闻取有 YoY 者) ----
    monthly: dict[str, dict[str, object]] = {}
    for r in records:
        rm = str(r["report_month"])
        if rm not in monthly or (
            r.get("china_yoy_growth") is not None and monthly[rm].get("china_yoy_growth") is None
        ):
            monthly[rm] = dict(r)

    # ---- 2. 聚合年度锚点 (全年取最新/最大可信值) ----
    year_anchors: dict[int, float] = {}
    for r in records:
        ay = r.get("anchor_year")
        av = r.get("china_year_sales_usd")
        if isinstance(ay, int) and isinstance(av, int | float) and av is not None:
            year_anchors[ay] = float(av)

    if not year_anchors:
        logger.warning("未找到任何 China 年度绝对值锚点, 无法建立推算基准")
        return pl.DataFrame(schema=CHINA_SERIES_SCHEMA)

    # ---- 3. 确定推算区间 ----
    sy, sm = int(start_month[:4]), int(start_month[5:7])
    ey, em = (
        (int(end_month[:4]), int(end_month[5:7]))
        if end_month
        else max((int(k[:4]), int(k[5:7])) for k in monthly)
    )
    # 锚点年按时间升序 (多锚点分段校准: 每段以该段最新锚点年为准绳)
    anchor_years = sorted(year_anchors)

    def _month_factors(year: int) -> dict[str, float]:
        """该年各月相对 1 月的累计因子 (1月=1.0), 缺失 MoM 按环比 0% 插值。"""
        factors: dict[str, float] = {_month_key(year, 1): 1.0}
        prev_abs = 1.0
        for mo in range(2, 13):
            mk = _month_key(year, mo)
            rec = monthly.get(mk) or {}
            mom = rec.get("china_mom_growth")
            if isinstance(mom, int | float) and mom is not None:
                prev_abs *= 1.0 + float(mom)
            factors[mk] = prev_abs
        return factors

    def _anchor_year_values(year: int) -> dict[str, float] | None:
        """锚点年内 12 个月绝对值: 严格满足年合计 = year_anchors[year]。"""
        anchor = year_anchors.get(year)
        if anchor is None:
            return None
        factors = _month_factors(year)
        total_factor = sum(factors[_month_key(year, mo)] for mo in range(1, 13))
        if total_factor <= 0:
            return None
        base = anchor / total_factor
        return {_month_key(year, mo): base * factors[_month_key(year, mo)] for mo in range(1, 13)}

    def _chain_from(
        seed: dict[str, float], seed_year: int, direction: str
    ) -> tuple[dict[str, float | None], dict[str, str]]:
        """从种子年份向未来(forward)/过去(backward)推算。

        forward:  逐月 MoM 链 month_k = month_{k-1} * (1+mom_k), 缺 MoM 环比 0% 插值。
        backward: 优先用 YoY 跨年反推 month_{y-1,m} = month_{y,m} / (1+yoy_{y,m})
                  (SIA 官方同比, 比长 MoM 链更可靠); 同一年内缺失月用 MoM 反向补齐。
        """
        vals: dict[str, float | None] = dict(seed)
        flags: dict[str, str] = {
            _month_key(seed_year, 1): "anchor",
            **{_month_key(seed_year, mo): "backward" for mo in range(2, 13)},
        }
        if direction == "forward":
            last_val = seed.get(_month_key(seed_year, 12))
            cur_y, cur_m = _next_month(seed_year, 12)
            while (cur_y, cur_m) <= (ey, em):
                ck = _month_key(cur_y, cur_m)
                rec = monthly.get(ck) or {}
                cmom = rec.get("china_mom_growth")
                if last_val is not None and isinstance(cmom, int | float) and cmom is not None:
                    last_val = last_val * (1.0 + float(cmom))
                    vals[ck] = last_val
                    flags[ck] = "forward"
                elif last_val is not None:
                    vals[ck] = last_val
                    flags[ck] = "gap_flat"
                else:
                    vals[ck] = None
                    flags[ck] = "gap"
                cur_y, cur_m = _next_month(cur_y, cur_m)
        else:
            # 反推: 逐年前推 (用 YoY 跨年反推), 同一年内用 MoM 从 1 月向 12 月补齐形状
            year = seed_year - 1
            while year * 100 + 1 >= sy * 100 + sm:
                # 该年 1 月: 由下一年同月 YoY 反推
                jan_next_key = _month_key(year + 1, 1)
                jan_next_val = vals.get(jan_next_key)
                jan_rec = monthly.get(jan_next_key) or {}
                jan_yoy = jan_rec.get("china_yoy_growth")
                if (
                    jan_next_val is not None
                    and isinstance(jan_yoy, int | float)
                    and jan_yoy is not None
                ):
                    jan_val = jan_next_val / (1.0 + float(jan_yoy))
                else:
                    jan_val = None
                vals[_month_key(year, 1)] = jan_val
                flags[_month_key(year, 1)] = "backward_yoy" if jan_val is not None else "gap"

                # 该年 2-12 月: 从 1 月用 MoM 链补齐
                cur_val = jan_val
                for mo in range(2, 13):
                    ck = _month_key(year, mo)
                    prev_mom = (monthly.get(ck) or {}).get("china_mom_growth")
                    if (
                        cur_val is not None
                        and isinstance(prev_mom, int | float)
                        and prev_mom is not None
                    ):
                        cur_val = cur_val * (1.0 + float(prev_mom))
                        vals[ck] = cur_val
                        flags[ck] = "backward_mom"
                    elif cur_val is not None:
                        vals[ck] = cur_val
                        flags[ck] = "gap_flat"
                    else:
                        vals[ck] = None
                        flags[ck] = "gap"
                year -= 1
        return vals, flags

    # ---- 4. 多锚点分段推算: ----
    #    锚点年内部严格满足年度合计; 各锚点年之间用较新年份向较旧年份反推,
    #    遇到更早锚点年时以其为种子重启 (分段校准, 避免误差跨锚点累积)。
    values: dict[str, float | None] = {}
    calc_flags: dict[str, str] = {}

    # 4a. 未来段: 从最新锚点年向 end 前推
    latest_anchor = anchor_years[-1]
    latest_seed = _anchor_year_values(latest_anchor)
    if latest_seed is None:
        logger.warning("最新锚点年 %d 推算失败", latest_anchor)
        return pl.DataFrame(schema=CHINA_SERIES_SCHEMA)
    fwd_vals, fwd_flags = _chain_from(latest_seed, latest_anchor, "forward")
    values.update(fwd_vals)
    calc_flags.update(fwd_flags)

    # 4b. 过去段: 从最新锚点年向 start 反推 (YoY 跨年反推)
    latest_seed_b = _anchor_year_values(latest_anchor)
    if latest_seed_b is not None:
        bwd_vals, bwd_flags = _chain_from(latest_seed_b, latest_anchor, "backward")
        for mk, v in bwd_vals.items():
            if mk not in values:
                values[mk] = v
                calc_flags[mk] = bwd_flags[mk]

    # 锚点年内各月用 seed 精确值 (严格满足年合计)
    for ay in anchor_years:
        seg_seed = _anchor_year_values(ay)
        if seg_seed is None:
            continue
        for mo in range(1, 13):
            mk = _month_key(ay, mo)
            values[mk] = seg_seed[mk]
            calc_flags[mk] = "anchor" if mo == 1 else "backward"

    # 5. YoY 双向校验 + 校准
    rows: list[dict[str, object]] = []
    chain_values: dict[str, float | None] = dict(values)
    last_output: float | None = None

    for y, m in _iter_months((sy, sm), (ey, em)):
        mk = _month_key(y, m)
        rec = monthly.get(mk) or {}
        yoy = rec.get("china_yoy_growth")
        mom = rec.get("china_mom_growth")
        chain_val = chain_values.get(mk)
        flag = calc_flags.get(mk, "gap")
        is_anchor_year = y in year_anchors

        # 校准沿链传播: forward/gap_flat 月份若前一月已校准, 基于前一月输出 × (1+mom) 重建
        if flag in ("forward", "gap_flat") and last_output is not None and chain_val is not None:
            if isinstance(mom, int | float) and mom is not None:
                chain_val = last_output * (1.0 + float(mom))
                chain_values[mk] = chain_val
            elif flag == "gap_flat":
                chain_val = last_output
                chain_values[mk] = chain_val

        # 12 个月 MoM 复合: product(1+mom_{k-11..k}) - 1
        check_diff: float | None = None
        check_status = "missing"
        if isinstance(yoy, int | float) and yoy is not None:
            moms: list[float] = []
            cy, cm = y, m
            for _ in range(12):
                ck = _month_key(cy, cm)
                crec = monthly.get(ck) or {}
                cmom = crec.get("china_mom_growth")
                if isinstance(cmom, int | float) and cmom is not None:
                    moms.append(float(cmom))
                else:
                    break
                cy, cm = _prev_month(cy, cm)
            if len(moms) == 12:
                compound = 1.0
                for mm in moms:
                    compound *= 1.0 + mm
                check_diff = round(compound - 1.0 - float(yoy), 4)
                check_status = "ok" if abs(check_diff or 0) < 0.05 else "mismatch"
            else:
                check_status = "partial"

        # YoY 校准 (锚点年内跳过, 保持年合计约束)
        val = chain_val
        if not is_anchor_year:
            prev_key = _month_key(y - 1, m)
            prev_chain = chain_values.get(prev_key)
            if (
                prev_chain is not None
                and chain_val is not None
                and isinstance(yoy, int | float)
                and yoy is not None
                and abs(chain_val / prev_chain - 1.0 - float(yoy)) >= 0.05
            ):
                val = round(prev_chain * (1.0 + float(yoy)), 2)
                flag = "corrected"
                check_status = "corrected"
                # 校准反馈回链值, 使后续月份 MoM 前推基于校准值 (保持链条连续)
                chain_values[mk] = val

        rows.append(
            {
                "report_month": mk,
                "trade_date": date(y, m, calendar.monthrange(y, m)[1]),
                "china_sales_usd": round(val, 2) if val is not None else None,
                "china_yoy_growth": yoy,
                "china_mom_growth": mom,
                "anchor_flag": is_anchor_year,
                "calc_flag": flag,
                "yoy_check_diff": check_diff,
                "check_status": check_status,
                "source_url": rec.get("source_url") or "",
            }
        )
        # 记录本行输出值, 供下一 forward/gap_flat 月份校准传播
        last_output = val if val is not None else last_output

    return pl.DataFrame(rows, schema=CHINA_SERIES_SCHEMA).sort("report_month")


def save_china_series(df: pl.DataFrame, path: str | Path) -> int:
    """落盘 China 推算序列到 curated 黄金表。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p)
    logger.info("China 序列落盘成功 [%s]: 共 %d 行", p.name, df.height)
    return df.height


def parse_sia_raw_dir(raw_dir: str | Path = "data/raw/industry/sia") -> list[dict[str, object]]:
    """扫描 SIA raw 新闻目录, 解析全部 China 信息。"""
    import glob
    import gzip

    files = sorted(glob.glob(str(Path(raw_dir) / "*.html.gz")))
    records: list[dict[str, object]] = []
    for f in files:
        try:
            with gzip.open(f, "rt", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except Exception:
            continue
        r = parse_sia_china_enriched(text, f)
        if r:
            records.append(r)
    logger.info("SIA raw 解析完成: %d 篇新闻 -> %d 条 China 记录", len(files), len(records))
    return records
