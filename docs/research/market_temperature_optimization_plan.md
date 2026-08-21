# A 股六维市场温度计优化实现方案

- 状态: 已确认设计，待实现
- 创建日期: 2026-08-20
- 关联产物: `data/analytics/market_temperature/`（as_of=2026-08-19）
- 关联配置: `config/analytics/market_temperature.yaml`
- 关联源码:
  - `src/stock_analytics/pipelines/market_temperature/{scoring,metric_temperature,facts_mart,derived,pipeline}.py`
  - `src/stock_reporting/interpretation/market_temperature/config.py`
  - `src/stock_reporting/templates/market_temperature.py` 与 `temperature/*.md.j2`

---

## 1. 背景与问题

基于 `as_of=2026-08-19` 标准产物审查，当前框架存在三个可观测缺陷：

### 1.1 情绪面不同时间域指标强制混掺（P0）

当前情绪面 51.96 的合成来源（`config/analytics/market_temperature.yaml` 权重 × 实测值）：

| 指标 | 权重 | 实测 | 时间域 |
|---|---:|---:|---|
| turnover_rate_percentile_1250d | 0.40 | 90.07 | 5 年分位（长期活跃水位） |
| advance_share | 0.25 | 8.07 | 当日截面（日频动能） |
| limit_event_temperature | 0.25 | 19.36 | 当日事件（日频动能） |
| investor_account_temperature | 0.10 | 90.70 | 月度（月频慢情绪） |

当日上涨家数仅 8.07%、涨跌停温度 19.36 已是极冷，却被换手 5 年分位 90.07 与月度开户 90.70 加权对冲成"中性 51.96"。这是**同一维度内时间域不同的错误混掺**：分位/月频指标描述"水位高、拥挤度累积"，当日指标描述"当下赚钱效应"，两者正交，不应相加。

### 1.2 跨期驱动变化未结构化（P0）

`pipeline.py:84` 已通过 `_load_comparison` 拿到 `previous_scores`，但 `build_scores` 不接收对比信息，跨期变化只在模板 `_cross_period_change_section` 拼成文字，`report.json` / `scores.json` 无法被下游机器消费。简报、复盘、跨期验证无法复用同一驱动口径。

### 1.3 资金面单点脉冲主导（P0）

`main_money_net_inflow_share` 取单日（实测 -7.09%），`margin_balance_growth_20d` 为单样本单点。资金面评分易被单日脉冲打飞，20 日趋势被压制，与"资金确认是行情质量关键"的定位不符。

### 1.4 facts 无统一 metric_date 列（P3）

`metric_date` 当前藏于事实 note 的 `metric_date=` 字符串，仅模板解析，跨脚本消费存在歧义风险。

---

## 2. 已确认决策

| 决策点 | 结论 |
|---|---|
| 情绪面主温度合成策略 | **动能主导**：主温度由当日动能指标合成；换手 5 年分位归入"活跃水位"观察组、开户归入"慢情绪"观察组，只展示不入主温度 |
| 实现范围 | 本次实现改动 1+2+3+4 全量；本方案即最终实现依据 |
| 兼容性 | `schema_version` 保持 1；新增字段均为增量，缺失时行为与现状一致 |

---

## 3. 改动设计

### 3.1 改动 1：情绪面快/慢拆解（动能主导）

#### 配置层（`config/analytics/market_temperature.yaml`）

情绪面指标分三组，通过指标级新增字段 `subgroup` 标识：

```yaml
sentiment:
  metrics:
    # 动能组（无 subgroup，默认主温度唯一来源）
    - metric_id: advance_share            # weight 0.25
    - metric_id: limit_event_temperature  # weight 0.25
    # 活跃水位组（观察，不入主温度）
    - metric_id: turnover_rate_percentile_1250d
      subgroup: activity                  # weight 0.40 → 仅观察
    - metric_id: market_turnover_rate
      subgroup: activity                  # weight 0.00
    # 慢情绪组（观察，不入主温度）
    - metric_id: investor_account_temperature
      subgroup: slow                      # weight 0.10 → 仅观察
    # 其余 weight=0 指标（limit 系列 / 期权系列 / settlement_iv_proxy）按语义分组：
    #  limit 系列 → 动能组；期权与 settlement 系列 → activity 观察组
```

`subgroup` 允许取值：空（默认，等价 `daily`）、`activity`、`slow`。其他维度指标不改动。

#### 代码层

1. `src/stock_reporting/interpretation/market_temperature/config.py`
   - `MetricInputConfig` 增加 `subgroup: str = ""`，`from_mapping` 解析 `subgroup`。

