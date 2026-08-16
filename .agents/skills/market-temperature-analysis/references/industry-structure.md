# 申万行业结构分析

## 定位

行业结构分析是六维市场温度计之后的中观方向筛选模块。六维温度计回答“市场整体热不热、风险偏好如何”，行业结构分析回答“哪些申万行业在走强、哪些有性价比、哪些已经拥挤”。

不要把行业结构分并入六维综合温度。两者应组合使用：

```text
六维市场温度计 -> 判断仓位和风险偏好
申万行业结构分析 -> 判断方向、轮动和拥挤风险
```

## 标准产物

优先使用仓库内行业结构产物管线：

```bash
make industry-structure DATE=YYYY-MM-DD
# 或
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock.cli.industry_structure --date YYYY-MM-DD
```

默认配置为 `config/analytics/industry_structure.yaml`，产物目录为 `data/analytics/industry_structure/`：

- `runs/as_of=YYYY-MM-DD/run_YYYYMMDDTHHMMSS/manifest.json`
- `facts.parquet`
- `industry_panel.parquet`
- `scores.json`
- `report.md`
- `report.json`
- `human_report.md`
- `latest/`

## 数据源

核心数据：

- `tushare.sw_daily`：申万行业指数行情，计算 5/10/20/60/120 日收益、相对收益、TCR；
- `tushare.index_classify`：申万行业分类静态字典，用于识别 SW2021 一级行业；该表没有交易日期列，水位显示为 `static` 属正常；
- `tushare.index_daily`：宽基基准收益，缺失时用行业 20 日收益中位数回退；
- `tushare.index_member`：申万行业成份股映射，用于把个股级预告、快报和研报映射到一级行业；
- `tushare.forecast`：业绩预告，按最近 20 个交易日公告聚合行业正向预告占比和预告增速中位数；
- `tushare.express`：业绩快报，按最近 20 个交易日公告聚合行业净利润增速和 ROE 中位数；净利润增速由 `n_income` 相对 `yoy_net_profit` 手工计算，`yoy_net_profit` 在本地表中是上年同期净利润金额，不是同比百分比；
- `tushare.report_rc`：卖方盈利预测，按最近 20 个交易日研报计算同机构同报告期上修比例；
- `lixinger.sw_2021_fundamental`：申万一级行业 PE/PB/股息率和 PB-ROE 残差；
- `lixinger.sw_2021_constituents`：申万2021成份股图谱，在 `index_member` 缺失时补充行业映射；
- `lixinger.sw_2021_fs_*`：申万行业季频正式财报，计算收入/利润增速和 ROE 底座。

缺失数据必须披露为 `missing`、`unavailable` 或 `insufficient`，不要用模型记忆补值。

## 评分口径

行业结构分是排序分，不是市场温度。

默认四类子分：

| 子分 | 默认权重 | 方向 | 数据 |
|---|---:|---|---|
| 动量趋势 | 40% | 越强越高 | 20日收益、相对收益、60日收益、均线乖离 |
| 估值性价比 | 25% | 越便宜越高 | PE/PB 五年反向分位、PB-ROE 残差 |
| 基本面合成 | 15% | 越强越高 | 正式财报底座 + 预告/快报/研报快速确认 |
| 拥挤度约束 | 20% | 越不拥挤越高 | TCR 历史反向分位 |

同时保留 `crowding_temperature`，该字段越高表示行业越拥挤，和 `crowding_score` 方向相反。

TCR 定义：

- `TCR = 最近20个行业交易日的行业成交额占全部申万一级行业成交额比例均值`，单位为百分点；
- `tcr_percentile` 是该行业自身历史 TCR 分位；
- `crowding_temperature = tcr_percentile`，越高越拥挤；
- `crowding_score = 100 - crowding_temperature`，越高越不拥挤。

标准化规则：

- 动量趋势使用基准日申万一级行业横截面分位，越强越高；
- 估值使用 PE/PB 五年历史反向分位和 PB-ROE 残差横截面反向分位，越便宜或越低估越高；
- 基本面使用正式财报历史分位与快速确认横截面分位合成；正式财报只代表中期底座，快速项只代表最近 20 个交易日内可见的预告、快报和研报变化；
- 拥挤度使用行业自身 TCR 历史反向分位，避免高成交集中行业被直接当作机会。

基本面合成：

