"""历史 Curated 文件读取兼容规则。"""

from collections.abc import Iterable

_IDENTITY_ALIASES = frozenset({"ts_code", "stockCode", "code", "date", "asOfDate"})
_KNOWN_FLOAT_COLUMNS = frozenset(
    {
        "rqyl",
        "rzye",
        "rqye",
        "rzmre",
        "rzche",
        "rqchl",
        "rqmcl",
        "rzrqye",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "vol",
        "pe",
        "pb",
        "ps",
        "pe_ttm",
        "pb_mrq",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_mv",
        "circ_mv",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "adj_factor",
        "fd_share",
        "float_share",
        "float_ratio",
        "free_share",
        "total_share",
        "n_shares",
        "value",
        "yield",
        "tcm_y10",
        "market_cap",
        "total_assets",
        "trailing_pe",
        "forward_pe",
        "price_to_book",
        "price_to_sales",
        "dividend_yield",
        "net_mf_amount",
        "buy_sm_amount",
        "sell_sm_amount",
        "buy_md_amount",
        "sell_md_amount",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
        "money_cap",
        "total_cur_assets",
        "total_cur_liab",
        "total_nca",
        "total_ncl",
        "oper_cost",
        "fin_exp",
        "minority_gain",
        "expense_of_sales",
        "fa_turn",
        "gc_of_gr",
        "q_gc_to_gr",
        "tangible_asset",
        "tangibleasset_to_debt",
        "tbassets_to_totalassets",
        "total_size",
        "limit_amount",
        "pre_close",
        "max_price",
        "min_price",
        "op_pr",
        "rd",
        "ev_ebitda",
        "diluted_roe",
    }
)

_KNOWN_DATE_COLUMNS = frozenset(
    {
        "trade_date",
        "ann_date",
        "float_date",
        "f_ann_date",
        "report_date",
        "end_date",
        "as_of_date",
        "list_date",
        "delist_date",
        "base_date",
        "found_date",
        "due_date",
        "issue_date",
        "purc_startdate",
        "redm_startdate",
        "pretrade_date",
        "first_ann_date",
        "publish_date",
        "cal_date",
        "begin_date",
        "close_date",
        "exp_date",
        "value_date",
        "maturity_date",
        "conv_start_date",
        "conv_end_date",
        "conv_stop_date",
        "in_date",
        "out_date",
        "last_data_date",
        "last_edate",
        "last_ddate",
        "start_date",
        "suspend_date",
        "reportDate",
        "standardDate",
        "Date Reported",
        "Start Date",
        "announcement_date",
        "observation_date",
    }
)

_FINANCIAL_TEXT_COLUMNS = frozenset(
    {
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_date",
        "report_type",
        "comp_type",
        "end_type",
        "update_flag",
        "symbol",
        "ts_code",
        "data_source",
        "source_endpoint",
        "request_id",
        "updated_at",
        "market",
        "exchange",
        "currency",
        "adjustment",
        "schema_version",
        "name",
        "report_title",
        "classify",
        "org_name",
        "author_name",
        "quarter",
        "rating",
        "perf_summary",
        "type",
        "summary",
        "change_reason",
        "accountant",
        "accountingFirm",
        "auditOpinionType",
    }
)

_FINANCIAL_DATASETS = frozenset(
    {"balancesheet", "income", "fina_indicator", "cashflow", "forecast"}
)

