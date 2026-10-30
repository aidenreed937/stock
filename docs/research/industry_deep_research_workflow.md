# 中观产业深度研究标准工作流程（产业深研 SOP）

> 本文是**中观产业深度研究（industry deep research）**的专题 SOP，是通用量化研究骨架
> （[`quantitative_research_workflow.md`](./quantitative_research_workflow.md)）在
> **中观产业**研究域的具体展开，即"骨架 S × 产业专题规则 T_industry = 产业深研 SOP"。
>
> 适用于：对某个行业/板块（白酒、食品饮料、电力设备/新能源、半导体/电子、医药生物、
> 煤炭、化工、光伏等）做**供需周期、估值分位、产业链上下游传导、龙头梯队、行业配置评级**、
> 以及**产业趋势跟踪与轮动**的量化深度研究。
>
> 边界：
> - 通用六阶段（S0 立题 / S1 数据 / S2 特征 / S3 验证 / S4 组合 / S5 报告）与 Ground Truth
>   First 纪律见通用文档，本文不重复。
> - 各产业的**专项实证**与符合性审计独立成文：如
>   `docs/research/semiconductor/sop_gap_assessment.md`、`docs/research/photovoltaic/` 分篇。

---

## 1. 产业深研与通用骨架的关系

| 通用阶段 | 产业深研的落点 | 中观特有内容 |
| :-- | :-- | :-- |
| S0 立题 | 产业研究方法论：核心命题（周期/成长属性） | 供需周期定位、剪刀差机制假说、一句法攻防收束 |
| S1 数据 | 产业数据腿接入（见 `data-pipeline`） | 实物流量数据（TSMC/SIA/SEAJ/装机/出货/批价/渠道库存等），release_date 生效 |
| S2 特征 | 产业特征面板（`pipelines/<industry>/*`） | 供需剪刀差、产业数据腿、5 大中观因子、0-100 滚动分位 |
| S3 验证 | 产业因子验证（IC/回测/敏感性/稳定性） | 11 年跨周期多策略回测、跨周期稳定性审计、防退化 CI 门禁 |
| S4 组合 | 行业配置评级 → ETF/成分股执行 | 深研线簇选行业、动量 Top3 兜底、防守门、盘尾报单 |
| S5 报告 | 产业深研报告 + 归档 | 中观产业研报模板、`docs/research/<industry>/` 分篇 |

---

## 2. 产业研究方法论（S0）

产业深研的立题遵循通用 S0，但内容偏中观：

1. **核心命题**：这个行业为什么值得单独一套方法——**周期成长属性**（如半导体成长期权、
   白酒消费属性、光伏周期成长），收益分布特征与年度摆动幅度。
2. **机制假说**：驱动产业收益的因果链，典型如
   - 供需剪刀差：`需求 − 供给`（需求腿如台积电营收/SIA 销售额，供给腿如 SEAJ 设备出货）；
   - 全球资本开支方向 × A 股供应链承接（全球共振）。
3. **分层**：定位层（在哪）→ 操作层（怎么做），每个动作**正交不混职责**。
4. **一句法收束**：把方法论压成一句话的攻防组合（如"防守门保回撤 + 进攻脚博增长"）。
5. **术语分层**：产业数据算出的 0-100 分位是**特征（feature）**，经验证有预测力才叫
   **有效因子（factor）**——沿用通用约定，文档里"剪刀差因子 IC"是广义用法，需声明。

### 2.1 跨行业可迁移纪律（光伏 630500 实证反哺）

以下三条由光伏深研（`docs/research/photovoltaic/` 00-13 + `core_proposition.md`）验证、**跨行业通用**，
新行业深研立项/验收时照做，不必重新踩坑：

1. **信号尺度由供给弹性决定**：高壁垒、难扩产行业（半导体）fwd60 可跟踪；低壁垒、易扩产、
   周期被拉长的行业（光伏）须用 `fwd2q/4q` 季度尺度。立项先定供弹→定信号尺度，再做因子，避免在错误尺度上白做。
2. **供给侧腿须过"跨周期稳定性验收"，不只看当期 IC**：候选腿样本外 2022+ 是否逐年符号漂移即淘汰
   （正负交替、跨 ±0.4 = 不可用），符合同号且方向稳定才可接；样本外塌向噪声（IC→0）同样作废。
   供给侧观测即使全周期高 IC 也无前瞻可接时，只作"谁先见底"的定性解释 / 拐点预警，**不纳入择时**。
