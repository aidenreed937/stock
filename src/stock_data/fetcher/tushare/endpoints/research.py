"""TuShare 股东、筹码、龙虎榜与题材研究类接口注册表。"""

from stock_data.fetcher.tushare.registry_meta import EndpointMeta

RESEARCH_ENDPOINTS: dict[str, EndpointMeta] = {
    "stk_holdernumber": EndpointMeta(
        api_name="stk_holdernumber",
        description="上市公司股东户数",
        frequency="quarterly",
        query_mode="period",
        group="shareholder_data",
        primary_keys=["ts_code", "ann_date", "end_date"],
        date_columns=["ann_date", "end_date"],
        required_columns=["ts_code", "ann_date", "end_date", "holder_num"],
        update_time="18:00",
        max_rows_per_request=3000,
        request_fields="ts_code,ann_date,end_date,holder_num",
    ),
    "top10_floatholders": EndpointMeta(
        api_name="top10_floatholders",
        description="上市公司前十大流通股东",
        frequency="quarterly",
        query_mode="period",
        group="shareholder_data",
        primary_keys=["ts_code", "ann_date", "end_date", "holder_name"],
        date_columns=["ann_date", "end_date"],
        required_columns=["ts_code", "ann_date", "end_date", "holder_name", "hold_amount"],
        update_time="18:00",
        max_rows_per_request=6000,
        request_fields=(
            "ts_code,ann_date,end_date,holder_name,hold_amount,hold_ratio,"
            "hold_float_ratio,hold_change,holder_type"
        ),
    ),
    "dividend": EndpointMeta(
        api_name="dividend",
        description="上市公司分红送股明细",
        frequency="event",
        query_mode="symbol",
        symbol_query_mode="ann_date",
        group="corporate_action",
        primary_keys=["ts_code", "end_date", "ann_date", "div_proc"],
        date_columns=[
            "end_date",
            "ann_date",
            "record_date",
            "ex_date",
            "pay_date",
            "div_listdate",
            "imp_ann_date",
        ],
        required_columns=["ts_code", "end_date", "ann_date", "div_proc"],
        update_time="18:00",
        request_fields=(
            "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,"
            "cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,"
            "imp_ann_date,base_date,base_share"
        ),
    ),
    "cyq_perf": EndpointMeta(
        api_name="cyq_perf",
        description="A 股每日筹码平均成本与胜率",
        frequency="daily",
        query_mode="trade_date",
        group="market_indicators",
        primary_keys=["ts_code", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["ts_code", "trade_date", "cost_50pct", "winner_rate"],
        update_time="19:00",
        max_rows_per_request=6000,
        request_fields=(
            "ts_code,trade_date,his_low,his_high,cost_5pct,cost_15pct,cost_50pct,"
            "cost_85pct,cost_95pct,weight_avg,winner_rate"
        ),
    ),
    "cyq_chips": EndpointMeta(
        api_name="cyq_chips",
        description="A 股每日筹码分布",
        frequency="daily",
        query_mode="trade_date",
        group="market_indicators",
        primary_keys=["ts_code", "trade_date", "price"],
        date_columns=["trade_date"],
        required_columns=["ts_code", "trade_date", "price", "percent"],
        update_time="19:00",
        request_window_days=30,
        per_symbol_windowed=True,
        max_rows_per_request=6000,
        request_fields="ts_code,trade_date,price,percent",
    ),
    "top_list": EndpointMeta(
        api_name="top_list",
        description="龙虎榜每日交易明细",
        frequency="daily",
        query_mode="trade_date",
        group="market_behavior",
        primary_keys=["trade_date", "ts_code", "reason"],
        date_columns=["trade_date"],
        required_columns=["trade_date", "ts_code", "reason"],
        update_time="18:00",
        request_window_days=1,
        max_rows_per_request=10000,
        request_fields=(
            "trade_date,ts_code,name,close,pct_change,turnover_rate,amount,l_sell,"
            "l_buy,l_amount,net_amount,net_rate,amount_rate,float_values,reason"
        ),
        symbol_query_mode="trade_date",
    ),
    "top_inst": EndpointMeta(
        api_name="top_inst",
        description="龙虎榜机构成交明细",
        frequency="daily",
        query_mode="trade_date",
        group="market_behavior",
        primary_keys=["trade_date", "ts_code", "exalter", "side", "reason"],
        date_columns=["trade_date"],
        required_columns=["trade_date", "ts_code", "exalter", "side", "reason"],
        update_time="18:00",
        request_window_days=1,
        max_rows_per_request=10000,
        request_fields=(
            "trade_date,ts_code,exalter,side,buy,buy_rate,sell,sell_rate,net_buy,reason"
        ),
        symbol_query_mode="trade_date",
    ),
    "dc_concept": EndpointMeta(
        api_name="dc_concept",
        description="东方财富概念题材日度快照",
        frequency="daily",
        query_mode="trade_date",
        group="theme_data",
        primary_keys=["theme_code", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["theme_code", "trade_date", "name"],
        update_time="18:00",
        request_window_days=1,
        max_rows_per_request=5000,
        request_fields=(
            "theme_code,trade_date,name,pct_change,hot,sort,strength,z_t_num,"
            "main_change,lead_stock,lead_stock_code,lead_stock_pct_change"
        ),
    ),
    "dc_concept_cons": EndpointMeta(
        api_name="dc_concept_cons",
        description="东方财富概念题材成分股日度快照",
        frequency="daily",
        query_mode="trade_date",
        group="theme_data",
        primary_keys=["ts_code", "trade_date", "theme_code"],
        date_columns=["trade_date"],
        required_columns=["ts_code", "trade_date", "theme_code"],
        update_time="18:00",
        request_window_days=1,
        per_symbol_windowed=True,
        max_rows_per_request=3000,
        request_fields=("ts_code,trade_date,name,theme_code,industry_code,industry,reason,hot_num"),
        symbol_query_mode="trade_date",
    ),
    "stk_managers": EndpointMeta(
        api_name="stk_managers",
        description="上市公司管理层任职信息",
        frequency="event",
        query_mode="ann_date",
        group="governance_data",
        primary_keys=["ts_code", "ann_date", "name", "title"],
        date_columns=["ann_date", "begin_date", "end_date"],
        required_columns=["ts_code", "ann_date", "name", "title"],
        update_time="18:00",
        request_fields=(
            "ts_code,ann_date,name,gender,lev,title,edu,national,birthday,"
            "begin_date,end_date,resume"
        ),
    ),
    "stk_surv": EndpointMeta(
        api_name="stk_surv",
        description="上市公司机构调研记录",
        frequency="event",
        query_mode="trade_date",
        group="research_data",
        primary_keys=["ts_code", "surv_date", "rece_org", "fund_visitors"],
        date_columns=["surv_date"],
        required_columns=["ts_code", "surv_date", "rece_org"],
        update_time="18:00",
        request_window_days=31,
        per_symbol_windowed=True,
        max_rows_per_request=400,
        request_fields=(
            "ts_code,name,surv_date,fund_visitors,rece_place,rece_mode,rece_org,"
            "org_type,comp_rece,content"
        ),
    ),
}


RESEARCH_PROFILES: dict[str, tuple[list[str], dict[str, str], str]] = {
    "stk_holdernumber": (
        ["ts_code", "ann_date", "end_date", "holder_num"],
        {"holder_num": "count"},
        "shareholder_event",
    ),
    "top10_floatholders": (
        ["ts_code", "ann_date", "end_date", "holder_name", "hold_amount"],
        {
            "hold_amount": "share",
            "hold_ratio": "percent",
            "hold_float_ratio": "percent",
            "hold_change": "share",
        },
        "shareholder_event",
    ),
    "dividend": (
        ["ts_code", "end_date", "ann_date", "div_proc"],
        {
            "stk_div": "share/share",
            "stk_bo_rate": "percent",
            "stk_co_rate": "percent",
            "cash_div": "CNY/share",
            "cash_div_tax": "CNY/share",
            "base_share": "10k_share",
        },
        "corporate_action_event",
    ),
    "cyq_perf": (
        ["ts_code", "trade_date", "cost_50pct", "winner_rate"],
        {
            "his_low": "CNY/share",
            "his_high": "CNY/share",
            "cost_5pct": "CNY/share",
            "cost_15pct": "CNY/share",
            "cost_50pct": "CNY/share",
            "cost_85pct": "CNY/share",
            "cost_95pct": "CNY/share",
            "weight_avg": "CNY/share",
            "winner_rate": "percent",
        },
        "market_indicator",
    ),
    "cyq_chips": (
        ["ts_code", "trade_date", "price", "percent"],
        {"price": "CNY/share", "percent": "percent"},
        "market_indicator",
    ),
    "top_list": (
        ["trade_date", "ts_code", "reason"],
        {
            "close": "CNY/share",
            "pct_change": "percent",
            "turnover_rate": "percent",
            "amount": "CNY",
            "l_sell": "CNY",
            "l_buy": "CNY",
            "l_amount": "CNY",
            "net_amount": "CNY",
            "net_rate": "percent",
            "amount_rate": "percent",
            "float_values": "CNY",
        },
        "event",
    ),
    "top_inst": (
        ["trade_date", "ts_code", "exalter", "side", "reason"],
        {
            "buy": "CNY",
            "buy_rate": "percent",
            "sell": "CNY",
            "sell_rate": "percent",
            "net_buy": "CNY",
        },
        "event",
    ),
    "dc_concept": (
        ["theme_code", "trade_date", "name"],
        {
            "pct_change": "percent",
            "hot": "count",
            "sort": "count",
            "strength": "count",
            "z_t_num": "count",
            "main_change": "CNY",
            "lead_stock_pct_change": "percent",
        },
        "event",
    ),
    "dc_concept_cons": (
        ["ts_code", "trade_date", "theme_code"],
        {"hot_num": "count"},
        "event",
    ),
    "stk_managers": (
        ["ts_code", "ann_date", "name", "title"],
        {},
        "governance_event",
    ),
    "stk_surv": (
        ["ts_code", "surv_date", "rece_org"],
        {},
        "research_event",
    ),
}
