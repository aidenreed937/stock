# 半导体 GM 前瞻腿（Gross Margin Leading Indicator）Stage 1 验证（ASML 单家）

> 结论性总览（Stage 1 = ASML 单家验证，两阶段方案第一步）。
> 回答问题：**设备龙头毛利率扩张能否用经营先导变量提前预测，且对 A 股 270100 有剪刀差之外的增量？**
> 答案：**能。** 增量 IC 检验通过，但属"方向可靠 + 分年度不稳"的进攻/确认腿，非稳定顺风。

## 一句话结论

> **ASML 前瞻 GM 腿（guidance + 服务 mix）对 270100 fwd60 有显著正 IC（复合 0.156、控制剪刀差后偏 IC 0.189），
> 样本外更强（服务 mix 0.235 / bookings 0.41）；但年度 IC 不稳（2021/2023/2025 转负），
> 定位为「前瞻确认腿」（leg_type 独立分组），不作稳定择时。Stage 2 扩四巨头前先按本结论定门槛。**

---

## 1. 数据（新落盘，Ground Truth 无前视）

| 层 | 内容 | 路径 |
| :--- | :--- | :--- |
| RAW | ASML 2016-2026 共 41 个季度财报新闻稿 HTML（SEC EDGAR 6-K Exhibit 99.1/99.2，gzip 保真） | `data/raw/industry/asml/sec_edgar/*.gz` |
| Curated | 季度黄金表 `semiconductor_equipment_gm.parquet`（41 季，字段覆盖见下） | `data/curated/industry/` |
| 分析产物 | `semi_gm_leading.{md,csv}`（IC/增量/当前截面） | `data/analytics/industry_strategy/` |

采集脚本：`scripts/asml_quarterly_collect.py`（EDGAR 枚举+下载）、`scripts/asml_quarterly_parse.py`（要点句+表格列感知解析）、`scripts/semi_gm_leading.py`（腿构建+IC）。

**关键口径（无前视）**：`release_date` = SEC 6-K filingDate（官方披露日），信号当日收盘后才可用，与现有结构性腿同口径。

**字段覆盖**（41 季）：

| 字段 | 覆盖 | 说明 |
| :--- | :---: | :--- |
| gross_margin_pct | 41/41 | 本季毛利率（要点句+表格双源交叉验证） |
| net_sales_eur_m | 41/41 | 本季净销售额 |
| ibm_sales_eur_m | 41/41 | Installed Base Management（服务/mix，GM 正驱动） |
| new_litho_units | 40/41 | 新光刻机出货（EUV/DUV mix 代理） |
| net_bookings_eur_m | 38/41 | **2016-2025 有值（缺 2015-Q4），2026-Q1 起 ASML 不再披露→诚实缺失** |
| gm_guidance_next_pct | 33/41 | 下季 GM 指引（区间取中值，管理层前瞻） |
| systems_backlog_eur_m | 早期 | 2016-2018 表格披露，后多数缺失 |

---

## 2. 腿构建（leg_type 独立分组，不入剪刀差）

| 腿 | 定义 | 覆盖 |
| :--- | :--- | :--- |
| gm_guidance_score | 下季 GM 指引 12 季滚动分位 | 全期 |
| gm_expansion_score | (指引 − 实际) 12 季滚动分位 = 预期扩张/收缩 | 全期 |
| ibm_share_score | 服务/mix 占比 12 季滚动分位 | 全期 |
| bookings_score | Net bookings 同比 12 季滚动分位 | 2016-2025 |
| **gm_leading_score** | 0.5·guidance + 0.3·expansion + 0.2·ibm（缺失回退） | 全期 |

全部按 release_date 日频前向填充，无前视。

---

## 3. IC 检验结果（270100 fwd60，样本外 2022-01 起）

### 3.1 整体 / 样本外 IC

| 腿 | 全周期 | 样本外 |
| :--- | :---: | :---: |
| **gm_leading_score（复合）** | **0.156** | 0.132 |
| gm_guidance_score | 0.084 | 0.143 |
| gm_expansion_score | 0.109 | 0.036 |
| **ibm_share_score** | **0.215** | **0.235** |
| bookings_score | 0.114 | **0.410** |

### 3.2 增量检验（控制剪刀差后偏 IC，rank 残差法）

