# 大宗化工全板块横向截面扫描雷达 Mart 与源头数据正确性审计报告

> 审计基准日: 2026-09-20 | 审计人: 本地只读校验脚本 + 人工复核
> 审计对象: `data/curated/mart/chemical_cross_section_mart.parquet` / `chemical_cross_section_mart_latest.csv`
> 复现脚本: `scripts/check_chemical_cross_section.py`（只读，不写盘）
> 说明：第一~六节为 2026-09-20 审计时点的快照记录（含已发现的问题）；修复进展见第七节"阶段一验收记录"。

## 一、总体结论

**Mart 的计算链路自洽、可复现、无计算错误（PASS），但"数据完整且全字段最新"不成立（FAIL）。**

| 维度 | 结论 | 说明 |
| :--- | :---: | :--- |
| parquet 与 CSV 快照一致 | ✅ PASS | 8 行 × 42 列，逐字段一致（数值容差 1e-6） |
| Schema 与代码契约 | ⚠️ WARN | 42 列集合一致；`cross_section_rank` 实际 Int64，代码声明 Int32 |
| 可复现性 | ✅ PASS | `as_of=2026-09-20` 内存重建与落盘 parquet 完全一致 |
| 打分引擎自洽性 | ✅ PASS | 8 行按落盘输入重算 phase/score/stance 100% 一致 |
| 8 大品种源头覆盖完整性 | ❌ FAIL | R32 现货缺失；MDI/TiO2/R32 无成本曲线与周度开工库存；TA/V 部分指标显著陈旧 |
| 海关出口与弹性映射 | ✅ PASS | 2026-08 出口量价与 `export_regime`、弹性 top 均与源头最新行一致 |
| alpha/beta 标的映射 | ✅ PASS | 8 个 `trading_gates.yaml` 的 `target_universe_mapping` 与 Mart 输出一致 |

## 二、一致性证据（脚本输出摘要）

1. `chemical_cross_section_mart.parquet` 与 `_latest.csv`：rows=8、columns=42，逐字段一致 → PASS。
2. 内存重建（`ChemicalCrossSectionMart(as_of_date=2026-09-20).build_cross_section_frame()`）与落盘逐字段一致 → PASS。
3. 打分重算：8/8 行 `cycle_phase`、`composite_score`、`investment_stance` 与落盘一致 → PASS（规则本身无逻辑跳变）。
4. Schema：列集合与 `CROSS_SECTION_SCHEMA` 一致；仅 `cross_section_rank` dtype 为 Int64（声明 Int32），低风险。

## 三、8 大品种 × 7 类源头覆盖矩阵（各源头最新行）

| 品种 | 成本曲线(最新日/现货/现金覆盖%) | 理论价差 | 现货基准 | 周度开工/企业库存 | 期现基差/仓单 | 海关出口(2026-08) | 业绩弹性 top |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| SA 纯碱 | 09-17 / 1077.14 / 41.11% | 09-15 +502.86 profitable | 09-17 1077.14 | 09-17 开工无值 / 库存 190.62* | 09-17 basis +6.59% / 0.338万t | vol +32.15% asp -6.15% volume_driven | 山东海化 0.2076 |
| TA PTA | 09-17 / 7362.2 / 100% | 09-15 +757.25 high_profit | 09-17 7362.2 | 09-17 开工 72.08% / 库存 320.37△ | 09-17 basis +13.23% / 1.0万t | vol -16.03% asp +30.0% price_driven | 恒力石化 0.1283 |
| MEG 乙二醇 | 09-17 / 6708.33 / 100% | 无 | 09-17 6708.33 | 09-17 开工 61.89% / 库存 11.4 | 09-17 basis +9.12% / 2.244万t | vol +85.33% asp +25.34% export_boom | 华鲁恒升 0.0274 |
| MA 甲醇 | 09-17 / 4030.0 / 100% | 无 | 09-17 4030.0 | 09-16 开工取 09-11 值 83.8% / 库存 27.97 | 09-17 basis +25.68% / 6.508万t | vol +510.25% asp +6.97% export_boom | 华鲁恒升 0.0137 |
| V PVC | 09-17 / 4710.0 / 19.25% | 无 | 09-17 4710.0 | 开工 70.97%（08-07 值◇）/ 库存 108.47 | 09-17 basis -1.61% / 31.4465万t | vol +11.79% asp +11.3% export_boom | 新疆天业 0.0617 |
| TiO2 钛白粉 | 09-15 / 14200 / 100% | 09-15 +1550 profitable | 09-15 14200 | 无（周度源无 TIO2 记录） | 无（无期货） | vol +3.71% asp +19.62% stable | 龙佰集团 0.0438 |
| MDI 聚合MDI | 无（polyurethane 无 cost_models） | 无 | 09-15 18466.67 | 无 | 无（无期货） | vol +4.47% asp +22.89% stable | 万华化学 0.0799 |
| R32 制冷剂 | 无（refrigerant 无 cost_models） | 无 | **无（现货价=0）** | 无 | 无（无期货） | vol -40.04% asp +21.9% price_driven | 三美股份 0.0049 |

