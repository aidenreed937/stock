# 个股排雷 (Stock Screening/Vetting) 实现方案

- 状态: 已确认设计，待实现
- 创建日期: 2026-08-21
- 关联产物（规划）: `data/analytics/stock_screen/`
- 关联配置（规划）: `config/analytics/stock_screen.yaml`
- 关联源码（规划）:
  - `src/stock_analytics/pipelines/stock_screen/{sources,rules,pipeline,artifacts}.py`
  - `src/stock_reporting/templates/stock_screen.py`
  - `src/stock_cli/stock_screen.py`

---

## 1. 背景与定位

个股排雷（Stock Vetting）是选股/行业轮动的**第一道闸门**（硬过滤），必须在评分与排序之前执行：

```
全市场 5,000+ 只 A 股
   │
   ▼
【闸门 0】市场环境闸门 (quant_brief 四道风控闸门，已实现，只读准入)
   │  通过
   ▼
【闸门 1】个股排雷 (本方案) ──► 硬性剔除 (excluded) / 黄牌预警 (warned) / 通过 (passed)
   │  通过名单 passed.csv
   ▼
【闸门 2】选股 / 行业轮动打分 (打分仅在通过名单内进行)
```

核心原则：**宁可误杀，不可错放**。任何雷点必须能追溯到本地真实的 Curated 黄金表字段，**严禁凭模型记忆或外部叙事编造**（遵循 Ground Truth First 与三层信息分级）。

关键决策：排雷输出是**每日/指定日期全市场快照**，与 `industry_structure` 同为同类产物，只读 Curated 数据，不新增数据源、不写回存储层。

---

## 2. 排雷维度总表（数据可用性已实测验证）

### 2.1 硬性剔除（一票否决，命中任一直接排除，无分数可谈）