- `official_fundamental_score`：来自 `sw_2021_fs_non_financial`、`sw_2021_fs_bank`、`sw_2021_fs_security`、`sw_2021_fs_insurance`，对收入 TTM 增速、利润 TTM 增速和 ROE TTM 的行业自身历史分位取可用均值；
- `fast_fundamental_score`：来自 `forecast_positive_share`、`forecast_p_change_mid_median`、`express_profit_growth_median`、`express_roe_median`、`report_rc_revision_ratio` 的基准日行业横截面分位，取可用均值；`express_profit_growth_median` 只在上年同期净利润为正时计算；
- `fundamental_score`：正式财报分和快速确认分按配置合成，缺失一侧时按有效权重重归一；
- `fundamental_status` 是机器字段，报告展示时必须翻译为中文：
  - `fresh_blended`：财报未滞后，且已有预告/快报/研报辅助；
  - `stale_blended`：财报已滞后，但已有预告/快报/研报辅助；
  - `official_only`：仅使用未滞后的正式财报；
  - `official_stale`：仅有已滞后的正式财报，缺少快速确认；
  - `provisional_fast_only`：仅有预告/快报/研报快速确认；
  - `insufficient`：基本面数据不足。

默认配置：

| 状态 | 正式财报权重 | 快速确认权重 | 说明 |
|---|---:|---:|---|
| 财报未滞后 | 70% | 30% | 正式财报为主，预告/快报/研报辅助确认 |
| 财报滞后超过 90 天 | 40% | 60% | 短期降级，避免旧财报压过最新预期和公告 |

这只是行业基本面子分内部的合成规则。行业结构总分里，基本面合成分仍只占默认 15%，不会替代动量、估值或拥挤度。

## 输出解读

优先输出：

- 结构健康度；
- 结构分 Top 行业；
- 动量主线；
- 低估改善行业；
- 拥挤风险行业；
- 落后方向/结构靠后行业；
- 数据水位和缺失项。

标签含义：

- `强势主线`：`momentum_score >= 75` 且 `return_20d > 0`；
- `低估改善`：`valuation_score >= 70` 且 `fundamental_score >= 55`；
- `拥挤风险`：`crowding_temperature >= 80`；
- `超跌修复`：`return_20d < 0` 且 `return_5d > 0`；
- `景气承压`：`fundamental_score < 40`；
- `相对占优`：`relative_return_20d > 0`；
- `中性观察`：不满足以上标签时使用。

分组规则：

- 结构分 Top：`structure_score` 降序前 10；
- 动量主线：`momentum_score` 降序前 5；
- 低估线索：`valuation_score` 降序前 5；
- 强势主线/低估改善/拥挤风险：满足对应标签后按 `structure_score` 降序；
- 落后方向：`structure_score` 升序后 5，即当前动量、估值、基本面和拥挤约束合成后最靠后的行业。

标签和分组不是互斥关系。同一行业可以同时出现“强势主线”和“拥挤风险”，也可以在“落后方向”中带有其他风险标签。

结构健康度：

- `positive_return_20d_share`：20 日收益为正的行业占比，衡量短线扩散；
- `positive_return_60d_share`：60 日收益为正的行业占比，衡量中期确认；
- `top_negative_60d_count`：结构分前 10 行业中 60 日收益仍为负的数量，衡量领先行业是否只是短线反弹；
- `crowded_industry_share`：拥挤温度大于等于 80 的行业占比，衡量结构风险；
- `strong_trend_count`：强势主线数量，衡量主线清晰度。

解读优先级：

- 20 日扩散强、60 日扩散也强、拥挤行业占比低：结构健康；
- 20 日扩散强但 60 日扩散弱，且 Top 行业多数 60 日仍为负：修复中但偏脆弱；
- 拥挤行业多且 60 日扩散不足：偏脆弱；
- 20 日扩散不足：结构偏弱。

## 口径提醒

- 申万2021行业结构分析使用一级行业优先；`index_classify` 是静态字典表，无交易日期列时应显示为 `static`。若分类字典无记录或加载失败，代码才回退到 `sw_daily` 当前可用行业代码，名称优先用分类字典，再用 `sw_daily` 或理杏仁估值表名称回填，并在报告披露水位问题。
- 行业财报是季频，只代表基本面底座，不代表最近 20 个交易日内的财报变化。若财报日期明显早于基准日，应在结论中说明滞后天数，并查看 `fundamental_status_counts` 是否已经进入 `stale_blended` 或 `official_stale`。
- 快速基本面依赖个股到申万一级行业的映射。优先使用 `tushare.index_member + index_classify`，再用 `lixinger.sw_2021_constituents` 补充；若两者都不可用，快速基本面只能输出缺失，不能用行业名称猜测映射。
- `forecast` 只能称为“业绩预告改善/承压”，只有能与一致预期或历史口径匹配时才称“超预期”。`report_rc` 反映卖方预测修正，不等同真实财报改善。
- 若结构领先行业多数 60 日收益仍为负，报告应提示“短期修复强于中期趋势，中期趋势未全面确认”。
- 行业资金流目前不硬算。没有稳定行业颗粒度资金表时，不把主力或北向行业资金纳入结构分。
- 行业结构分应与六维市场温度交叉使用：市场过热时重点看拥挤风险，市场偏冷时重点看低估改善和超跌修复。
