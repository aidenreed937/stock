# 金融工程量化研究标准工作流程（通用 SOP）

> 本文定义本仓库**跨资产、跨研究对象通用**的金融工程量化研究标准工作流程
> （Standard Operating Procedure, SOP）——不仅限于中观行业，也适用于
> **宏观、个股、跨资产配置、市场微观结构**等各类量化研究。
>
> 目标：让每一类量化研究（提出问题 → 数据 → 特征 → 验证 → 组合 → 报告）都走同一套
> 可审计、可回溯、防过拟合、接地事实的标准路径，而不是为每次研究临时拼装 `scripts/*.py`。
>
> 适用范围与本仓库既有文档的边界：
> - `docs/architecture/*`：稳定职责与依赖边界（数据/推导层怎么分）——本文不重复，只引用。
> - `.agents/skills/*/SKILL.md`：各研究域（行业轮动、产业趋势、宏观风控、个股深研……）的
>   **专题操作细则**。本文是**跨研究域的通用骨架**，关系是"骨架 S × 专题规则 T = 具体研究 SOP"。
> - 产业/行业等**中观特有**的深度研究流程，独立成文：
>   [`industry_deep_research_workflow.md`](./industry_deep_research_workflow.md)。
> - 具体公式、字段、产物 Schema、CLI 参数以代码 / YAML / CLI `--help` / 运行产物 Manifest 为准。

---

## 0. 第一条纪律：Ground Truth First

本仓库所有点位、估值、指标必须来自本地 Curated 黄金事实表或已校验的分析产物；
本地缺失必须**披露**，**不得用记忆补造**。外部背景必须标注来源与时效。

对应落地约束（来源 `AGENTS.md`）：

| # | 事实存储与派生层 | 说明 |
| :-- | :-- | :-- |
| 1 | `data/raw/` | API 原始响应分区快照，保留源字段与批次信息 |
| 2 | `data/curated/` | 标准化黄金事实表；日期类型、主键、单位、血统统一；**下游分析/策略唯一事实消费层** |
| 3 | `data/curated/mart/` | 由 Curated 构建的派生 Mart/特征缓存，不替代原始事实 |
| 4 | `data/analytics/` | 分析管线运行目录、Manifest、报告与 `latest` 展示副本 |

> 任何研究一旦发现"想用但本地没有"的数据，第一步不是补造，而是走数据接入 SOP
> （新增 source 到 `stock_data`），再回填、再接入分析。

---

## 1. 工作流程总览：六阶段标准路径

```
┌────────────────────────────────────────────────────────────────────────────┐
│   S0 立题        S1 数据        S2 特征        S3 验证        S4 组合/实盘  S5 报告    │
│  ┌────────┐   ┌────────┐    ┌────────┐    ┌────────┐     ┌────────┐   ┌────────┐   │
│  │命题/口径│→  │接入/构建│→   │特征/候选│→   │有效性   │→    │策略/持仓│→  │结论+留痕│  │
│  │+方法论  │   │+回填   │    │因子     │    │验证     │     │+风控   │   │+归档   │   │
│  └────────┘   └────────┘    └────────┘    └────────┘     └────────┘   └────────┘   │
└────────────────────────────────────────────────────────────────────────────┘
```

| 阶段 | 一句话目标 | 主要落点（代码/配置） | 产物 | 主要验收门禁 |
| :-- | :-- | :-- | :-- | :-- |
| **S0 立题** | 明确"研究什么问题、用什么机制、口径与胜负标准" | 研究方法论文档 + `config/*.yaml` 投研参数 | 命题书/方法论文档 | 机制可证伪；口径可落地；术语分层（特征 vs 因子） |
| **S1 数据** | 让"需要的真实数据"进 Curated | `stock_data/fetcher/*` + `config/data.yaml` | Curated 黄金事实表 | 无前视、代码有测试、外部源 mock、质量门禁过 |
| **S2 特征** | 把事实算成无量纲、可解释的候选特征 | `stock_analytics/pipelines/*` + `config/analytics/*.yaml` | `data/analytics/*` 特征面板 + Manifest | release_date 生效（无前视）、config 驱动、Manifest 完整、落 `latest` |
| **S3 验证** | 确认候选特征是否为有效因子 | `stock_strategy/*` + `config/strategy/*.yaml` | IC / 回测 / 敏感性 / 稳定性产物 | 整体 + 样本外 IC、回测带摩擦、敏感性扫描、跨周期稳定性 |
| **S4 组合/实盘** | 把有效因子组装成可执行策略与风控 | `stock_strategy/*` + CLI | 持仓/报单/风控指令 | T+1 与摩擦、防守门、观察池单一信任源 |
| **S5 报告** | 结论分层留痕、可复核、可回溯 | `stock_reporting/*` / skill 报告脚本 | 研报/日报 + 留痕文档 | 信息分级、来源标注、结论可复核 |