2. `src/stock_analytics/pipelines/market_temperature/scoring.py`
   - `_dimension_temperature`：只对 `subgroup in ("", "daily")` 的指标合成**主温度**，保留现有 stale 降权、方向映射、缺失指标重归一逻辑。
   - 新增 `_subgroup_temperatures(item, facts)`：对每个非空 `subgroup` 各聚合一个温度（同一 `_dimension_temperature` 内部的加权逻辑复用，抽成共享私有函数）。
   - `_dimension_score` 返回值增加 `"subgroups": {"activity": float|None, "slow": float|None}`。
   - **数据保护回退**：若动能组无任何 `status=ok` 事实（如 limit_list_d 缺失且 advance 缺数），按 `activity → slow → None` 顺序回退为主温度来源，并在 dimension `reason` 与质量报告标注"情绪面主温度已降级为活跃水位/慢情绪口径"。

3. `src/stock_reporting/templates/market_temperature.py`
   - `dimension_interpretations` 的 comment 通过一个 helper 拼接 `subgroups`（存在时附加"动能 X / 活跃水位 Y / 慢情绪 Z"）。
   - `_key_divergence_section` 增加规则：动能温度与活跃水位温差 ≥ 阈值（建议 25）时输出警告，如"高换手低位动能 = 派发/退潮特征"。

4. `temperature/market_temperature_human.md.j2`
   - 在 `## 六维解读` 增加一列或不限列，展示情绪面三个 subgroup 值；模板若无改动显示则通过已有 `fact_sections` 呈现。

#### 行为影响（预期变化）

- 情绪面主温度 `51.96 → 约 13.7`（＝ (8.07 + 19.36)/2，动能双指标等权），综合温度 `51.82 → 约 35-40` 区间。
- 报界面读法："动能主导"下普跌日正确显示冷，活跃水位作为中期拥挤度观察，慢情绪只作开户热度背景。
- 活跃水位 90.1 与动能 13.7 的背离将被显式输出为「派发特征」信号，而非被对冲成中性。

### 3.2 改动 2：跨期 drivers 结构化

#### 代码层

1. `scoring.py::build_scores` 增加参数 `previous_scores: dict[str, Any] | None = None`。
2. 新增 `_build_drivers(current_dimensions, previous_scores)`：
   - 对每维度计算 `delta = current - previous`、`weighted_delta = delta × dimension.weight`（即对综合温度的边际贡献）。
   - 按 `|weighted_delta|` 降序取 top 3，每项带 `direction: warming|cooling`。
   - `composite_delta` 由前后综合温度差给出。
   - 对缺失项（某侧为 None）跳过；全部不可比时返回 `{"status": "insufficient"}`。
3. 返回值写入 `scores.json` 顶层：

```json
{
  "drivers": {
    "status": "ok",
    "comparison_as_of": "2026-08-19",
    "composite_delta": 2.1,
    "summary": "综合温度上升主要由情绪面(+8.5)与资金面(-3.2)迁移驱动",
    "top_contributors": [
      {
        "dimension_id": "sentiment",
        "name": "情绪面",
        "delta": 8.5,
        "weight": 0.15,
        "weighted_delta": 1.27,
        "direction": "warming"
      }
    ]
  }
}
```

   未提供 `previous_scores` 时：`{"drivers": {"status": "no_comparison"}}`。

4. `pipeline.py:104`：`build_scores(config, as_of_date=..., facts=facts, previous_scores=comparison.get("previous_scores") if comparison else None)`。
5. 模板 `_cross_period_change_section` 优先读 `scores["drivers"]` 渲染；absent 或 `status != "ok"` 时回退现有逐维差值逻辑（向后兼容）。

### 3.3 改动 3：资金面脉冲 → 趋势

#### 新事实

- `main_money_net_inflow_share_20d_cum`（20 日累计净流入 / 20 日累计成交额）：
  - 实现位置：`facts_mart.py`（对照现有 `main_money_net_inflow_share` 落盘逻辑，保持同分母口径，`Σ amount` 与 `Σ main net inflow` 均取最新可得的 20 个资金交易日）。
  - 事实 note 附 `metric_date`、窗口起止日期。

#### 温度映射

- `metric_temperature.py::fact_temperature` 增加分支：`main_money_net_inflow_share_20d_cum` 走 `50 + value × 1000`（与单日 share 同刻度）。

#### 配置层

```yaml
fund_flow:
  metrics:
    - metric_id: main_money_net_inflow_share       # 0.20 → 0.10
      weight: 0.10
    - metric_id: main_money_net_inflow_share_20d_cum   # 新增
      weight: 0.10
    - metric_id: margin_balance_growth_20d         # 不变
      weight: 0.20
    - metric_id: margin_balance_growth_60d         # 新增，仅事实展示
      weight: 0.00
```