标注：
- `*` SA 库存 190.62 为 Curated 同周合流后 09-17 行的值，实际取自周一 09-14 数据；RAW 中周四 09-17 新值 188.88 被合流锚定丢弃（见问题 P3）。
- `△` TA 企业库存 320.37 最后有效值为 2026-06-12，7–9 月周报无库存数据，被 as-of 前推使用（问题 P1）。
- `◇` V 开工率 70.97% 为 2026-08-07 值，09-17 周报无开工数据（问题 P1/P2）。

## 四、问题清单

| ID | 严重度 | 现象 | 证据 | 建议 |
| :--- | :--- | :--- | :--- | :--- |
| P1 | 高 | R32：现货价=0、无成本曲线、无开工/库存/基差仓单，却输出 95 分 `OVERWEIGHT_RIGHT` | `chemical_spot_price.parquet` 无 R32 symbol（R134a/R22 有）；`config/industry/chemicals/refrigerant/` 无 `cost_models.yaml`；`_evaluate_cross_section` 对 C 类配额品种硬编码 90+ 分 | 接入 100ppi R32 (ppid 1289) 现货采集；补 `refrigerant/cost_models.yaml`；在源未就绪前为 R32 行打 `DATA_INCOMPLETE` 标记并降置信度，不得输出 95 分 |
| P2 | 高 | MDI：仅现货+出口+弹性，无成本曲线/开工/库存/基差，仍输出 72 分 `OVERWEIGHT_RIGHT` | 覆盖矩阵 MDI 行 5/7 类缺失；`polyurethane/` 无 `cost_models.yaml` | 补 MDI 多工艺成本模型（光气化/厂家挂牌口径）；无数据时降级或标注缺失 |
| P3 | 中高 | TA 企业库存 320.37 万吨为 2026-06-12 旧值，被当作当前库存参与库存分位 | Curated 周度表 TA 7–9 月 factory_inventory 全为 null；basis mart as-of 前推旧值 | 补齐 TA 企业/社会库存数据源；在 mart 中增加"字段数据日期"列，避免旧值伪装成最新 |
| P4 | 中 | V 开工率 70.97% 为 2026-08-07 值（滞后 6 周）；09-17 周报无开工数据 | 周度表 V 09-17 行 op=None；交差截面取历史最后非空 70.97 | 补 V 开工周报；或披露滞后并按缺数处理 |
| P5 | 中 | 周度同周合流锚定丢弃周四新值：SA RAW 09-17 库存 188.88，Curated 09-17 行为 190.62（周一 09-14 旧值） | RAW `weekly_survey.csv` 行 702 与 Curated 表 09-17 行对比；`transforms/weekly_survey.py` 锚定优先 weekday 升序 | 修正合流锚定：同周内优先取最新 report_date 的非空值，而非最小 weekday；加测试断言 |
| P6 | 低 | `cross_section_rank` 落盘 dtype=Int64，代码 schema 声明 Int32 | 校验脚本 Section 2 | 统一为 Int32 或同步代码声明 |
| P7 | 低 | TiO2 无周度开工/企业库存与基差（无期货属预期）；库存时钟目前完全由 margin/export 推断，缺库存腿 | 覆盖矩阵 TiO2 行 | B 类产品可接受期货缺项，但建议补钛白粉周度开工数据源 |

## 五、时效说明（正常项）

- 海关出口截至 2026-08 报告月（09-20 时点满足 T+20 节奏），量价与四象限与 Mart 一致 → 正常。
- 成本曲线/价差/现货/基差仓单最新日为 2026-09-15 ~ 09-19，较 Mart 基准日 09-20 滞后 1~5 天，属日频/周频正常节奏。
- 业绩弹性 `chemical_elasticity_mart` 最新 trade_date 2026-09-07（周频）。