| # | 排雷点 | 数据字段 | 本地可用性 | 实测覆盖（2025-08-01 ~ 2026-08-20 窗口） |
|---|---|---:|---|---|
| 1 | ST / *ST / 退市整理期 | `stock_basic.name` 正则 `ST *ST 退` | ✅ | 全市场 5,544 只；当前 ST/*ST 207 只 |
| 2 | 次新股未满观察期（默认 180 天） | `stock_basic.list_date` | ✅ | 全市场，`list_date` 无缺失 |
| 3 | 低价股 / 面值退市风险（默认 <2 元） | `daily_basic.close` | ✅ | 全市场，2013 至今 |
| 4 | 日成交额流动性枯竭（默认 <5000 万） | **`stock_daily_bar.amount`**（元） | ✅ | 全市场，2013 至今（`daily_basic` **无 amount 字段**，已在实测中纠正） |
| 5 | 连续亏损（默认近 2 年中报净利润为负） | `income.n_income` / `fina_indicator.netprofit_yoy` | ✅ | `income` 5,829 只、`fina_indicator` 6,789 只 |
| 6 | 净资产为负 | `balancesheet.total_hldr_eqy_exc_min_int` | ✅ | `balancesheet` 5,834 只 |
| 7 | 商誉暴雷（商誉 / 净资产 > 50%） | `balancesheet.goodwill` | ✅ | 同上，`goodwill` 字段实测存在 |
| 8 | 长期停牌 / 当日无交易 | `suspend_d`、`stock_daily_bar` 当日缺行 | ✅ | `suspend_d` 538 只 / 3,964 行 |

### 2.2 黄牌预警（不剔除，但标记并累计，N 黄牌可升级为临时排除）

> 下表"实测覆盖"均基于 **2025-08-01 ~ 2026-08-20 半年窗口**逐数据集实跑确认。**排雷处理基准始终为全市场**：`enabled: true` 的规则对全市场标的可评估则评估，某标的数据缺失不判该规则（降级观察）；`scope` 限定标的子集（如北向）的规则只对该子集评估。覆盖率与全市场预期存在差距的数据集，规则仍按全市场口径声明，但通过 `enabled: false` 显式关闭，见 §3.2。

| # | 排雷点 | 数据字段 | 实测覆盖 | 结论 |
|---|---|---:|---:|---|
| 1 | 业绩预告大亏（PIT 幅度默认 <-50%） | `forecast.p_change_min/p_change_max`（`ann_date` 生效，禁用前向填充） | 3,552 只 / 5,450 行 | ✅ 仅覆盖预告披露公司（正常，可作存在性黄牌） |
| 2 | 营收与经营现金流长期背离 | `fina_indicator.q_ocf_to_sales`、`netprofit_margin` | 6,789 只 | ✅ 全市场 |
| 3 | 大股东/董监高持续减持（默认半年 ≥3 笔） | `stk_holdertrade`（`in_de` 值域 **`DE`/`IN`**，非 `D`；日期用 `begin_date`/`close_date`） | 2,882 只 / 13,449 行 | ✅ 覆盖多数减持股（事件型，正常） |
| 4 | 股权质押比例过高（默认 >70%） | `lixinger/pledge_info` | **仅 6 只 / 6 行** | ⚠️ **不可用**：近半年仅落盘 6 只，疑似仅补充性快照，无法支撑全市场规则 |
| 5 | 北向持仓 20 日骤降（默认降幅 >20%） | `tushare/hk_hold` | 981 只 / 32,424 行，日期 2025-09-30 起 | ✅ 覆盖北向标的物（沪股通+深股通约 1,000+），可对北向标的执行 |
| 6 | 两融余额异常骤降（杠杆踩踏） | `tushare/margin_detail` | **仅 7 只**（watchlist A 股） | ⚠️ **不可用**：仅自选池标的，非全市场，无法支撑全市场排雷 |
| 7 | 连续跌停 / 异常封板事件 | `tushare/limit_list_d` | 4,117 只 / 27,912 行 | ✅ 全市场 |
| 8 | 大宗交易折价出货 | `tushare/block_trade` | 2,083 只 / 9,794 行 | ✅ 事件型，覆盖大宗活跃股 |

### 2.3 无法本地覆盖（如实标注，禁止硬造）

| 排雷点 | 原因 | 处理 |
|---|---|---|
| 审计意见（非标 / 持续经营存疑） | `income/balancesheet` 为 TuShare 顶栏数据，无审计意见字段；理杏仁私有财报未接入本排雷链路 | 产物 `missing_gates` 与质量报告如实披露 "not_supported" |
| 违规处罚 / 立案调查 / 重大诉讼 | 本地无对应数据集 | 同上 |
| 限售解禁明细 | 本地无 `share_float` 等解禁表（已实测确认缺失） | 同上 |
| **两融个股明细（marging_detail）全市场** | 本地仅落盘 watchlist 7 只 A 股的半年明细 | 规则降级为"仅自选池快照"观察项，不做全市场硬规则 |

> 原则：**数据缺失不得导致误排雷**。财报类规则（连续亏损、商誉、净资产）在最近一期财报缺失时，降级为黄牌观察而非硬性剔除；质押/两融/解禁等覆盖不足的规则默认关闭，待数据补齐后再启用，并在 `manifest.data_gaps` 记录。

---

## 3. 系统设计

### 3.1 模块结构（完全对齐 `industry_structure` 范式）

```
src/stock_analytics/pipelines/stock_screen/
  __init__.py
  sources.py          # DataCatalog 按 as_of 精确加载各数据集（分区裁剪 + 列投影）
  rules.py            # 排雷引擎：硬剔除 + 黄牌预警纯函数，返回逐股 reasons
  decision.py         # 规则结果合并 → excluded / warned / passed 三路决策
  pipeline.py         # run_stock_screen(): 编排、质量报告、产物写入
  artifacts.py        # StockScreenRunPaths / StockScreenArtifactPayload / write_artifacts
src/stock_reporting/templates/stock_screen.py   # 报告渲染（Markdown + JSON）
src/stock_cli/stock_screen.py                   # CLI 入口 -m stock_cli.stock_screen
config/analytics/stock_screen.yaml              # 阈值配置（零硬编码）
Makefile                                        # 新增 screen-stocks 目标
tests/unit/stock_analytics/pipelines/stock_screen/
  test_rules.py
  test_pipeline.py
  test_artifacts.py
  test_reporting.py
```

### 3.2 配置设计（`config/analytics/stock_screen.yaml`）

规则统一为**结构化列表 + `enabled` 开关**。每个规则显式声明 `enabled`、`scope`（标的范围）与 `note`（数据缺口说明），默认关闭的规则以 `enabled: false` 声明为**数据缺口关闭**，而不是隐含在代码里。**排雷始终以全市场为处理基准**：`enabled` 规则对所有标的可评估则评估；某标的数据缺失不判该规则（降级观察），不因缺失误排雷。

```yaml
stock_screen:
  schema_version: 1
  title: "个股排雷（全市场硬性剔除与黄牌预警）"
  artifact_root: "data/analytics/stock_screen"
  as_of: null                # 默认取最新已落盘交易日
  symbols: []                # 空 = 全市场（默认）；可传 watchlist 限定范围调试

  # ---- 硬性剔除（一票否决，全市场）----
  hard_exclusion:
    rules:
      - id: st_marked
        enabled: true
        scope: all_market
        params:
          name_regex: "ST|\\*ST|退"
        note: "stock_basic.name 正则可识别 ST/*ST/退市整理"
      - id: too_new_listing
        enabled: true
        scope: all_market
        params:
          min_list_days: 180
        note: "stock_basic.list_date 距 as_of 不足 180 天"
      - id: penny_stock_face_value
        enabled: true
        scope: all_market
        params:
          min_close_price: 2.0            # 元；逼近 1 元面值退市线
        note: "daily_basic.close"
      - id: illiquid_float
        enabled: true
        scope: all_market
        params:
          min_daily_amount_yuan: 50_000_000.0   # 日成交额 < 5000 万元
        note: "stock_daily_bar.amount（daily_basic 无 amount 字段）"
      - id: consecutive_losses
        enabled: true
        scope: all_market
        params:
          loss_years: 2                  # 近 2 年报净利润为负
          report_lag_days: 120           # 财报缺失超容忍 → 降级观察
        note: "income.n_income / fina_indicator 按 ann_date<=as_of 取最新"
      - id: negative_equity
        enabled: true
        scope: all_market
        params:
          min_total_equity: 0.0          # 净资产为负
        note: "balancesheet.total_hldr_eqy_exc_min_int"
      - id: goodwill_overhang
        enabled: true
        scope: all_market
        params:
          max_goodwill_to_equity: 0.50   # 商誉/净资产 > 50% 硬剔除
        note: "balancesheet.goodwill / total_hldr_eqy_exc_min_int"
      - id: suspended
        enabled: true
        scope: all_market
        params:
          require_trade_on_as_of: true   # 当日无交易/停牌
        note: "stock_daily_bar 当日缺行 / suspend_d"

  # ---- 黄牌预警（标记不剔除，N 黄牌可升级）----
  yellow_warn:
    rules:
      - id: forecast_plunge
        enabled: true
        scope: all_market
        params:
          p_change_min_threshold: -50.0     # 业绩预告下修幅度 %
        note: "forecast 按 ann_date PIT 生效；仅覆盖披露预告公司"
      - id: holder_selloff
        enabled: true
        scope: all_market
        params:
          window_days: 180
          min_sell_count: 3                  # 半年内减持笔数
        note: "stk_holdertrade in_de=DE，按 begin_date/close_date 计数"
      - id: goodwill_observe
        enabled: true
        scope: all_market
        params:
          observe_ratio: 0.30                # 商誉/净资产 > 30% 黄牌观察
        note: "低于 0.50 硬剔除线，仅观察"
      - id: northbound_drawdown
        enabled: true
        scope: northbound                  # 仅北向标的（hk_hold 覆盖约 981 只）
        params:
          window_days: 20
          drop_threshold: -0.20
        note: "hk_hold 持仓 20 日降幅 > 20%"
      - id: consecutive_limit_down
        enabled: true
        scope: all_market
        params:
          min_consecutive_count: 2
        note: "limit_list_d 连续跌停"
      # ---- 以下默认关闭：实测覆盖不足，数据补齐后再启用；scope 预留全市场口径 ----
      - id: margin_stress
        enabled: false
        scope: all_market                  # 预期全市场口径
        params:
          window_days: 20
          drop_threshold: -0.30
        note: "margin_detail 当前仅覆盖 watchlist 7 只，无法执行全市场排雷"
      - id: pledge_overhang
        enabled: false
        scope: all_market                  # 预期全市场口径
        params:
          max_pledge_ratio: 0.70
        note: "lixinger/pledge_info 仅 6 只快照，数据不足"
      - id: block_trade_discount
        enabled: false
        scope: all_market                  # 预期全市场口径
        params:
          max_discount: -0.10
        note: "block_trade 事件型，第二期接入"

  output:
    top_passed: 100            # passed 清单默认留头部候选数（供选股消费）
    max_warn_rows: 500         # 黄牌清单默认展示上限

  datasets:                   # 与 industry_structure config 相同的 schema 规范
    # 核心（全市场，已实测）：stock_basic, stock_daily_bar, daily_basic,
    #       income, balancesheet, fina_indicator, forecast, express, suspend_d, limit_list_d
    # 确认-事件型：stk_holdertrade (in_de DE/IN, begin_date/close_date), block_trade(第二期)
    # 确认-标的子集：hk_hold（北向标的约 981 只，scope=northbound）
    # 不足默认关闭：margin_detail（仅 watchlist）、lixinger/pledge_info（仅 6 只快照）
    # 缺口 not_supported：审计意见、违规/诉讼、限售解禁、share_float
```

### 3.3 规则引擎设计（`rules.py`）

- 每个排雷点 = 一个**纯函数** `evaluate_<rule>(rows: pl.DataFrame, params) -> pl.DataFrame`，入参一次加载好的数据集，输出带 `{rule_id}: {pass/warn/fail}` 与 reason 文本的追加列。
- 规则由 YAML 驱动注册：`id / enabled / scope / params / note`。`enabled: false` 的规则不注册执行，只在 `missing_gates` 记录"数据缺口关闭"；`scope` 限定标的范围（`all_market` 默认 / `northbound` 等子集），**处理基准始终是全市场**，子集规则只对该子集评估、其余标的跳过。
- 决策合并（`decision.py`）：任何 `fail` → excluded；`warn` 计数 ≥ 3 → 升级为临时排除（列入 excluded 且理由注明升级路径）；其余 → passed。
- 输出列契约（所有输出表统一 schema）：

```
symbol   name   industry   list_date   market
reasons  rule_ids        # 命中的规则 id 列表（合并去重）
level    # excluded / warned / passed
note     # 规则判定依据的一句话（含数据日期、字段值），保证可溯源
```

### 3.4 产物结构（对齐 industry_structure runs/latest）

```
data/analytics/stock_screen/
  runs/as_of=YYYY-MM-DD/run_<timestamp>/
    manifest.json
    excluded.csv        # 硬性剔除清单（含多原因）
    warned.csv          # 黄牌预警清单
    passed.csv          # 通过名单（供选股/轮动消费）
    scores.json         # 决策摘要（剔除统计、warn 升级、缺失门禁）
    screen_report.md
    screen_report.json
    quality_report.md / quality_report.json
  latest/
    manifest.json
    excluded.csv / warned.csv / passed.csv / screen_report.md ...
```

### 3.5 数据一致性与质量披露

- **时滞对齐**：所有日频数据集先 `cat.get_latest_trade_date()` 取交集基准日，多表 Join 前对齐，杜绝跨日错位。
- **PIT 纪律**：`forecast`/`express`/业绩类规则一律以 `ann_date` 生效，禁止 FFill 造成前瞻偏差；`balance_sheet`/`fina_indicator` 取 `ann_date <= as_of` 的最新一期。
- **金额单位**：Curated 层已统一为元，一律除以 `1e8` 展示为亿元，严禁按数据源额外换算。
- **统计口径披露**：`screen_report.json` 输出 `population_size / excluded_count / warned_count / passed_count / data_gaps / rule_version`。
- **禁止通配符**：数据加载统一走 `DataCatalog.load_dataset()`，必须指定 `start_date / end_date / symbols / columns`，利用 Hive 年月分区裁剪。

---

## 4. 实现范围与里程碑

### 第一期（最小闭环，本方案即第一期实现依据）

1. **硬性剔除 8 条**全部落地（§2.1 表格 1-8，全部有全市场实测覆盖支撑）。
2. 黄牌预警先落 5 条（全部有实测覆盖支撑）：业绩预告大亏、大股东减持、商誉占净资产观察、北向持仓骤降、连续跌停。
3. **显式关闭 2 条**（实测覆盖不足，`enabled: false` 声明为数据缺口关闭，不阻塞运行）：两融个股明细（`margin_detail` 仅 watchlist 7 只）、股权质押（`pledge_info` 仅 6 只）。限售解禁等无对应数据集的排雷点以 `not_supported` 如实披露。
4. 单依赖管道跑通**全市场一个 as_of 日期**，产出 excluded/warned/passed + 质量报告。
5. CLI（`-m stock_cli.stock_screen --as-of YYYY-MM-DD`）+ Makefile `screen-stocks` 目标。
6. 报告模板：仅 Markdown + JSON 摘要，图表化留第二期。
7. 测试覆盖：单测不留死角（ST 正则、边界阈值、缺失降级、多头寸合并），跑 `make check`。

### 第二期（能力增强，不在本方案第一批实现范围）

- 补全黄牌预警：大宗折价出货、现金流/净利背离等。
- 累计 N 黄牌升级临时排除的自动化与复权说明。
- 与 `quant_brief` / `industry_structure` 联动：`passed.csv` 作为选股/轮动 pipeline 的标准输入。
- `symbols=watchlist` 白名单快照模式。
- 待数据补齐后启用关闭规则（两融/质押）。
- 补充审计意见 / 违规处罚 / 限售解禁等外部数据源。

### 3.6 关键实现注意（实测纠偏，实现时必须按真实字段）

| 方案初稿 | 实测真相 | 实现要求 |
|---|---|---|
| `daily_basic.amount` | `daily_basic` 无 amount；日成交额在 `stock_daily_bar.amount` | 流动性规则改读 `stock_daily_bar` |
| `stk_holdertrade.in_de='D'` | 值域为 `DE`（减持）/ `IN`（增持） | 用 `in_de=='DE'` 计数，区间用 `begin_date`/`close_date` |
| `stk_holdertrade.end_date` | 无 `end_date` 字段 | 改用 `begin_date`/`ann_date` |
| `margin_detail` 全市场 | 仅 watchlist 7 只半年明细 | 规则默认关闭，绝不冒充全市场 |
| `lixinger/pledge_info` 全市场 | 仅 6 只快照 | 规则默认关闭，待补齐 |
| 限售解禁可查 | 本地无解禁表 | 如实披露 not_supported |

---

## 5. 测试与质量门禁

- `tests/unit/stock_analytics/pipelines/stock_screen/`：
  - `test_rules.py`：每规则用最小 fixture 验证 pass/fail 边界（如 `min_close_price = 2.0` 时 1.99 剔除、2.00 通过；ST 正则大小写/带后缀）。
  - `test_pipeline.py`：mock 切面加载器，验证三路决策、无数据时 not_supported、as_of 必填校验。
  - `test_artifacts.py`：产物结构、latest 覆盖、manifest 关键字段。
  - `test_reporting.py`：渲染出 Markdown 含剔除统计表与数据缺口披露。
- 提交前 `make check`（format + lint + 覆盖率 ≥ 75%）。
- 真实数据冒烟：跑一次全市场 as_of 快照，人工核对排除数量级合理（ST≈200 量级、次新≈150、商誉/流动性尾部），数值可由黄金表字段复算。