资金面总入分权重不变（zscore 0.25 + 渗透 0.20 + 增长 0.20 + 单日 0.10 + 累计 0.10 = 0.85）。

#### 数据依赖

- `moneyflow` 不设未经权威资料证明的固定滞后上限：20d 累计基于最新可得资金日期计算；报告仍披露实际资金日期与行情基准日的差异。

### 3.4 改动 4：facts 统一 metric_date 列

- `collect_facts`（`facts.py`）汇总阶段为 `metric_value` 类事实补齐标准列 `metric_date: date`（从各事实来源的 `metric_date`/`latest_evaluation_date` 或 note 解析取值推导）。
- `build_report_json` 的 `fact_summary` 由模板带出 `metric_date`；`report.json` 可直接过滤"截至某资金日期"的事实。
- 模板注释 `_clean_fact_note` 中 `metric_date=` 清理逻辑保留（兼容既有 note 展示）。

---

## 4. 涉及文件清单

| 文件 | 改动类型 |
|---|---|
| `config/analytics/market_temperature.yaml` | 情绪面 subgroup 分组；资金面新增 20d 累计指标与权重重排 |
| `src/stock_reporting/interpretation/market_temperature/config.py` | `MetricInputConfig` 增加 `subgroup` |
| `src/stock_analytics/pipelines/market_temperature/scoring.py` | 主温度 subgroup 过滤、`_subgroup_temperatures`、drivers、回退逻辑 |
| `src/stock_analytics/pipelines/market_temperature/metric_temperature.py` | 新增 20d 累计指标温度映射 |
| `src/stock_analytics/pipelines/market_temperature/facts_mart.py` | 新增 `main_money_net_inflow_share_20d_cum` 派生事实 |
| `src/stock_analytics/pipelines/market_temperature/pipeline.py` | `build_scores` 传 `previous_scores` |
| `src/stock_analytics/pipelines/market_temperature/facts.py` | metrics 统一 `metric_date` 列 |
| `src/stock_reporting/templates/market_temperature.py` | subgroup 呈现、背离规则、drivers 优先渲染、fact_summary metric_date |
| `src/stock_reporting/templates/temperature/market_temperature_human.md.j2` | 情绪面 subgroup 展示 |
| `tests/unit/...` | 见 §5 |

---

## 5. 测试计划

单测（`tests/unit/stock_analytics/pipelines/market_temperature/` 与 `tests/unit/stock_reporting/...` 对应镜像）：

1. `scoring`：
   - 动能主导主温度只取动能组、subgroups 字段正确；
   - 无 subgroup（全空）退化行为与现状一致；
   - 动能组全部缺数时回退 activity / slow / None；
   - `_build_drivers`：有前对比出 top_contributors 与 composite_delta；无前对比返回 `no_comparison`；单侧缺数跳过。
2. `metric_temperature`：`main_money_net_inflow_share_20d_cum` 温度映射（含 clip 边界）。
3. `facts_mart`：20d 累计分母口径与窗口正确性（mock moneyflow）。
4. `facts`：`metric_date` 列存在于 metric_value 事实且为 date 类型。
5. 模板：`_cross_period_change_section` 在 `drivers` 存在时优先消费；absent 时回退。

集成验证：

```bash
make market-temperature DATE=2026-08-19
make market-temperature DATE=2026-08-19 COMPARE_DATE=2026-08-18
make check
```

验收标准：新综合温度显著低于 51.82（动能主导预期）且资金面分不再被单日 -7.09% 单点主导；`scores.json` 同时含 `drivers` 与情绪面 `subgroups`；`quality_report` 无新增硬错误；`make check` 全绿。

---

## 6. 实施顺序

1. 改动 3 数据层（facts_mart 20d 累计 + metric_temperature 映射）——最底层，其余依赖 facts 结构。
2. 改动 1（config subgroup + config.py 字段 + scoring 主温度过滤 + subgroups 回填）。
3. 改动 2（drivers）。
4. 改动 4（metric_date 列）。
5. 模板层（subgroup 呈现、背离规则、drivers 渲染）。
6. 单测 + `make market-temperature` 验证 + 行为对照。

## 7. 风险与限制

- 动能主温度仅入分 advance_share 与 limit_event_temperature 两个指标，样本小、单日易抖动；以回退机制与"动能+活跃水位背离"信号补偿，不额外引入新指标。
- 综合温度语义随动能主导而变化（更接近"当下市场热度"），历史产物不作为同语义对比基线；对比类消费（如 `market-cycle-review`）需同步升级到底层维度温度而非仅总分。
- `subgroups` 与 `drivers` 为新增字段，旧产物读取方不受影响；跨脚本消费新字段前需防 `KeyError`。
