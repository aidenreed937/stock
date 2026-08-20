# A 视角量化投研简报 `quant_brief` 设计方案

> 状态：已实现，已通过针对性测试与静态检查
> 主题：在 `data/analytics/` 下新增与 `investor_brief` 同级的 A 视角（底层量化投研 / 风控决策链）简报产物管线，并新增大盘级 Top 5% 成交占比派生指标。

---

## 1. 背景与定位

仓库现有 `investor_brief` 是 **B 视角（普通投资者交付）**：面向"能不能参与 / 参与什么方向 / 如何控风险"，回答风险等级与行业候选。

A 视角 = **底层量化投研 / 金融工程 / 风控决策链**，是 B 视角同源事实的另一张脸，遵循
`composite-temperature-interpretation.md` 的四步决策框架：

1. **宏观定基调**（系统风险 → 五档仓位钟）
2. **量价判性质**（快慢背离 → 真牛市 vs 存量脉冲）
3. **微观排雷区**（拥挤度 / 两融拐点 → 一票否决）
4. **中观选方向**（行业轮动 → PB-ROE / TCR 矩阵）

新产物命名为 **`quant_brief`**，运行历史保存在 `data/analytics/quant_brief`；最新报告与现有
投资者简报并列落在 `data/analytics/investor_brief/latest/`，便于统一消费。

本方案的实现约束已经收敛为：`quant_brief` 是同一基准日市场温度和行业结构产物的只读解释层；
新增指标只进入市场温度事实 Mart，不直接扩展 `market_daily` 宽表；所有阈值、边界和仓位区间由
`config/analytics/quant_brief.yaml` 驱动；四类产物在 `make scan` 和多日期任务中按同一基准日串行生成。

---

## 2. 输入契约与数据可用性

与 `investor_brief` **完全一致**：只读 `market_temperature` + `industry_structure` 两个上游产物，不重新计算指标、不引入新数据源。

| 四步 | 所需输入 | 来源 | 可用性 |
|---|---|---|---|
| 1 宏观定基调 | `composite.temperature`、`systemic_risk` | `market_temperature/scores.json` | ✅ |
| 2 量价判性质 | `technical`/`fund_flow` 维度温度、20D/60D 行业扩散 | `market_temperature/scores.json` + `industry_structure{trend_diagnostics, structure_health}` | ✅ |
| 3 微观排雷区 | 行业拥挤扩散、两融拐点、**大盘 Top5% 拥挤度** | `industry_structure` + `market_temperature/facts.parquet` + 新增派生指标 | ⚠️ 部分需新增 |
| 4 中观选方向 | `top_structure` / `strong_trends` / `undervalued_improving` / `fund_flow_confirmed` / `top_crowding` / `lagging_or_weak` | `industry_structure/{scores.json, industry_panel.parquet}` | ✅ |

### 关键数据缺口

`market_temperature` 产物当前**不含大盘 Top 5% 成交占比**（该指标只存在于独立 `market_aggregate`
产物，不在 A 视角两个输入上游）。这将通过**新增派生指标**解决（见 §3）。

---

## 3. 新增指标：`amount_top_5pct_share`

### 3.1 口径

基于本地 `stock_daily_bar` 按日聚合，**全历史可复算**（不依赖实时腾讯源）。口径与
`market_aggregate.py:309 _top_amount_share` 完全一致：

```
每日：按 amount 降序取前 5% 个股 → 其成交额之和 ÷ 全市场成交额
top_count = ceil(成交个股数 × 0.05)
```

单位为 0-1 比例（`market_aggregate` 中 `Field(ge=0, le=1)`）。

### 3.2 落点

增加为市场温度计的 **DataCatalog 派生事实**，由
`src/stock_analytics/pipelines/market_temperature/derived.py` 从 `stock_daily_bar` 按日聚合输出
`metric_value` 事实。实际构建时在
`src/stock_analytics/marts/market_temperature.py` 读取一次所需行情窗口，批量计算所有目标日期，
避免按日期重复扫描 `stock_daily_bar`。理由：