## 六、最终判定

1. **Mart 本身（结构/口径/可复现/打分）正确**：parquet=CSV、可重建、打分自洽、标的映射正确。
2. **源头数据并不"全部正确/完整"**：R32 现货与成本全缺、MDI/TiO2 成本曲线与开工库存缺项、TA/V 关键指标过期、SA 同周合流丢最新值，均会在投研解读中造成"看似有数据支撑、实则缺腿"的误导。
3. 建议按 P1–P7 逐项补齐后再将雷达用于轮动决策；在补齐前，报告/解读需显著标注各品种数据完整度。

---

## 七、修复进展与阶段一验收记录 (2026-09-20)

阶段一（纯代码缺陷与规则防御门禁）已全部落地并完成验证：

| 修复项 | 状态 | 对应改动与验证证据 |
| :--- | :---: | :--- |
| **P5 周度合流丢周四新值** | ✅ 已修复 | `transforms/weekly_survey.py`: 重构提取逻辑，各指标按 `report_date` 降序取最新非空值。重物化后 SA 09-17 库存正确取到 188.88 万吨（周四新值）；单测 `test_coalesce_weekly_survey_prioritizes_latest_thursday_values_over_monday` 通过 |
| **P6 Rank Schema 类型** | ✅ 已修复 | `chemical_cross_section_mart.py`: `pl.int_range(..., dtype=pl.Int32)` 保持契约一致；`check_chemical_cross_section.py` Section 2 告警消除 (PASS) |
| **P1 R32 现货缺失高危打分守卫** | ✅ 已修复 | `chemical_cross_section_mart.py`: `spot_price <= 0` 时硬约束返回 `DATA_INCOMPLETE` + 50.0 分 + `NEUTRAL_WATCH`，彻底消除 95 分假高分；单测通过 |
| **P2 MDI 寡头无成本模型降级守卫** | ✅ 已修复 | `chemical_cross_section_mart.py`: B 类无成本模型且无周度开工库存时，评分上限约束为 65.0 分并归入 `NEUTRAL_WATCH`；单测通过 |
| **P3/P4 历史陈旧值滞后披露** | ✅ 已修复 | `chemical_cross_section_mart.py`: 提取周度最后有效记录时检测距基准日是否 >30 天，若是则在 `rationale` 显著追加 `[数据滞后提示: ...]` |

**无风险收尾补充（2026-09-20 晚）**：
- 新增 8 个字段级数据日期列（Schema 42 → 50 列）：`spot_price_asof_date`、`cost_curve_asof_date`、`spread_asof_date`、`operating_rate_asof_date`、`inventory_asof_date`、`basis_asof_date`、`customs_asof_month`、`elasticity_asof_date`，滞后值可由列直接读取（如 TA `inventory_asof_date=2026-06-12`、V `operating_rate_asof_date=2026-08-07`），不再只埋在 `key_rationale` 文本；
- 修复 `key_rationale` 双标点（`。；/；；` → 单标点）；
- 校验脚本第 6 节增加"存在滞后提示"标注（TA/V 不再显示"核心字段齐备"）；
- 重新物化后复核：parquet==CSV（8 行 × 50 列）、Schema PASS、内存重建与落盘一致、打分 8/8 一致、ruff/pytest（18 passed）全通过。

**阶段二待办（数据模型与源头补齐）完成情况（2026-09-20）**：
- P1-data: 补齐 `data/raw/industry/chemicals/100ppi/R32.json` 并物化入 `chemical_spot_price.parquet`（最新现货 65,000 元/吨）；新建 `config/industry/chemicals/refrigerant/cost_models.yaml`，并在 `chemical_cost_curves.py` 注册，打通成本出清计算；
- P2-data: 新建 `config/industry/chemicals/polyurethane/cost_models.yaml`，并在 `chemical_cost_curves.py` 注册，打通 MDI 成本出清计算；
- TiO2/MDI 守卫: 在 `chemical_cross_section_mart.py` 中增加 B 类寡头开工库存双缺失守卫，将 TiO2 评分上限修正压制至 65.0 分（`NEUTRAL_WATCH`），彻底消除无库存数据下的右侧乐观偏误；
- 全流程物化复核：重新生成 `chemical_cost_curves.parquet`（8 品种）与 `chemical_cross_section_mart.parquet`（8 行 × 50 列），`scripts/check_chemical_cross_section.py` 全 6 节通过（PASS），pytest 18 个测试全部通过。
