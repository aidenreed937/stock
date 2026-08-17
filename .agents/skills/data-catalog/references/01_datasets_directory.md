# 全库黄金数据集资产数据字典 (Datasets Directory)

本字典汇总了系统本地已落盘的 **40+ 黄金数据集（Curated）** 的详细元数据、主键、覆盖范围与核心字段。

---

## 1. A 股行情与衍生量价 (`tushare`)

| 数据集名称 (`dataset`) | 业务含义 | 标的范围 / 历史区间 | 主键组合 | 核心字段清单 |
| :--- | :--- | :--- | :--- | :--- |
| **`stock_daily_bar`** | A 股全市场个股日 K 线 | 5,000+ A 股 (2013 至今) | `symbol`, `trade_date` | `open`, `high`, `low`, `close`, `volume(股)`, `amount(元)` |
| **`index_daily_bar`** | A 股 10 大核心指数日 K 线 | 上证指数/沪深300/中证500等 (12年) | `symbol`, `trade_date` | `open`, `high`, `low`, `close`, `volume`, `amount(元)` |
| **`adj_factor`** | A 股复权因子 | 5,000+ A 股全历史 | `symbol`, `trade_date` | `adj_factor` |
| **`fund_daily`** | 场内基金与 ETF 日 K 线 | 26 只核心 ETF 全历史 | `symbol`, `trade_date` | `open`, `high`, `low`, `close`, `volume`, `amount` |
| **`etf_share_size`** | 核心 ETF 份额与规模序列 | 26 只核心 ETF 全历史 | `symbol`, `trade_date` | `fd_share`, `n_shares` |
| **`moneyflow`** | 个股大单小单资金流向 | 全市场个股资金流 (2013 至今) | `symbol`, `trade_date` | `buy_sm_amount`, `buy_md_amount`, `buy_lg_amount`, `buy_elg_amount`, `net_mf_amount` (均为元) |
| **`moneyflow_hsgt`** | 北向资金每日净流入 | 沪股通/深股通/北向合计 (2014 至今) | `trade_date` | `hgt(元)`, `sgt(元)`, `north_money(元)` |
| **`margin`** | 全市场融资融券每日汇总 | SSE/SZSE/BSE 全历史 | `trade_date`, `exchange_id` | `rzye(元)`, `rzmre`, `rqye`, `rqyl`, `rzrqye` |
| **`margin_detail`** | 两融标的个股明细 | 标的个股每日两融 | `symbol`, `trade_date` | `rzye`, `rzmre`, `rqyl`, `rqmcl` |

---

## 2. 估值、基本面与预期分析 (`tushare` & `lixinger`)

| 数据集名称 (`dataset`) | 数据源 | 业务含义 | 主键组合 | 核心字段清单 |
| :--- | :--- | :--- | :--- | :--- |
| **`daily_basic`** | TuShare | A 股全市场每日估值与指标 | `symbol`, `trade_date` | `pe_ttm`, `pb`, `ps_ttm`, `dv_ttm`, `total_mv(元)`, `circ_mv(元)`, `turnover_rate` |
| **`index_fundamental`** | 理杏仁 | 9 大核心指数基本面估值 | `symbol`, `date` | `pe_ttm.mcw`, `pe_ttm.ew`, `pb.mcw`, `pb.ew`, `dyr.mcw`, `mc(元)` |
| **`report_rc`** | TuShare | 卖方研报一致预期盈利预测 | `symbol`, `report_date`, `org_name` | `quarter`, `np(元)`, `eps`, `tp(目标价)`, `rating`, `org_name` |
| **`forecast`** | TuShare | 上市公司业绩预告 (PIT) | `symbol`, `ann_date`, `end_date` | `type`, `p_change_min`, `p_change_max`, `net_profit_min`, `summary` |
| **`express`** | TuShare | 上市公司业绩快报 (PIT) | `symbol`, `ann_date`, `end_date` | `revenue(元)`, `operate_profit`, `n_income`, `yoy_net_profit`, `diluted_roe` |