- 它是"当日横截面排序占比"，而非标准时间序列指标值，契合派生聚合路径；
- 只在 `market_temperature` 产物加一次，`quant_brief` 通过 `market_facts` 读取，与
  `investor_brief` 读取水位一致。
- 不改动 `market_daily` 的 FeatureSpec 和存量 schema，降低 Mart 迁移影响面。

### 3.3 配置（YAML 观察项）

在 `config/analytics/market_temperature.yaml` 情绪面子组加一个观察项：

```yaml
- metric_id: amount_top_5pct_share
  weight: 0.0   # 不进入情绪面正式分，只作事实展示
```

`weight: 0` 保证不污染六维综合温度（与 SKILL 中期权 / settlement IV 观察项同一策略），仅作为
A 视角一票否决和事实依据。

必须显式声明 `source: derived`、`direction: positive`、`subgroup: activity`，并由事实层保存
`metric_date`、`sample_size`、`unit: ratio` 和缺失原因；比例不做 0-100 温度裁剪。

### 3.4 数据口径披露

该指标取**最新成交日的横截面 Top5% 成交占比**，非 20 日均值；使用时按单日事实解读，不断言趋势。
此限制写入 `report_consistency` 校验与 `quant_brief.data_quality_notes`。

### 3.5 主力资金与杠杆健康度观察指标

资金与杠杆作为 `market_temperature/facts.parquet` 的事实观察项，不直接把新增口径并入六维主温度：

| 指标 | 计算口径 | 用途 | 限制 |
|---|---|---|---|
| `main_large_order_net_inflow_share` | `(buy_lg + buy_elg - sell_lg - sell_elg) / market_amount` | 识别放量下的大单净流出 | Tushare `moneyflow` 大单分类代理，不等同于 Level-2 机构账户 |
| `main_money_net_inflow_share_20d_cum` | 20 个交易日主力净流入额 ÷ 20 日成交额 | 辅助观察资金方向是否持续偏弱 | 只能说明窗口累计事实，不能单独确认连续出货 |
| `margin_buy_share` | 融资买入额 ÷ 全市场成交额 | 识别融资交易活跃度过热 | 不是杠杆余额拐点 |
| `margin_penetration_percentile_1250d` | 两融余额 ÷ 流通市值的 5 年滚动分位 | 识别存量杠杆极端水位 | 高分位且余额增速为负只输出去杠杆观察 |
| `margin_balance_growth_20d/60d` | 两融余额的 20/60 交易日增长率 | 观察杠杆方向 | 当前链路不宣称严格高位拐点 |

当本地数据缺少 `buy_lg/sell_lg` 时，原有 `main_money_net_inflow_share` 仍可继续计算，新增大单指标输出为空；报告会明确标注回退到 `moneyflow` 主力净流入分类代理，不将其包装成 Level-2 事实。

---

## 4. 四步决策逻辑（interpretation）

全部基于 `market_scores.dimensions`（按 `dimension_id` 映射温度）+ `industry_scores` / `industry_panel` +
新增 `amount_top_5pct_share` 事实。

### 第 1 步 宏观定基调 — `quant_macro`

- 读 `composite.temperature` → 五档映射（`<20 / 20-40 / 40-60 / 60-80 / >80`）；
- 读 `systemic_risk.level/status/red_flags/warnings/offsets`；
- 输出 `stance`（仓位档文本）、`equity_position_band`（%）、`tactic`。

> 参考五档仓位钟：`composite-temperature-interpretation.md:38-44`。

### 第 2 步 量价判性质 — `quant_nature`