_DATASET_FLOAT_COLUMNS: dict[str, frozenset[str]] = {
    "etf_share_size": frozenset(
        {"total_share", "total_size", "float_share", "float_size", "nav", "close"}
    ),
    "report_rc": frozenset(
        {
            "op_rt",
            "op_pr",
            "tp",
            "np",
            "eps",
            "pe",
            "rd",
            "roe",
            "ev_ebitda",
            "max_price",
            "min_price",
        }
    ),
    "limit_list_d": frozenset(
        {
            "close",
            "pct_chg",
            "amount",
            "limit_amount",
            "float_mv",
            "total_mv",
            "turnover_ratio",
            "fd_amount",
            "limit_times",
        }
    ),
    "opt_daily": frozenset(
        {
            "pre_settle",
            "pre_close",
            "open",
            "high",
            "low",
            "close",
            "settle",
            "vol",
            "amount",
            "oi",
        }
    ),
    "express": frozenset(
        {
            "revenue",
            "operate_profit",
            "total_profit",
            "n_income",
            "total_assets",
            "total_hldr_eqy_exc_min_int",
            "diluted_eps",
            "diluted_roe",
            "yoy_net_profit",
            "prior_period_net_profit",
            "bps",
            "open_net_assets",
            "open_bps",
        }
    ),
    "fina_indicator": frozenset(
        {
            "expense_of_sales",
            "fa_turn",
            "gc_of_gr",
            "q_gc_to_gr",
            "tangible_asset",
            "tangibleasset_to_debt",
            "tbassets_to_totalassets",
        }
    ),
    "hsgt_top10": frozenset({"change", "net_amount", "buy", "sell"}),
    "sf_month": frozenset({"stk_endval", "stk_endval_yoy"}),
    "shibor_lpr": frozenset({"1y", "5y"}),
    "opt_basic": frozenset({"per_unit", "exercise_price", "list_price", "min_price_chg"}),
    "fund_basic": frozenset({"exp_return"}),
    "unlock_summary": frozenset(
        {
            "srl_last",
            "srl_cap_r_last",
            "elr_s_y1",
            "elr_s_cap_r_y1",
            "elr_mc_y1",
        }
    ),
}

_LIXINGER_FINANCIAL_STATEMENT_OPTIONAL_COLUMNS = frozenset(
    {"accountant", "accountingFirm", "auditOpinionType"}
)

_DATASET_OPTIONAL_COLUMNS: dict[str, frozenset[str]] = {
    "sw_daily": frozenset(
        {
            "classification",
            "industry_level",
            "industry_code",
            "industry_name",
            "parent_code",
            "classification_status",
        }
    ),
    "etf_share_size": frozenset(
        {"etf_name", "fund_type", "total_size", "float_share", "float_size", "nav", "close"}
    ),
    "express": frozenset(
        {
            "revenue",
            "operate_profit",
            "total_profit",
            "n_income",
            "total_assets",
            "total_hldr_eqy_exc_min_int",
            "diluted_eps",
            "diluted_roe",
            "prior_period_net_profit",
            "bps",
            "open_net_assets",
            "open_bps",
            "perf_summary",
            "update_flag",
        }
    ),
    "fs_non_financial": _LIXINGER_FINANCIAL_STATEMENT_OPTIONAL_COLUMNS,
    "fs_bank": _LIXINGER_FINANCIAL_STATEMENT_OPTIONAL_COLUMNS,
    "fs_security": _LIXINGER_FINANCIAL_STATEMENT_OPTIONAL_COLUMNS,
    "fs_insurance": _LIXINGER_FINANCIAL_STATEMENT_OPTIONAL_COLUMNS,
    "sw_2021_fs_non_financial": _LIXINGER_FINANCIAL_STATEMENT_OPTIONAL_COLUMNS,
    "sw_2021_fs_bank": _LIXINGER_FINANCIAL_STATEMENT_OPTIONAL_COLUMNS,
    "sw_2021_fs_security": _LIXINGER_FINANCIAL_STATEMENT_OPTIONAL_COLUMNS,
    "sw_2021_fs_insurance": _LIXINGER_FINANCIAL_STATEMENT_OPTIONAL_COLUMNS,
}


def numeric_columns_for_dataset(dataset_name: str, columns: Iterable[str]) -> frozenset[str]:
    """返回指定数据集当前列中应为数值的字段。"""
    available = {str(column) for column in columns}
    if dataset_name in _FINANCIAL_DATASETS:
        return frozenset(available - _FINANCIAL_TEXT_COLUMNS - _KNOWN_DATE_COLUMNS)
    return frozenset(
        available & (_KNOWN_FLOAT_COLUMNS | _DATASET_FLOAT_COLUMNS.get(dataset_name, frozenset()))
    )


def optional_columns_for_dataset(dataset_name: str) -> frozenset[str]:
    """返回允许随数据源响应变化、但需在合并时补齐的业务可选列。"""
    return _DATASET_OPTIONAL_COLUMNS.get(dataset_name, frozenset())


__all__ = [
    "_KNOWN_DATE_COLUMNS",
    "_KNOWN_FLOAT_COLUMNS",
    "numeric_columns_for_dataset",
    "optional_columns_for_dataset",
]