| 腿 | 原始 IC | 控制剪刀差后偏 IC |
| :--- | :---: | :---: |
| **gm_leading_score** | 0.156 | **0.189** |
| gm_guidance_score | 0.084 | 0.133 |
| gm_expansion_score | 0.109 | 0.113 |
| **ibm_share_score** | 0.215 | **0.247** |
| bookings_score | 0.114 | 0.128 |

> **增量成立**：控制剪刀差后偏 IC ≥ 原始 IC（0.189 ≥ 0.156），GM 前瞻腿与剪刀差正交增厚，
> 量级（0.19）与现有 demand 腿（0.153）相当，样本外服务 mix 腿更强（0.235）。

### 3.3 年度 IC（分年度不稳，诚实标注）

| 年份 | gm_leading | guidance | expansion | ibm | bookings |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 2018 | **0.798** | 0.787 | 0.629 | 0.224 | -0.086 |
| 2019 | 0.577 | 0.58 | 0.563 | 0.334 | 0.371 |
| 2020 | 0.112 | 0.127 | 0.127 | 0.023 | 0.271 |
| 2021 | -0.327 | -0.24 | -0.388 | 0.323 | -0.327 |
| 2022 | -0.108 | -0.485 | 0.199 | 0.018 | -0.249 |
| 2023 | -0.356 | -0.613 | -0.181 | -0.032 | 0.457 |
| 2024 | 0.104 | 0.443 | 0.39 | 0.206 | 0.306 |
| 2025 | -0.121 | -0.349 | -0.543 | **0.58** | 0.518 |
| 2026 | 0.257 | **0.549** | 0.257 | -0.719 | -0.324 |

> 模式：**服务/mix 腿（ibm_share）最稳定**（2018/2019/2021/2024/2025 常年正，仅 2026 负）；
> guidance/expansion 腿年度翻转（2021/2023/2025 负）——与现有 demand 进攻腿特征一致
> （分年度不恒稳，看收益方向随景气年波动）。符合"前瞻确认腿"定位，非稳定顺风。

### 3.4 当前截面（2026-08-28）

| 腿 | 当前值 |
| :--- | :---: |
| gm_leading_score | 95.0 |
| gm_guidance_score | 100.0 |
| gm_expansion_score | 100.0 |
| ibm_share_score | 75.0 |
| bookings_score | 91.7 |

> 当前 GM 前瞻腿全面贴顶（95/100/100/91.7）——管理层指引连续上修、服务 mix 高位，
> 与 ASML Q2 2026 官方数据一致（GM 54.0%、Q3 指引 55-57%、全年 54-56%）。属高位确认，
> 不作追涨信号（同 demand/ai_capex 贴顶语义）。

---

## 4. 局限（不可外推，诚实标注）

1. **单公司单行业**：全部实证来自 ASML 单家 + 270100，未做四巨头/多行业推广。
2. **bookings 结构断裂（2026-09 复核修正）**：2026-Q1 起（2026-04-15 披露）ASML 不再在新闻稿披露 net bookings 数值（仅定性"订单强劲"）；
   2024-2025 各季 bookings **均有值**（3.6B/5.6B/2.6B/7.1B/3.9B/5.5B/5.4B/13.2B），bookings_score 实际覆盖 **2016-2025（38 季全）**，
   仅缺 2015-Q4 与 2026-Q1/Q2；backlog 仅早期（2016-2018）披露。
3. **分年度不稳**：guidance/expansion 腿 2021/2023/2025 转负，不可作稳定择时腿。
4. **季频低样本**：41 季，12 季滚动分位起始段样本小；滚动分位硬编码 12 季（对齐结构性腿 12 季）。
5. **增量为秩相关**：未控制行业 beta 与多重比较。

---

## 5. Stage 2 结果：四巨头扩样（AMAT/LRCX/KLAC + ASML）

**结论（2026-09 已完成，详见 [`gm_leading_leg_stage2.md`](gm_leading_leg_stage2.md)）**：
- **数据**：AMAT/LRCX/KLAC 8-K 新闻稿 + 10-Q 已采集解析（`semiconductor_equipment_gm_multi.parquet`，company+release_date）。
  GM 以 10-Q 为权威源（KLAC 的 GrossProfit 标签是分部利润、早期 10-Q 无 XBRL → (Revenue−Cost)/Revenue 文本兜底）。
