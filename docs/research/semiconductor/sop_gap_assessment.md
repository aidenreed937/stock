# 半导体（`semiconductor`）深研线 SOP 符合性评估

> 本文是**半导体产业深研专项**文档，评估半导体深研线对照通用量化研究标准工作流程
> （`../quantitative_research_workflow.md`）的符合程度，并给出收口建议。
> 只保留半导体业务相关的评估结论与行动项；通用工作流（六阶段 SOP、Checklist、
> Ground Truth First）见通用文档，本文不重复。

---

## 1. 评估范围

对照通用 SOP 六阶段，对当前半导体深研线做逐项评估，基于本次核查时的代码、配置与产物：

- 代码：`src/stock_analytics/pipelines/semiconductor/`、`src/stock_strategy/industry/semiconductor/`、
  `src/stock_data/fetcher/industry/semiconductor*/`、`src/stock_cli/`
- 配置：`config/analytics/semiconductor_legs.yaml`、`config/strategy/semiconductor_research.yaml`
- 产物：`data/analytics/semiconductor/`、`data/strategy/semiconductor/`
- 方法论：`semiconductor_trading_methodology.md`（skills 引用目录）

---

## 2. 评估结论：**整体符合性好，已接近全链路闭环；主要缺口在统一 CLI 入口与部分数据披露**

半导体是当前仓库中按 SOP 落地最完整的一条深研线，六阶段**均已打通并已产出**
（特征面板、IC、回测、敏感性、稳定性、方法论文档均有物）。相对标准，它在
**S0 立题、S1 数据、S2 特征、S3 验证的工程化程度明显领先**；"部分符合"项主要落在
**统一 CLI 命令面、数据来源披露、docs/research 分篇归档、跨业务通用抽象**等
收紧类增量，多为有据可依，不改变主干工程化水准。

---

## 3. 逐项对照通用 SOP

| SOP 拉点 | 半导体现状 | 结论 |
| :-- | :-- | :-- |
| **S0 立题** | 有统一方法论文档 `semiconductor_trading_methodology.md`（含核心命题/机制/分层/一句法收束）；攻防双轨 + GM 前瞻确认腿 + 防守门都明确定位与职责 | ✅ 符合 |
| S0 术语分层 | 全链路显式区分"特征 feature vs 有效因子 factor"，并在 `legs.py`/`pipeline.py`/`config.py` 注释里重复声明 | ✅ 符合 |
| S0 参数进配置 | `config/analytics/semiconductor_legs.yaml`、`config/strategy/semiconductor_research.yaml`，默认对齐定稿阈值 | ✅ 符合 |
| **S1 数据** | 产业数据腿在 `stock_data/fetcher/industry/semiconductor*/`（TSMC/SIA/SEAJ/AI CapEx 等），release_date 生效无前视 | ✅ 符合 |
| S1 质量/测试 | 有 `tests/unit/stock_data/fetcher/test_semiconductor_*`、`test_seaj_*` 等；外部源 mock | ✅ 符合 |
| **S2 特征** | `pipelines/semiconductor/`（config/pipeline/legs），config 驱动、0-100 滚动分位、release_date 前向填充 | ✅ 符合 |
| S2 产物/Manifest | `data/analytics/semiconductor/latest/` 有 `manifest.json`（provenance/watermark/data_completeness）+ 面板 parquet | ✅ 符合 |
| **S3 验证** | `stock_strategy/industry/semiconductor/`（ic/backtest/sensitivity/validation/report/pipeline）四件套齐全；产物在 `data/strategy/semiconductor/` | ✅ 符合 |
| S3 跨周期/样本外 | `oos_start: 2022-01-01`；事件状态机回测（4 变体）；年度 IC；主要回撤段防守审计 | ✅ 符合 |
| **S4 组合/实盘** | 半导体已落为深研线簇（剪刀差 LONG + DOI 激活选行业并自带择时），防守门、ETF 映射、T+1 纪律在 `industry-trend-tracking` Skill 定义 | ✅ 符合（经由产业趋势跟踪体系） |
| **S5 报告/归档** | 有统一方法论文档 `semiconductor_trading_methodology.md`（skills 引用目录）+ 研究产物留痕（IC/回测/稳定性表）；但半导体自身尚未在 `docs/research/semiconductor/` 沉淀 `NN_*.md` 分篇研究归档（光伏已建 `docs/research/photovoltaic/` 分篇体系） | ⚠️ 部分符合 |
| **统一 CLI 入口** | `src/stock_cli/` 中 grep `semiconductor` **无匹配**：半导体深研线的建腿运行与策略验证目前以脚本/就地调用为主，未接进 CLI 命令面 | ⚠️ 部分符合 |
| **数据来源披露** | 已沉淀统一"数据源/时效/代理口径/缺口"声明 `docs/research/semiconductor/02_data_availability.md`（含需求腿核心声明：TSMC = 单公司领先代理腿、不替代 SIA/WSTS 作为全球销售额 Ground Truth；含云 Capex release_date 缺失等 6 项缺口披露），满足 Ground Truth First 与信息分级 | ✅ 已完成（2026-09-03） |
| **跨业务复用抽象** | 建腿/验证逻辑半导体专用（`pipelines/semiconductor/*`、`strategy/industry/semiconductor/*`），尚未抽象为"全业务通用建腿/验证框架"（虽有 `factor_research`/`industry_diagnostics` 管线可借鉴） | ⚠️ 部分符合（设计取舍，非缺陷） |

