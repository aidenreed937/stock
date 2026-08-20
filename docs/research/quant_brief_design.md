# A 视角量化投研简报 `quant_brief` 设计方案

> 状态：方案稿（待评审实现）
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

新产物命名为 **`quant_brief`**，产物根目录 `data/analytics/quant_brief`，与 `investor_brief` 同级。

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
`metric_value` 事实。理由：

- 它是"当日横截面排序占比"，而非标准时间序列指标值，契合派生聚合路径；
- 只在 `market_temperature` 产物加一次，`quant_brief` 通过 `market_facts` 读取，与
  `investor_brief` 读取水位一致。

### 3.3 配置（YAML 观察项）

在 `config/analytics/market_temperature.yaml` 情绪面子组加一个观察项：

```yaml
- metric_id: amount_top_5pct_share
  weight: 0.0   # 不进入情绪面正式分，只作事实展示
```

`weight: 0` 保证不污染六维综合温度（与 SKILL 中期权 / settlement IV 观察项同一策略），仅作为
A 视角一票否决和事实依据。

### 3.4 数据口径披露

该指标取**最新成交日的横截面 Top5% 成交占比**，非 20 日均值；使用时按单日事实解读，不断言趋势。
此限制写入 `report_consistency` 校验与 `quant_brief.data_quality_notes`。

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
  - **真牛市三维共振**：`fund_flow≥60` 且 60D 行业扩散高且 `composite` 上行；
  - **存量诱多短强中弱**：`technical≥60` 且 `fund_flow<50` 且 20D 行业多但 60D 少；
  - **高位极热背离 / 中性**；
- 输出 `nature_type`、`technical/fund_flow_temp`、`breadth_20d/60d`、`message`。

> 参考：`composite-temperature-interpretation.md:51-65`。

### 第 3 步 微观排雷区 — `quant_veto`

- 行业级拥挤：`crowded_industry_share≥30`、`top_crowding`、TCR≥80 计数；
- 两融拐点：`fund_flow` 两融渗透率 / `margin_balance_growth_20d/60d`；
- **大盘 Top5% 拥挤度**：`amount_top_5pct_share`（当日横截面，`>0.50` 触发警示）；
- 输出 `flags`（触发否决信号）、`crowded_industries`、`margin_note`、`top5pct_note`、`missing_note`。

> 一票否决参考：`composite-temperature-interpretation.md:73-83`。注意大盘 Top5% 为单日事实，不断言趋势。

### 第 4 步 中观选方向 — `quant_sector`

- 读 `top_structure` / `strong_trends` / `undervalued_improving` / `fund_flow_confirmed` / `top_crowding` / `lagging_or_weak`；
- **优先方向**：结构分靠前 + 资金确认 + `crowding_temperature<80` + 无"景气承压"标签；
- **回避方向**：拥挤 / 景气承压；
- 落后方向：`lagging_or_weak` 单列。

---

## 5. 产物结构（镜像 investor_brief）

```
data/analytics/quant_brief/
  runs/as_of=YYYY-MM-DD/run_*/manifest.json, brief_report.md, brief_report.json
  latest/   # 三个文件的副本
```

`brief_report.json` 顶层：`schema_version / manifest / macro / nature / veto / sector /
data_quality_notes / reading_notes`。

模板 `quant_brief.md.j2` 按四步分节 + "数据限制"节。

---

## 6. 全链路落点（镜像 investor_brief）

| # | 文件 | 内容 |
|---:|---|---|
| 1 | `config/analytics/quant_brief.yaml` | 镜像 investor_brief.yaml，`artifact_root: data/analytics/quant_brief` |
| 2 | `src/stock_reporting/interpretation/quant_brief/{config,interpretation,__init__}.py` | `QuantBriefConfig` + 四步逻辑 |
| 3 | `src/stock_reporting/templates/quant_brief.py` | `build_quant_brief_json` / `render_quant_brief_markdown` |
| 4 | `src/stock_reporting/templates/temperature/quant_brief.md.j2` | 报告模板 |
| 5 | `src/stock_analytics/pipelines/quant_brief/{artifacts,pipeline,__init__}.py` | `run_quant_brief`（复用 investor_brief 读取/写入模式） |
| 6 | `src/stock_cli/quant_brief.py` | CLI 入口 `-m stock_cli.quant_brief` |
| 7 | `Makefile` | 新增 `quant-brief` 目标 + `scan` 追加 |
| 8 | `src/stock_analytics/pipelines/__init__.py`、`src/stock_reporting/templates/__init__.py`、`src/stock_reporting/__init__.py` | 导出接线 |
| 9 | `src/stock_analytics/pipelines/multi_date.py` | 批量时追加 `quant_brief` 产物（第 4 类） |
| 10 | `scripts/report_consistency.py` | `ARTIFACT_FILES` 加 `quant_brief`；`_check_*` 校验 quant 内容与输入链接；`_markdown_paths` 加文件；接入 `_check_forbidden_phrases` |
| 11 | `scripts/market_cycle_review.py` | 追加 quant 产物目录（列示） |
| 12 | 测试 | `tests/unit/stock_analytics/pipelines/quant_brief/{test_pipeline,test_interpretation}.py`、`test_reporting.py` 加渲染、`test_report_consistency.py`、`test_market_cycle_review.py` |

> 新指标落点：`src/stock_analytics/pipelines/market_temperature/derived.py` + `market_temperature.yaml` 观察项。

---

## 7. 口径与一致性保证

- 沿用 `investor_brief` 的 `_resolve_latest_common_date` / `_resolve_as_of_date` / manifest `inputs`
  链接；`report_consistency` 同步校验 quant 与上游的基准日 + run_id + 数值一致性。
- 外盘（`external_risk` / `external_pressure`）仅作宏观背景写入，不改写仓位的五档判定——
  除非 `systemic_risk` 本身已降档。
- 所有数值来源为本地产物；行业财报季频滞后、大盘 Top5% 单日横截面等限制在
  `data_quality_notes` 如实披露，不编造。

---

## 8. 待确认项

- [ ] `multi_date` / `make scan` 是否把 `quant_brief` 设为与 `investor_brief` 同级的**必产第四类产物**，还是仅作独立可选产物。