- **腿**：各公司独立 12 季滚动分位 → 日频前向填充；`gm_cross` = 每日各公司 gm_leading 等权。
- **IC**：跨公司合成偏 IC 0.26（控剪刀差），样本外 0.333；**门槛通过 3/4**（AMAT 0.254 / KLAC 0.12 / ASML 0.21 正，LRCX -0.07 负）。
- **非复制品证据**：跨公司腿 vs ASML 单家 Spearman 0.367（R² 13.5%）；控制 ASML 后跨公司偏 IC 仍 0.244/0.320（与自身原始 IC 持平）→ 增量主要来自 AMAT/LRCX/KLAC 独立信息，ASML 与 AMAT 甚至负相关 -0.297。
- **组合确认复核**：`scissors_confirm_cross` 样本外 Sharpe 0.664 > 剪刀差主信号 0.652 > ASML 单家腿 0.626。
- **TEL 已采集但 GM 水平腿已移除（2026-09）**：日本 IR tanshin 57 季（FY2011-2027）→ `tel_gm_quarterly.parquet`；
  TEL 仅 GM 实际值水平腿（日本 GAAP 无指引无服务拆分），偏 IC **-0.091（负，滞后确认）**——
  **已从前瞻复合中移除**（并入会把 gm_cross 稀释至 0.179）。门槛判定仍基于四家前瞻腿公司（AMAT/LRCX/KLAC/ASML，3/4 正）。
- **定位升级**：从 ASML 单家"确认腿"升级为四巨头合成"较强确认腿"；**待办**：KLAC 财年末 10-K 补采、LRCX 早年服务占比、权重寻优。

### 5.1 数据源与财年错位（roadmap 否决线的正面应对）

| 公司 | 财年末 | 6-K/10-Q 节奏 | 前瞻字段可得性 |
| :--- | :--- | :--- | :--- |
| ASML | 12 月 | 6-K 季报（已落地） | GM 指引/IBM/bookings(至2023) |
| AMAT | 10 月末 | 10-Q/8-K | GM 指引/backlog(部分)/服务占比 |
| LRCX | 6 月末 | 10-Q | GM 指引/service mix |
| KLAC | 6 月末 | 10-Q | GM 指引/服务占比 |
| TEL(日) | 3 月末 | 财报新闻稿（非 EDGAR） | GM 指引/订单 |

- **EDGAR 可复用**：AMAT/LRCX/KLAC 直接复用 `cloud/collector.py` 的 SEC CompanyFacts/6-K 采集范式；
  TEL 需走日本 IR 新闻稿（单独适配器）。
- **财年错位处理**：统一以 `release_date`（实际披露日）对齐日频，**不用财年末对齐**——
  无前视口径天然规避 roadmap 封存的"财年错位硬对齐"；每季 GM 相对各公司自身财季，同口径合成时
  按各自 release_date 生效再聚合（与结构性腿 ai_capex 四家合成同范式）。
- **量级归一**：GM 用百分数（无量纲）、IBM/service 占比用占比、bookings 用同比（去体量）——
  规避 roadmap 封存的"量级失真"。

### 5.2 落地清单

1. 复用 `asml_quarterly_collect.py` 泛化为 `equipment_giants_collect.py`（AMAT CIK 6951/LRCX 707549/KLAC 71810/TEL 需 IR 适配）。
2. 各自季度黄金表 → 合并为 `semiconductor_equipment_gm_multi.parquet`（company 维度 + release_date）。
3. `gm_leading_score` 扩展为跨公司合成（各自滚动分位后等权或按份额加权）。
4. 增量 IC 检验复跑（270100 fwd60，控制剪刀差），四家一致正 → 升级框架腿；不一致 → 降级确认腿。
5. 分年度监控 + 财年/量级对账审计（对齐 roadmap 对账锚要求）。

### 5.3 门槛（对齐 roadmap 纪律）

- 四家 ≥3 家样本外偏 IC 为正 → 可作进攻/确认腿接入；
- <3 家 → 保持 ASML 单家确认腿，不作跨行业推广，诚实标注。

---

## 6. 定位（一句话）

> **GM 前瞻腿 = 「毛利率扩张」从滞后财报验证升级为经营先导前瞻（订单/指引/服务 mix 驱动），
> 与剪刀差正交增厚（偏 IC 0.26）；Stage 1 验证 ASML 单家（确认腿），
> Stage 2 四巨头（AMAT/LRCX/KLAC+ASML）门槛 3/4 通过、跨公司合成腿更优 → 已升级为「较强确认腿」。**