---

## 4. 建议的符合性收口（按优先级）

1. **补统一 CLI 入口（P1）**：把半导体建腿运行 + 策略验证接到 `src/stock_cli/`，
   提供 `--dry-run`、`--as-of`、`--latest` 之类的统一研究命令面，使半导体能像
   `industry-trend-*` / `macro-*` 一样一键复现，也便于后续业务复制同一命令骨架。
2. **补数据来源披露（P1）**：~~仿照光伏 `02_data_availability.md`，为半导体产业腿
   生成一份统一的"数据源/时效/代理口径/缺口"声明，满足 Ground Truth First 与信息分级。~~
   ✅ **已完成（2026-09-03）**：落地 `docs/research/semiconductor/02_data_availability.md`。
3. **补研究分篇归档（P1）**：在 `docs/research/semiconductor/` 下沉淀 `NN_*.md` 分篇
   （数据可得性 → 建腿 → 验证 → 结论），对齐光伏 `docs/research/photovoltaic/` 的同款结构。
4. **沉淀跨业务通用骨架（P2，长期）**：把已高度成熟的"建腿(特征) → 验证(因子)"两级
   流程，结合 `factor_research` / `industry_diagnostics` 抽象成一份**通用业务建腿验证框架**
   （可复用 ArtifactStore/Manifest、release_date 生效、IC/回测/敏感性/稳定性工具），
   让半导体经验直接迁移到光伏/化工/计算机等业务，减少重复脚本。

> 说明：以上"部分符合"项多为**有据可依的增量收口**，不改变半导体深研线当前已具备的
> 完整性与工程化水准；数据披露已补齐（`02_data_availability.md`），在按第 4 节的
> P1（CLI 入口 + 分篇归档）补齐前，半导体可视为"符合 SOP"但"CLI 统一命令面 + 分篇归档待补全"。

---

## 5. 本文与通用 SOP 的关系

- 通用工作流（六阶段、Checklist、Ground Truth First、门禁）见
  `../quantitative_research_workflow.md`。
- 本文是 `通用 SOP × 半导体专题规则` 落地后的**符合性自我审计**，随半导体研究演进持续跟踪。
- 新业务线的符合性评估，另立 `docs/research/<business>/sop_gap_assessment.md`，
  不并入通用文件。