以下各节给出每阶段的标准动作与门禁。具体命令以各 Skill 的 Cheat Sheet 与 `make` 目标为准，
本文不复制专属命令（见 `AGENTS.md`「领域任务」规则）。

---

## 2. S0 立题：命题与口径

**目标**：把模糊想法收敛为"可证伪、可落地、口径唯一"的研究命题。

标准动作：

1. **写方法论文档**（一处一处留痕）：
   - 核心命题：这个研究对象为什么值得单独一套方法（资产/板块/标的的收益分布特征）。
   - 机制假说：驱动收益的因果链。
   - 分层：定位层（在哪）→ 操作层（怎么做），每个动作正交不混职责。
   - **一句法收束**：把方法论压缩成一句话的攻防组合。
2. **定义口径**：研究对象、回测窗口与样本外起点、参数是否允许覆盖。
3. **术语分层（关键约定）**：
   - **特征（feature / 候选因子）**：由基础事实（行情/财务/宏观/产业等）算出的无量纲序列，
     是回测的**输入**，产出在 `stock_analytics` 层；
   - **有效因子（factor）**：只有经 S3 的 IC / 回测 / 敏感性验证确认对收益有稳定预测力后才算，
     确认在 `stock_strategy` 验证层。
   - 文档中"因子 IC +0.24"等是广义用法，与严格"特征→验证→因子"分层不矛盾——**必须声明**。
4. **落地投研配置**：把研究参数（目标、窗口、OOS 起点、验证腿、防守阈值）进 `config/`，
   默认对齐方法论定稿值，不重炒阈值。

**S0 验收**：命题可证伪；口径可落地；术语已分层；参数已进配置（不在代码里硬编码散落）。

**S0 常用 Skill**：`quant-metric-standards`（指标计算与统计标准）、研究域对应 Skill（见第 11 章）。

---

## 3. S1 数据：接入、回填、质量

**目标**：让真实数据以黄金事实表形态进 Curated，供一切下游消费。

标准动作（详见 `data-pipeline` Skill）：

1. **新增数据源**：在 `stock_data/fetcher/<source>/*` 注册 collector + transform；
   无前视关键点——**按 release_date 生效**，避免用未来可得值。
2. **回填（Backfill）**：用 Skill 提供的回填配方覆盖所需历史区间。
3. **增量采集（Sync）**：基于水位/发布时间窗口/RAW 缓存的每日增量。
4. **清洗与质量门禁**：走 `stock_data/governance/quality/*`，跑 domain quality 校验，写审计。
5. **回归到 Curated**：标准化日期类型、主键、单位、血统统一。

**S1 验收**：
- 每个外部数据源在单元测试中 **mock，不依赖真实 Token 或网络**；
- 无前视人工复核（方法论文档声明 release_date 生效）。
- 数据接口/字段以 `data-pipeline` Skill、`config/data.yaml` 与产物 Manifest 为准。

**S1 常用 Skill**：`data-pipeline`、`data-catalog`、`tushare-data`。

---

## 4. S2 特征：从事实到候选特征

**目标**：把 Curated 事实算成无量纲、无前视、config 驱动的候选特征面板。

标准动作（`stock_analytics/pipelines/<domain>/*`，`<domain>` = 研究域，如
macro / equity / industry / cross_asset）：

1. **配置驱动**：特征定义（源 column、滚动窗口、合成方式）进
   `config/analytics/<domain>.yaml`。