- 读 `technical` vs `fund_flow` 温度 + `industry.trend_diagnostics` / `structure_health` 的 20D/60D 行业扩散；
- 分类：
  - **真牛市三维共振**：`fund_flow≥60` 且 60D 行业扩散达到配置阈值且 `composite_delta` 达配置阈值；
  - **存量诱多短强中弱**：`technical≥60` 且 `fund_flow<50` 且 20D 行业扩散达到阈值、60D 扩散不超过上限；
  - **高位极热背离 / 中性**；
- 输出 `nature_type`、`technical/fund_flow_temp`、`breadth_20d/60d`、`message`。

`composite_delta` 只读取 `market_scores.drivers.composite_delta`。没有传入对比运行或对比值缺失时，
输出 `insufficient_comparison`，不默认判定为真牛市。

> 参考：`composite-temperature-interpretation.md:51-65`。

### 第 3 步 微观排雷区 — `quant_veto`

- 行业级拥挤：`crowded_industry_share≥30`、`top_crowding`、`crowding_temperature≥80` 计数；
  原始 TCR 是成交额占比/百分点，不能直接用 `tcr≥80` 代替拥挤温度判断；
- 两融确认：读取 `fund_flow` 两融渗透率 / `margin_balance_growth_20d/60d`。当前上游事实没有
  严格的历史拐点状态时，只输出“当前增长为负/资金确认不足”，不得宣称已完成“高位拐头转负且持续回落”；
- **大盘 Top5% 拥挤度**：`amount_top_5pct_share`（当日横截面，`>0.50` 触发警示）；
- 输出 `flags`（触发否决信号）、`crowded_industries`、`margin_note`、`top5pct_note`、`missing_note`。

> 一票否决参考：`composite-temperature-interpretation.md:73-83`。注意大盘 Top5% 为单日事实，不断言趋势。

### 第 4 步 中观选方向 — `quant_sector`

- 读 `top_structure` / `strong_trends` / `undervalued_improving` / `fund_flow_confirmed` / `top_crowding` / `lagging_or_weak`；
- **优先方向**：结构分靠前 + 资金确认 + `crowding_temperature<80` + 无"景气承压"标签；
- **回避方向**：拥挤 / 景气承压；
- 落后方向：`lagging_or_weak` 单列。

---

## 5. 四道风控闸门

`quant_brief` 在四步研判之前输出 `risk_gates`，把宏观总仓位、中观行业回避和微观资金观察分层：

1. **系统性风险与估值红旗**：估值温度 `>=85` 或上游系统性风险为高风险时，触发总仓位防守上限 `0%-30%`；综合温度 `>=65` 只输出“只减不加”观察，不自动等同于硬止损。
2. **主力资金与杠杆健康度**：精确大单净流入占比 `<=-5%` 且成交额处于 `>=90` 分位时触发资金硬风险观察；融资买入占比 `>10%`、两融高分位及余额增速为负时输出杠杆观察。单日数据不推断连续出货或必然踩踏。
3. **全市场技术宽度**：站上 60 日均线个股占比 `<30%` 或 20 日上涨行业少于 10 家时，标记少数抱团/宽度不足；达到 50% 且行业扩散达到配置线才算通过。
4. **行业拥挤度与成交占比**：行业 TCR `>=20%` 或拥挤温度 `>=80` 进入局部回避观察；TCR `>=25%` 或拥挤温度 `>=90` 标记为局部坚决回避，但不改写全市场总仓位硬闸门。

每道闸门输出 `status / severity / facts_text / message / action`。`severity=local` 只影响候选行业，不计入 `risk_gates.hard_stop`；上游事实缺失则输出 `insufficient`，总状态为 `partial`，不以模型记忆补齐。

## 6. 产物结构（镜像 investor_brief）

```
data/analytics/quant_brief/
  runs/as_of=YYYY-MM-DD/run_*/manifest.json, brief_report.md, brief_report.json
data/analytics/investor_brief/latest/
  brief_report.md       # 原有投资者简报
  quant_brief.md        # 最新量化投研简报
  quant_brief.json
```

`brief_report.json` 顶层：`schema_version / title / manifest / macro / nature / veto / sector / risk_gates /
data_quality_notes / reading_notes`。

