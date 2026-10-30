"""中国创新药海外 License-out (BD) 领域数据模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PharmaLicenseOutRecord:
    """创新药出海 BD 月度聚合事实记录。"""

    report_month: str
    trade_date: date
    upfront_cash_million_usd: float | None = None
    potential_total_deal_million_usd: float | None = None
    deal_count: int = 0
    asset_count: int = 0
    mnc_deal_count: int = 0
    global_deal_count: int = 0
    median_upfront_million_usd: float | None = None
    avg_upfront_million_usd: float | None = None
    upfront_to_total_ratio: float | None = None
    upfront_3mma: float | None = None
    total_deal_3mma: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    global_rights_ratio: float | None = None
    mnc_ratio: float | None = None
    late_stage_ratio: float | None = None
    adc_asset_count: int = 0  # 当月 ADC 类型资产数 (一个 deal 可含多个资产)
    bispecific_asset_count: int = 0
    metabolic_glp1_asset_count: int = 0
    small_molecule_asset_count: int = 0
    unit: str = "million_usd"
    source: str = "PharmaCube/Filings/PR"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    monthly_upfront_million_usd: float | None = None
    monthly_total_deal_million_usd: float | None = None

    def __post_init__(self) -> None:
        if self.monthly_upfront_million_usd is not None and self.upfront_cash_million_usd is None:
            object.__setattr__(self, "upfront_cash_million_usd", self.monthly_upfront_million_usd)
        if (
            self.monthly_total_deal_million_usd is not None
            and self.potential_total_deal_million_usd is None
        ):
            object.__setattr__(
                self, "potential_total_deal_million_usd", self.monthly_total_deal_million_usd
            )
        if self.monthly_upfront_million_usd is None:
            object.__setattr__(self, "monthly_upfront_million_usd", self.upfront_cash_million_usd)
        if self.monthly_total_deal_million_usd is None:
            object.__setattr__(
                self, "monthly_total_deal_million_usd", self.potential_total_deal_million_usd
            )


@dataclass(frozen=True)
class PharmaBdDealRecord:
    """创新药 BD 交易级实体 (Deal Entity)。"""

    deal_id: str
    licensor: str
    licensor_type: str
    licensee: str
    is_mnc: bool
    transaction_type: str
    territory_scope: str
    announcement_date: date
    effective_date: date | None = None
    source_filing: str = ""
    source_url: str = ""


@dataclass(frozen=True)
class PharmaBdAssetRecord:
    """创新药 BD 资产级实体 (Asset Entity)。"""

    asset_id: str
    deal_id: str
    drug_name_code: str
    target: str
    modality: str
    stage: str
    indication: str = ""


@dataclass(frozen=True)
class PharmaBdEventRecord:
    """创新药 BD 交易事件与里程碑级实体 (Event Entity)。"""

    event_id: str
    deal_id: str
    event_type: str
    event_date: date
    upfront_cash_usd: float | None = None
    equity_investment_usd: float | None = None
    option_payment_usd: float | None = None
    near_term_milestone_usd: float | None = None
    potential_total_deal_usd: float | None = None
    equity_stake_pct: float | None = None
    original_currency: str = "USD"
    notes: str = ""