3. **结论"诚实定位"纪律**：防守门/减亏变体样本外仍负，就是**减亏工具而非正收益引擎**，必须如实标注、
   不得隐去；单次产能循环实现（n=1 下行周期）未验证可重复前，一律作〔B〕不宣称可重复。

> 这三条是"方法论"（跨行业可迁移的验收铁律）而非"光伏结论"（哪些腿证伪、防守形态最优）；
> 后者留在 `docs/research/photovoltaic/` 实例，不回灌 SOP 以免把个案当通用。

---

## 3. 产业数据腿（S1 中观落点）

产业深研依赖**实物流量数据**（非仅行情/财务），全部按 `release_date` 生效、无前视：

| 类型 | 示例 | 领先性 |
| :-- | :-- | :-- |
| 需求腿 | 台积电月营收（领先）、SIA 全球销售额（同步，官方 3MMA） | 领先/同步 |
| 供给腿 | SEAJ 日本制设备出货（领先 1-2 年产能释放）、产能利用率 | 领先 |
| 结构性腿 | AI CapEx（云厂商季度）、DXI 存储指数月度同比 | 领先 |
| 价格/库存腿 | 批价、现货报价、渠道库存、DOI | 同步/滞后 |
| 财报滞后验证 | 量价齐升（营收+净利双正）、毛利率扩张 | **滞后，仅事后确认** |

> 产业供需数据作**前瞻确认**；财报层（量价齐升/毛利率扩张）**仅作滞后事后验证**，
> 不作前瞻选股。这是产业深研的纪律（详见 `industry-trend-tracking` Skill）。

新增产业数据源走通用 S1 流程：`stock_data/fetcher/industry/<name>/*`（collector + transform）
+ 回填 + 每日 Sync + 质量门禁 + 单测 mock。

---

## 4. 产业特征（S2 中观落点）

产业特征面板在 `stock_analytics/pipelines/<industry>/*`（config/pipeline/legs），config 驱动：

- **供需剪刀差**：`demand_score − supply_score`（各腿 0-100 滚动分位后合成）。
- **产业数据腿**：需求/供给/结构性/价格库存等独立分组，`leg_type` 区分，不入剪刀差。
- **5 大中观因子**（行业轮动用）：景气动量 / 供需剪刀差 / 拥挤过热 / 估值赔率 / 聪明资金流。
- **0-100 滚动分位**：去体量通胀，跨行业可比较（参考 `quant-metric-standards`）。

产物落 `data/analytics/<industry>/latest/`（manifest + parquet），通用 S2 验收全部适用。

配置参考：`config/analytics/semiconductor_legs.yaml`（供需剪刀差 + 结构性确认腿）、
`config/analytics/industry_*.yaml`（中观因子）。

---

## 5. 产业因子验证（S3 中观落点）

产业因子的有效性验证在 `stock_strategy/industry/*`，通用 S3 四件套基础上叠加产业特有：

1. **IC 验证**：整体 + 年度 + 当前截面，f60 前瞻收益。
2. **事件状态机回测**：多策略变体（纯动量 / 反拥挤逆向 / 供需剪刀差 / 宏观相态元路由），
   带 T+1 与摩擦成本。
3. **跨周期稳定性审计**：**11 年（2015-2026）跨周期 6 大宏观范式**回测检验，
   防退化 CI 门禁（`stock_cli.industry_strategy_audit --assert-guardrails`）。
4. **防守门与敏感性**：拥挤度一票否决、DOI 阈值 / 降仓权重敏感性扫描、主要回撤段防守审计。

产物落 `data/strategy/<industry>/`（参考 `data/strategy/semiconductor/`）。

---

## 6. 产业组合 / 实盘（S4 中观落点）

- **深研线簇选行业**：有产业供需腿的行业用剪刀差 LONG + DOI 激活（自带择时）；
  无腿行业用动量 Top3 兜底 + 估值/组合防守门。