2. **无前视**：全部按 `release_date` 生效、日频前向填充。
3. **无量纲化**：0-100 滚动历史分位、z-score 等标准化手段（参考 `quant-metric-standards` 的
   分位选型与去体量通胀）。
4. **ArtifactStore 落盘**：结果写 `data/analytics/<domain>/`（run 目录 + `latest`），
   写完整 **Manifest**（完整性 + watermark + provenance + inputs/parents + data_completeness）。
5. **产物读取**：消费者统一经 `DataCatalog` / 产物门面读，不直接拼路径。

**S2 验收**：
- `data/analytics/<domain>/latest/` 存在 manifest + 面板 parquet；
- Manifest 含 provenance（git_commit/config_sha256）、watermarks、data_completeness；
- 特征面板 schema 稳定、列名可验收；
- 本层不动策略逻辑（依赖方向见 `docs/architecture/analytics-boundaries.md`）。

**S2 常用 Skill**：`quant-metric-standards`、研究域对应 Skill 的因子定义。

---

## 5. S3 验证：候选特征 → 有效因子

**目标**：用严格统计与回测确认一个特征"是否真有效，且跨周期稳定、不过拟合"。

这是**防过拟合的核心阶段**，标准四件套（`stock_strategy/<domain>/*` + `config/strategy/*.yaml`）：

1. **IC 验证**：整体 + 年度 + 当前截面，前瞻收益（`ic_min_samples` 控制最小样本）。
2. **事件状态机回测**：多个策略变体对比，**带 T+1 与摩擦成本**（佣金 + 滑点 + 调仓死区）。
3. **敏感性扫描**：对关键参数（如阈值、权重）做扫描，确认结论不是"卡点凑出来的"。
4. **稳定性/样本外**：样本外（OOS）表现、跨周期稳定性、主要回撤段的防守有效性审计。

防过拟合护栏（研究域方法论的「执行纪律」通用版）：
- 阈值定稿后**不重炒**；改动属于研究参数，需显式记录。
- 声明**证据等级分层**（已验证事实 / 机制推断 / 外部背景），失效机制要如实标注。
- **不把本地缺失的信息补造**；不宣称无依据的前瞻性。

**S3 验收**：
- IC（整体 + 年度 + 当前截面）留档；样本外 IC 与回测指标（CAGR/夏普/最大回撤）齐全；
- 敏感性扫描产物存在（可追溯参数是否被微调过）；
- 结论落到 `data/strategy/<domain>/`。

**S3 常用 Skill**：`quant-metric-standards`、`macro-risk-research`（跨周期回测/胜率）、
研究域对应 Skill（多策略资金曲线对比）。

---

## 6. S4 组合 / 实盘

**目标**：把已验证因子组装成可执行策略与风控指令。

标准动作：

1. **观察池单一信任源**：研究对象（个股/指数/ETF/行业等）由
   `config/universe/watchlist.yaml` 集中管理；CLI 传 `SYMBOL=watchlist` 时按配置路由和截断。
2. **防守门**：拥挤度/估值/回撤等一票否决或减仓信号，作为组合层面的风控闸门。
3. **执行纪律**：信号当日收盘生成、次日开盘执行（T+1）；对标物缺失时用代理并**透明披露偏差**。
4. **盘尾/巡检**：离线推演报单卡片，dry-run 再实盘。

**S4 验收**：持仓/报单/风控指令可离线复现；防守门生效；映射关系透明。

**S4 常用 Skill**：`macro-risk-research`（仓位建议）、`daily-market-review`（每日复盘）、
研究域对应 Skill（盘尾拟定调仓）。

---

## 7. S5 报告 / 归档

**目标**：把研究结论分层留痕、可复核、可回溯。

标准动作：

1. **信息分级**：报告区分已验证事实、机制推断、外部背景。
2. **来源标注**：公式/口径不确定时先查代码配置、权威依据、测试；外部背景标来源与时效。
3. **产物归档**：研究文档进 `docs/research/`（按研究域分子目录，如 `docs/research/<domain>/NN_*.md`），
   配套 Markdown 报告 + 留痕（回测表、敏感性表）。
