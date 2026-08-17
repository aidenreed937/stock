"""Cross-provider capability registrations for data-source routing decisions."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapabilityRegistration:
    """Describe whether a provider can supply a requested research capability."""

    provider: str
    capability: str
    status: str
    endpoint_names: tuple[str, ...] = field(default_factory=tuple)
    raw_fields: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""


DATA_SOURCE_CAPABILITY_REGISTRY: dict[tuple[str, str], CapabilityRegistration] = {
    ("yfinance", "implied_volatility"): CapabilityRegistration(
        provider="yfinance",
        capability="implied_volatility",
        status="native_raw",
        endpoint_names=("Ticker.option_chain",),
        raw_fields=("impliedVolatility",),
        note="Returns current option-chain snapshots; no historical IV backfill task is exposed.",
    ),
    ("tushare", "implied_volatility"): CapabilityRegistration(
        provider="tushare",
        capability="implied_volatility",
        status="raw_inputs",
        endpoint_names=("opt_basic", "opt_daily"),
        raw_fields=("exercise_price", "settle", "maturity_date"),
        note="No source IV field; these endpoints are inputs for a later model calculation.",
    ),
    ("lixinger", "implied_volatility"): CapabilityRegistration(
        provider="lixinger",
        capability="implied_volatility",
        status="unsupported",
        endpoint_names=("cn/index/volatility",),
        raw_fields=("value",),
        note="The documented endpoint is historical annualized realized volatility, not IV.",
    ),
    ("yfinance", "new_investor_accounts"): CapabilityRegistration(
        provider="yfinance",
        capability="new_investor_accounts",
        status="unsupported",
    ),
    ("tushare", "new_investor_accounts"): CapabilityRegistration(
        provider="tushare",
        capability="new_investor_accounts",
        status="historical_only",
        endpoint_names=("stk_account",),
        raw_fields=("date", "weekly_new", "total"),
        note="The official documentation states that this endpoint has stopped updating.",
    ),
    ("lixinger", "new_investor_accounts"): CapabilityRegistration(
        provider="lixinger",
        capability="new_investor_accounts",
        status="native",
        endpoint_names=("macro/investor",),
        raw_fields=("nni_m", "n_non_ni_m", "nni_w", "n_non_ni_w"),
    ),
    ("yfinance", "HG=F"): CapabilityRegistration(
        provider="yfinance",
        capability="HG=F",
        status="native",
        endpoint_names=("macro_indicators",),
        raw_fields=("Open", "High", "Low", "Close", "Volume"),
        note=(
            "Yahoo Finance copper futures symbol; local backfill is separate from "
            "symbol registration."
        ),
    ),
    ("tushare", "HG=F"): CapabilityRegistration(
        provider="tushare",
        capability="HG=F",
        status="unsupported",
        endpoint_names=("fut_index_daily",),
        note=(
            "TuShare does not expose the Yahoo Finance HG=F symbol or an equivalent "
            "registered contract route."
        ),
    ),
    ("lixinger", "HG=F"): CapabilityRegistration(
        provider="lixinger",
        capability="HG=F",
        status="unsupported",
        endpoint_names=("macro/non-ferrous-metals",),
        raw_fields=("l_cu_p",),
        note=(
            "The documented data is London copper spot, not the Yahoo Finance HG=F futures series."
        ),
    ),
    ("yfinance", "GC=F"): CapabilityRegistration(
        provider="yfinance",
        capability="GC=F",
        status="native",
        endpoint_names=("macro_indicators",),
        raw_fields=("Open", "High", "Low", "Close", "Volume"),
        note="Yahoo Finance gold futures symbol; local macro data is already present.",
    ),
    ("yfinance", "CL=F"): CapabilityRegistration(
        provider="yfinance",
        capability="CL=F",
        status="native",
        endpoint_names=("macro_indicators",),
        raw_fields=("Open", "High", "Low", "Close", "Volume"),
        note="Yahoo Finance crude-oil futures symbol; local macro data still needs backfill.",
    ),
}


def get_capability(provider: str, capability: str) -> CapabilityRegistration:
    """Return one capability registration or raise a clear lookup error."""
    key = (provider.lower(), capability)
    try:
        return DATA_SOURCE_CAPABILITY_REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"未注册数据能力 [{provider}/{capability}]") from exc


__all__ = [
    "DATA_SOURCE_CAPABILITY_REGISTRY",
    "CapabilityRegistration",
    "get_capability",
]