其中 `macro` 保存综合温度、五档区间、风险等级、仓位区间、策略动作和理由；`nature` 保存性质、
维度温度、行业 20D/60D 扩散、`composite_delta` 及比较状态；`veto` 保存旗标、拥挤行业、两融
说明、Top5 说明和缺失项；`sector` 保存优先、回避、落后方向，并保留行业面板来源字段。

模板 `quant_brief.md.j2` 按四步分节 + "数据限制"节。

---

## 7. 全链路落点（镜像 investor_brief）

| # | 文件 | 内容 |
|---:|---|---|
| 1 | `config/analytics/quant_brief.yaml` | `artifact_root: data/analytics/quant_brief` 保存运行历史，`latest_root: data/analytics/investor_brief` 共享最新目录 |
| 2 | `src/stock_reporting/interpretation/quant_brief/{config,interpretation,__init__}.py` | `QuantBriefConfig` + 四步逻辑 |
| 3 | `src/stock_reporting/templates/quant_brief.py` | `build_quant_brief_json` / `render_quant_brief_markdown` |
| 4 | `src/stock_reporting/templates/temperature/quant_brief.md.j2` | 报告模板 |
| 5 | `src/stock_analytics/pipelines/quant_brief/{artifacts,pipeline,__init__}.py` | `run_quant_brief`（复用 investor_brief 读取/写入模式） |
| 6 | `src/stock_cli/quant_brief.py` | CLI 入口 `-m stock_cli.quant_brief` |
| 7 | `Makefile` | 新增 `quant-brief` 目标 + `scan` 追加 |
| 8 | `src/stock_analytics/pipelines/__init__.py`、`src/stock_reporting/templates/__init__.py`、`src/stock_reporting/__init__.py` | 导出接线 |
| 9 | `src/stock_analytics/pipelines/multi_date.py` | 批量时追加 `quant_brief` 产物（第 4 类） |
| 10 | `scripts/report_consistency.py` | `ARTIFACT_FILES` 加 `quant_brief`；`_check_*` 校验 quant 内容与输入链接；`_markdown_paths` 加文件；接入 `_check_forbidden_phrases` |
| 11 | `scripts/market_cycle_review.py` | 读取并列示 quant 产物，缺失时保留可定位告警 |
| 12 | 测试 | `tests/unit/stock_analytics/pipelines/quant_brief/{test_pipeline,test_interpretation}.py`、`test_reporting.py` 加渲染、`test_report_consistency.py`、`test_market_cycle_review.py` |

> 新指标落点：`src/stock_analytics/pipelines/market_temperature/derived.py` + `market_temperature.yaml` 观察项。

---

## 8. 口径与一致性保证

- 沿用 `investor_brief` 的 `_resolve_latest_common_date` / `_resolve_as_of_date` / manifest `inputs`
  链接；`report_consistency` 同步校验 quant 与上游的基准日 + run_id + 数值一致性。
- 外盘（`external_risk` / `external_pressure`）仅作宏观背景写入，不改写仓位的五档判定——
  除非 `systemic_risk` 本身已降档。
- 所有数值来源为本地产物；行业财报季频滞后、大盘 Top5% 单日横截面等限制在
  `data_quality_notes` 如实披露，不编造。

---

## 9. 已确认的兼容策略

- `multi_date` / `make scan` 将 `quant_brief` 设为**必产第四类产物**；运行历史独立保存，最新文件与
  `investor_brief` 共享 `latest/` 目录。
- `report_consistency` 对新生成日期强制校验 quant 输入基准日、run_id 和事实链接；扫描历史日期时，
  若旧日期没有 quant 目录先输出 legacy compatibility warning，不把历史存量直接判为新链路硬错误。
- 外盘风险仍只作宏观背景，不改变五档仓位；只有 `systemic_risk` 和配置驱动的本地事实能够改变仓位档位。