4. **方法论更新**：收束成"一句话方法论"回写 Skill 参考文档，沉淀为可执行的交易方法论。

**S5 验收**：结论可复核（有好文档/报告支撑）；信息分级清晰；研究产物归档；方法论已沉淀。

**S5 常用 Skill**：`stock-deep-research`（个股投研报告）、`macro-risk-research`（日报）/
`daily-market-review`、研究域对应 Skill。

---

## 8. 质量、测试与提交流程

每个研究产物在进入 Git / 上报前，执行 `AGENTS.md` 与仓库 Makefile 的门禁：

```bash
make lint            # Ruff、mypy、类规模与导入边界
make test            # 全量 pytest 与覆盖率门禁（>75%）
make test TEST_PATH=tests/unit/...   # 受影响范围定向测试（改动小时优先）
make check           # format + lint + Rust 检查 + test 全流程
```

编码要求（详见 `AGENTS.md` / `CLAUDE.md`）：
- 4 空格缩进；YAML/Markdown 2 空格；LF；Ruff 行宽 100。
- 测试 `test_<behavior>`；外部数据源必须 mock。
- 不自动 commit/push；提交用 Conventional Commits。

---

## 9. 研究落地 Checklist（一份对应一类研究）

开展任何新研究时，用此清单自查六阶段是否闭环：

- [ ] **S0** 立题：有方法论文档；口径唯一；术语已分层（特征 vs 因子）；参数进 `config/`。
- [ ] **S1** 数据：所需真实数据进 Curated；无前视；外部源 mock 有测试。
- [ ] **S2** 特征：`stock_analytics/pipelines/<domain>` 配置驱动；无量纲化；release_date 生效；
      `data/analytics/<domain>/latest/` 有 manifest（provenance/watermark/completeness）。
- [ ] **S3** 验证：IC（整体+年度+截面）+ 回测（带摩擦/T+1）+ 敏感性 + 稳定性 四件套齐全；
      结论到 `data/strategy/<domain>/`。
- [ ] **S4** 组合/实盘：观察池走 watchlist；防守门生效；T+1 执行纪律；映射透明。
- [ ] **S5** 报告：信息分级；来源标注；`docs/research/<domain>/` 归档；方法论沉淀回 Skill。
- [ ] 门禁：`make lint` / `make test` 通过（受影响范围至少）。

> **研究域专项符合性审计**：某条研究线对照本 SOP 的逐项评估与收口建议，独立成文于
> `docs/research/<domain>/sop_gap_assessment.md`（例如半导体见
> `docs/research/semiconductor/sop_gap_assessment.md`）。本通用文档不内嵌任何单一研究域的检查清单。

---

## 10. 研究域专题规则（骨架 × 专题）

本仓库已有的研究域专题规则，作为"骨架 S × 专题 T"的具体实例：

| 研究域 | 专题 SOP | 说明 |
| :-- | :-- | :-- |
| 中观产业深研 | [`industry_deep_research_workflow.md`](./industry_deep_research_workflow.md) | 供需剪刀差、产业腿、深研线簇、配置评级等中观特有流程 |
| 宏观风控 | `macro-risk-research` Skill | 双轨雷达、8 维风控画像、宏观范式定位 |
| 行业轮动 | `industry-rotation-strategy` Skill | 5 大中观因子、多策略回测、盘尾报单 |
| 个股深研 | `stock-deep-research` Skill | 个股全景体检、Bull/Base/Bear 情景推演 |
| 产业趋势跟踪 | `industry-trend-tracking` Skill | 全球方向共振、剪刀差 LONG、拐点预警 |

> 每个新研究域落地时：先写方法论文档（S0）→ 进 Skill（专题 T）→ 对照本骨架自查闭环
> → 在 `docs/research/<domain>/` 归档。

---

## 附注

- 本文是**跨研究域通用骨架**；各研究域的专属命令、公式口径以对应 Skill 与代码为准，不在本文重复。
- 研究开始前，先读对应研究域 Skill 的 SKILL.md；落地本 SOP 时以第 9 章 Checklist 自查。
- 中观**产业深度研究**的专用流程见 `industry_deep_research_workflow.md`。
