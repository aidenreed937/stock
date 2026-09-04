"""SEC online sources for semiconductor IDM inventory facts."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from stock_data.fetcher.industry.semiconductor.models import SemiconductorInventoryRecord

SEC_FACT_FORMS = frozenset({"10-Q", "10-K", "10-Q/A", "10-K/A", "20-F"})
COMPANYFACTS_INVENTORY_TAGS = (
    "InventoryNet",
    "InventoryFinishedGoodsNetOfReserves",
    "InventoryFinishedGoods",
)
COMPANYFACTS_COGS_TAGS = {
    "TXN": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    "ADI": ("CostOfGoodsSold", "CostOfGoodsAndServicesSold", "CostOfRevenue"),
    "NXPI": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
}
MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}


@dataclass(frozen=True)
class _FactValue:
    tag_priority: int
    unit: str
    start: date | None
    end: date
    value: float
    filed: date
    form: str
    accession: str


def parse_companyfacts_inventory(
    payload: Mapping[str, Any],
    *,
    symbol: str,
    start_date: date | None,
    end_date: date | None,
    source_url: str,
    raw_content_hash: str,
    raw_snapshot_path: str,
    collected_at: str,
) -> list[SemiconductorInventoryRecord]:
    """Parse instant inventory and duration COGS facts from SEC companyfacts."""
    facts = payload.get("facts", {})
    us_gaap = facts.get("us-gaap", {}) if isinstance(facts, Mapping) else {}
    if not isinstance(us_gaap, Mapping):
        return []

    inventory = _collect_facts(us_gaap, COMPANYFACTS_INVENTORY_TAGS, instant=True)
    cogs_tags = COMPANYFACTS_COGS_TAGS.get(symbol.upper(), ())
    cogs = _collect_facts(us_gaap, cogs_tags, instant=False)
    inventory_by_quarter = _pick_inventory(inventory, symbol)
    short_by_quarter, annual_by_quarter = _split_cogs(cogs, symbol)

    records: list[SemiconductorInventoryRecord] = []
    for year in range(2015, 2031):
        for quarter in range(1, 5):
            key = (year, quarter)
            if key not in inventory_by_quarter:
                continue
            inventory_fact = inventory_by_quarter[key]
            cogs_fact = _pick_earliest(short_by_quarter.get(key, ()))
            data_status = "actual"
            derivation = ""
            annual_raw: str | None = None
            if quarter == 4 and cogs_fact is None:
                annual_fact = _pick_earliest(annual_by_quarter.get(key, ()))
                previous_values = [
                    _pick_earliest(short_by_quarter.get((year, previous_quarter), ()))
                    for previous_quarter in (1, 2, 3)
                ]
                if annual_fact is not None and all(previous_values):
                    cogs_fact = _FactValue(
                        tag_priority=annual_fact.tag_priority,
                        unit=annual_fact.unit,
                        start=annual_fact.start,
                        end=annual_fact.end,
                        value=annual_fact.value
                        - sum(fact.value for fact in previous_values if fact is not None),
                        filed=annual_fact.filed,
                        form=annual_fact.form,
                        accession=annual_fact.accession,
                    )
                    data_status = "derived_q4"
                    derivation = "annual_minus_q1_q2_q3"
                    annual_raw = _raw_number(annual_fact.value)
            if cogs_fact is None:
                continue

            trade_date = _quarter_trade_date(year, quarter)
            if not _in_date_range(trade_date, start_date=start_date, end_date=end_date):
                continue
            record_url = _accession_url(symbol, inventory_fact.accession) or source_url
            release_date = max(inventory_fact.filed, cogs_fact.filed)
            records.append(
                SemiconductorInventoryRecord(
                    symbol=symbol.upper(),
                    report_quarter=f"{year}Q{quarter}",
                    trade_date=trade_date,
                    inventory_usd_million=inventory_fact.value / 1_000_000.0,
                    cost_of_revenue_usd_million=cogs_fact.value / 1_000_000.0,
                    unit="USD",
                    source="SEC_companyfacts",
                    source_url=record_url,
                    release_date=release_date,
                    data_status=data_status,
                    collected_at=collected_at,
                    inventory_usd_raw=_raw_number(inventory_fact.value),
                    cost_of_revenue_usd_raw=_raw_number(cogs_fact.value),
                    source_period_end=inventory_fact.end,
                    fiscal_period=f"Q{quarter}",
                    raw_content_sha256=raw_content_hash,
                    raw_snapshot_path=raw_snapshot_path,
                    cost_of_revenue_annual_raw=annual_raw,
                    cost_of_revenue_derivation=derivation,
                )
            )
    return records


def parse_sec_6k_inventory(
    content: bytes | str,
    *,
    symbol: str,
    report_quarter: str,
    release_date: date,
    source_url: str,
    raw_content_hash: str,
    raw_snapshot_path: str,
    collected_at: str,
) -> SemiconductorInventoryRecord | None:
    """Parse quarterly inventory and cost from a foreign issuer 6-K HTML report."""
    year = int(report_quarter[:4])
    quarter = int(report_quarter[-1])
    html = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content
    text = _normalise_html_text(html)
    income_start = _find_income_statement(text)
    terms = (
        ("Cost of sales", "Cost of revenue")
        if symbol == "STM"
        else (
            "Cost of revenue",
            "Cost of sales",
        )
    )
    cost_raw = _first_number_after_terms(text, terms, start=income_start)
    balance_start = _find_balance_sheet(text)
    inventory_raw = _first_number_after_terms(
        text,
        ("Inventories, net", "Inventories"),
        start=balance_start,
    )
    source_period_end = _find_quarter_end(text, year, quarter, anchor=income_start or balance_start)
    if cost_raw is None or inventory_raw is None or source_period_end is None:
        return None

    return SemiconductorInventoryRecord(
        symbol=symbol.upper(),
        report_quarter=report_quarter,
        trade_date=_quarter_trade_date(year, quarter),
        inventory_usd_million=_number_value(inventory_raw),
        cost_of_revenue_usd_million=_number_value(cost_raw),
        unit="million_usd",
        source="SEC_6K",
        source_url=source_url,
        release_date=release_date,
        data_status="actual",
        collected_at=collected_at,
        inventory_usd_raw=inventory_raw,
        cost_of_revenue_usd_raw=cost_raw,
        source_period_end=source_period_end,
        fiscal_period=f"Q{quarter}",
        raw_content_sha256=raw_content_hash,
        raw_snapshot_path=raw_snapshot_path,
    )


def _collect_facts(
    facts: Mapping[str, Any],
    tags: Sequence[str],
    *,
    instant: bool,
) -> list[_FactValue]:
    result: list[_FactValue] = []
    for tag_priority, tag in enumerate(tags):
        payload = facts.get(tag)
        if not isinstance(payload, Mapping):
            continue
        units = payload.get("units", {})
        if not isinstance(units, Mapping):
            continue
        for unit, values in units.items():
            if unit != "USD" or not isinstance(values, Sequence):
                continue
            for value in values:
                if not isinstance(value, Mapping):
                    continue
                form = str(value.get("form") or "").upper()
                if form not in SEC_FACT_FORMS:
                    continue
                end = _parse_date(value.get("end"))
                filed = _parse_date(value.get("filed"))
                if end is None or filed is None:
                    continue
                start = _parse_date(value.get("start"))
                if instant != (start is None):
                    continue
                try:
                    number = float(str(value.get("val")))
                except (TypeError, ValueError):
                    continue
                result.append(
                    _FactValue(
                        tag_priority=tag_priority,
                        unit=unit,
                        start=start,
                        end=end,
                        value=number,
                        filed=filed,
                        form=form,
                        accession=str(value.get("accn") or ""),
                    )
                )
    return result


def _pick_inventory(
    facts: Sequence[_FactValue],
    symbol: str,
) -> dict[tuple[int, int], _FactValue]:
    by_quarter: dict[tuple[int, int], list[_FactValue]] = defaultdict(list)
    for fact in facts:
        quarter = _quarter_from_period_end(symbol, fact.end)
        if quarter is not None:
            by_quarter[quarter].append(fact)
    result: dict[tuple[int, int], _FactValue] = {}
    for key, values in by_quarter.items():
        chosen = _pick_earliest(values)
        if chosen is not None:
            result[key] = chosen
    return result


def _split_cogs(
    facts: Sequence[_FactValue],
    symbol: str,
) -> tuple[dict[tuple[int, int], list[_FactValue]], dict[tuple[int, int], list[_FactValue]]]:
    short: dict[tuple[int, int], list[_FactValue]] = defaultdict(list)
    annual: dict[tuple[int, int], list[_FactValue]] = defaultdict(list)
    for fact in facts:
        quarter = _quarter_from_period_end(symbol, fact.end)
        if quarter is None or fact.start is None:
            continue
        duration = (fact.end - fact.start).days
        if 70 <= duration <= 110:
            short[quarter].append(fact)
        elif 300 <= duration <= 400:
            annual[(quarter[0], 4)].append(fact)
    return short, annual


def _pick_earliest(facts: Sequence[_FactValue]) -> _FactValue | None:
    if not facts:
        return None
    return min(
        facts,
        key=lambda fact: (
            fact.filed,
            fact.tag_priority,
            0 if fact.form in {"10-Q", "10-K"} else 1,
            fact.accession,
        ),
    )


def _quarter_from_period_end(symbol: str, period_end: date) -> tuple[int, int] | None:
    month = period_end.month
    if symbol.upper() == "ADI":
        quarter = 1 if month <= 2 else 2 if month <= 5 else 3 if month <= 8 else 4
    elif symbol.upper() == "NXPI":
        quarter = 1 if month <= 4 else 2 if month <= 7 else 3 if month <= 10 else 4
    else:
        quarter = 1 if month <= 3 else 2 if month <= 6 else 3 if month <= 9 else 4
    return period_end.year, quarter


def _quarter_trade_date(year: int, quarter: int) -> date:
    return date(year, (3, 6, 9, 12)[quarter - 1], (31, 30, 30, 31)[quarter - 1])


def _normalise_html_text(html: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ", strip=True))


def _find_income_statement(text: str) -> int:
    positions = [
        text.lower().find("statements of income"),
        text.lower().find("income statements"),
        text.lower().find("statements of operations"),
    ]
    return min((position for position in positions if position >= 0), default=0)


def _find_balance_sheet(text: str) -> int:
    consolidated = re.search(r"consolidated balance sheets?", text, flags=re.IGNORECASE)
    if consolidated is not None:
        return consolidated.start()
    position = text.lower().find("balance sheets")
    if position >= 0:
        return position
    return text.lower().find("balance sheet")


def _first_number_after_terms(text: str, terms: Sequence[str], *, start: int) -> str | None:
    end = start + 4_000 if start > 0 else len(text)
    candidates = [(text.lower().find(term.lower(), start, end), term) for term in terms]
    candidates = [(position, term) for position, term in candidates if position >= 0]
    if not candidates:
        return None
    position, term = min(candidates)
    segment = text[position + len(term) : position + len(term) + 300]
    match = re.search(r"(?:\(|-)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", segment)
    return match.group(1) if match else None


def _find_quarter_end(
    text: str,
    year: int,
    quarter: int,
    *,
    anchor: int = 0,
) -> date | None:
    target_date = _quarter_trade_date(year, quarter)
    pattern = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"[\u00a0 ]*([0-9]{1,2}),?[\u00a0 ]*([0-9]{4})"
    )
    matches = [
        (
            date(int(match.group(3)), MONTHS[match.group(1)], int(match.group(2))),
            match.start(),
        )
        for match in pattern.finditer(text)
        if int(match.group(3)) == year
        and abs(
            (
                date(int(match.group(3)), MONTHS[match.group(1)], int(match.group(2))) - target_date
            ).days
        )
        <= 45
    ]
    announced = [
        item
        for item in matches
        if item[1] <= 10_000
        and "ended" in text[max(0, item[1] - 120) : item[1]].lower()
        and "quarter" in text[max(0, item[1] - 180) : item[1]].lower()
    ]
    if announced:
        return min(announced, key=lambda item: abs((item[0] - target_date).days))[0]
    nearby = [item for item in matches if anchor <= item[1] <= anchor + 5_000]
    dates = nearby or matches
    if not dates:
        return None
    return min(dates, key=lambda item: abs((item[0] - target_date).days))[0]


def _number_value(value: str) -> float:
    return float(value.replace(",", ""))


def _raw_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _in_date_range(
    value: date,
    *,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    return (start_date is None or value >= start_date) and (end_date is None or value <= end_date)


def _accession_url(symbol: str, accession: str) -> str:
    if not accession:
        return ""
    cik = {"TXN": "97476", "ADI": "6281", "STM": "932787", "NXPI": "1413447"}.get(
        symbol.upper(), ""
    )
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/index.json"


__all__ = ["parse_companyfacts_inventory", "parse_sec_6k_inventory"]