---

## 3. 申万行业体系 (`tushare` & `lixinger`)

| 数据集名称 (`dataset`) | 数据源 | 业务含义 | 主键组合 | 核心字段清单 |
| :--- | :--- | :--- | :--- | :--- |
| **`sw_daily`** | TuShare | 申万行业日线行情与估值 | `symbol`, `trade_date` | `open`, `high`, `low`, `close`, `amount(元)`, `pe`, `pb` |
| **`index_classify`** | TuShare | 申万行业分类标准 (SW2014) | `index_code` | `index_code`, `industry_name`, `level`, `industry_code` |
| **`index_member`** | TuShare | 申万行业历史成份股流水 | `index_code`, `con_code`, `in_date` | `index_code`, `con_code`, `in_date`, `out_date` |
| **`sw_2021_constituents`** | 理杏仁 | 申万 2021 行业成份股图谱 | `symbol` | `symbol(行业代码)`, `constituents(成份股列表)` |
| **`sw_2021_fundamental`** | 理杏仁 | 申万 31 一级行业日度估值 | `symbol`, `date` | `pe_ttm.ew`, `pb.ew`, `ps_ttm.ew`, `dyr.ew`, `mc(元)` |
| **`sw_2021_l2_fundamental`** | 理杏仁 | 申万 162 二级行业日度估值 | `symbol`, `date` | `pe_ttm.ew`, `pb.ew`, `ps_ttm.ew`, `dyr.ew`, `mc(元)` |
| **`sw_2021_fs_non_financial`** | 理杏仁 | 29 个非金融行业合并财报 | `symbol`, `report_date` | `ps.toi.c_y2y`, `ps.np.c_y2y`, `ps.gp_m.ttm`, `m.roe.ttm` |
| **`sw_2021_fs_bank`** | 理杏仁 | 商业银行行业合并财报 | `symbol`, `report_date` | `ps.nii.c_y2y`, `ps.np.c_y2y`, `ps.cir.ttm`, `m.roe.ttm` |
| **`sw_2021_fs_security`** | 理杏仁 | 证券公司行业合并财报 | `symbol`, `report_date` | `ps.ib_n_inc.c_y2y`, `ps.np.c_y2y`, `m.roe.ttm` |
| **`sw_2021_fs_insurance`** | 理杏仁 | 保险公司行业合并财报 | `symbol`, `report_date` | `ps.ep.c_y2y`, `ps.np.c_y2y`, `m.roe.ttm` |

---

## 4. 全球资产、外盘与宏观利率 (`yfinance`, `fred`, `lixinger`, `alphavantage`)

| 数据集名称 (`dataset`) | 数据源 | 业务含义 | 主键组合 | 核心字段清单 |
| :--- | :--- | :--- | :--- | :--- |
| **`stock_daily_bar`** | YFinance | 美股科技巨头日 K 线 | `symbol`, `trade_date` | `open`, `high`, `low`, `close`, `volume` |
| **`index_daily_bar`** | YFinance | 外盘 9 大核心指数日 K 线 | `symbol`, `trade_date` | 标普500/纳指100/罗素2000 等 |
| **`macro_indicators`** | YFinance | 7 大全球宏观资产行情 | `symbol`, `trade_date` | 美债10Y/3M、美元指数、黄金、原油、铜、VIX |
| **`macro_indicators`** | FRED | 美联储官方核心宏观经济指标 | `symbol`, `trade_date` | FEDFUNDS, CPI, 失业率, 非农, GDP, 10Y-2Y 利差 |
| **`national_debt`** | 理杏仁 | 中债官方国债收益率序列 | `date` | `tcm_y1`, `tcm_y2`, `tcm_y5`, `tcm_y10`, `tcm_y30` |
| **`macro_indicators`** | AlphaVantage | USD/CNH 离岸人民币汇率 | `symbol`, `trade_date` | `open`, `high`, `low`, `close` |