- **行业配置评级**：超配 / 标配 / 低配（`stock_cli.industry_diagnose`）。
- **ETF 映射执行**：申万二级行业 → 场内 ETF（纯二级对标优先，主题/一级 ETF 代理透明披露偏差）。
- **盘尾调仓**：14:50 盘尾实盘推演 + 报单卡片（dry-run 再实盘），T+1 执行纪律。
- **拐点预警**：全球资本开支见顶（SOX/装机/出货转弱）是拐点信号，不赌 A 股内部反弹。

---

## 7. 产业深研报告与归档（S5 中观落点）

产业深研报告遵循通用 S5 信息分级与来源标注，输出**中观产业研报模板**
（详见 `industry-deep-research` Skill）：

```markdown
# 中观产业深度量化投研报告：{行业名称}（{行业代码}）

> 分析基准日 / 行业层级 / 数据底座（本地 Curated + GrokSearch-rs 产业高频事实核验）

## 一、核心结论与行业配置评级（超配/标配/低配 + 产业周期定位）
## 二、行业全景量化体检事实表（估值分位 / 技术面 / 竞争格局）
## 三、产业链上下游传导与高频微观核验（上游成本 / 下游应用 / 毛利敏感性 / 高频事实）
## 四、行业核心龙头梯队与选股建议
## 五、主要产业风险提示
```

高频微观事实（批价/出货/渠道库存/政策催化）用 GrokSearch-rs MCP 检索核验，明确信源与日期，
填补季频财报时滞。

归档：`docs/research/<industry>/NN_*.md` 分篇（数据可得性 → 建腿 → 验证 → 结论，
对齐光伏 `docs/research/photovoltaic/` 结构）。

---

## 8. 产业深研 SOP 速查（5 步）

1. **提取量化体检数据**：`stock_cli.industry_diagnose --industry <名称/代码> --format json`
   （本地申万黄金表，不虚构估值分位）。
2. **估值水位评估**：行业 PE/PB 历史分位（近 5Y / 10Y），判断极端低/中枢/过热。
3. **产业链传导分析**：对照 `config/industry/value_chain_map.yaml`，上下游价格与毛利敏感性。
4. **高频微观核验**：GrokSearch-rs 检索最新批价/出货/库存/政策，标注信源日期。
5. **龙头梯队与配置结论**：市值 Top 5 龙头、优选赛道与标的池、输出配置评级。

---

## 9. 常用命令速查

```bash
# 产业诊断（估值/技术/竞争格局/传导）
uv run python -m stock_cli.industry_diagnose --industry 半导体 --format json

# 31 行业 5 大中观因子面板（2015-2026 全历史）
uv run python -m stock_cli.industry_factors

# 多策略全周期横向对账研报
uv run python -m stock_cli.industry_strategy_report

# 跨周期稳定性审计 + 防退化 CI 门禁
uv run python -m stock_cli.industry_strategy_audit --assert-guardrails

# 盘尾实盘推演 + 行业 ETF 报单
uv run python -m stock_cli.industry_strategy_live --strategy industry_momentum --dry-run
```

---

## 10. 产业专项文档导航

| 产业 | 数据腿 / 方法论 | 符合性审计 / 分篇 |
| :-- | :-- | :-- |
| 半导体 | `industry-trend-tracking` Skill `references/semiconductor/`（`semiconductor_trading_methodology.md`）、`config/analytics/semiconductor_legs.yaml` | `docs/research/semiconductor/sop_gap_assessment.md` |
| 光伏 | `industry-trend-tracking` Skill `references/photovoltaic/` | `docs/research/photovoltaic/` 分篇（00-13） |
| 化工 | `stock_data/fetcher/industry/chemicals/*`（供需/库存/价差腿） | 待推广 |
| 计算机设备 | `config/analytics/semiconductor_legs.yaml` 覆盖 710100 | 待推广 |

> 新增产业深研线：先读通用骨架 → 按本文 S0-S5 落地 → 在 `docs/research/<industry>/`
> 归档 → 对照通用 Checklist 自查闭环。

---

## 附注

- 本文只承载**中观产业特有**流程；通用六阶段与门禁见 `quantitative_research_workflow.md`。
- 各产业专属命令、公式口径以对应 Skill 与代码为准，不在本文复制。
- 产业专项实证结论以 `docs/research/<industry>/` 与产物 Manifest 为准。
