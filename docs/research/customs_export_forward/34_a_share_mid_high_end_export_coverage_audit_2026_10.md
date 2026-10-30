# 34 · A股中高端出口商品覆盖审计（2026-10）

> 状态更新（2026-10 最终重建后）：`taxline_segments.csv` 实测 **31 段**（32 行含表头，
> 本文档 §2 记 32 段为含表头计数）；§5 记高置信映射 **102 个产品不变**（mapping
> match_status=selected 实测仍 102），暴露 Mart 产品覆盖更新为 **104 个**（另含
> auto_parts/battery，经 `company_segment_binding.csv` 人工绑定路径进入；Mart
> 348,713 行 / 1,045 家，见 customs-export-research 操作手册 §1）。

> ⚠️ 时效提示（2026-10 后 catalog 再扩容）：本文档审计口径为 149 产品 / 1,044 码 /
> 18 个 category_key、taxline 31 段。当前实测：catalog **154 产品 / 1,074 个 8 位税号**、
> `categories.csv` **16 个 category_key**、`taxline_segments.csv` **212 段**、
> `gacc_query_codes.txt` **1,069 码**；待补采以 `customs_export_backlog.csv`（82 码）为准。
> 段级产品覆盖数（**121 产品**）与暴露 Mart 行数（**463,073 行 / 1,221 家 / 136 产品**，
> max report_month 2026-07）已于 2026-10 复核确认，以操作手册 §1 与最新 Manifest 为准。

> 版本：2026-10 · 对象：`config/data/customs/good_products.csv`（产品主表）与
> `config/data/customs/good_h8_codes.csv`（税号表）
> 口径（用户确认）：以仓库现有口径为基准——108 产品回测池 + 现行 149 产品 catalog
> 做全池完整性核验，并单独给出“严格中高端制造子集”分层结论；本审计**只检查、不改文件**。
> 复现：`uv run python scripts/audit_customs_catalog_coverage.py`；
> 基础一致性另跑 `uv run python scripts/check_catalog.py --industry`。

## 0. 结论摘要

**两个文件不能支撑“A 股中高端出口商品已覆盖全”的结论**，但缺失集中在三个可枚举的层：

1. **仓库口径产品池缺口（已修复一项）**：审计发现 108 产品回测池中 `aquatic_products`
   （水产品）在 catalog 缺失（gold 仍残留其 6 码数据）；**已按黄金表权威映射恢复**
   （§3.2/§7.1，2026-10）。`ev_charger`（充电桩）仍未入 catalog（需税则确认，§6/§7.2）。
2. **税号层口径缺口（实测）**：catalog 1044 码中 **59 码在黄金表无行**（HS2027/HEV/PHEV
   拆分新码、历史桥接码等），黄金表另有 30 个 catalog 已不维护的历史码驻留（§3.3）；
   `vacuum_cleaner` 已并入 `robot_vacuum`（GACC 仅报 85081100，无独立数据属设计内），
   `robot_vacuum` 数据仍只到 2026-05；另有 12 个产品是“代理/限定口径”，
   不是物理全集（§3.3）。
3. **中高端制造子集边界外的候选缺口（待确认，不计入结论）**：充电桩、轴承、工业阀门、
   液压件、燃气轮机、拖拉机、集装箱、港口机械、工业电机、半导体材料等常见 A 股出海
   商品未入 catalog（§6）。

另有结构性提示：catalog 149 产品中仅 **102 个**有高置信公司映射（METHODOLOGY_COMPANY_FINAL
§7），即产品层覆盖 ≠ 公司层覆盖；申万 L2 中厨卫电器在 catalog 无产品映射
（METHODOLOGY_FINAL §2.4）。

## 1. 审计口径与范围

- 判定“覆盖全”的参照系 = 仓库自身研究口径：
  - **108 产品回测池**（GACC 黄金表口径，`METHODOLOGY_COMPANY_FINAL` §6；名单见 18/24 号文档）；
  - **现行 catalog** = `good_products.csv` 149 产品 / `good_h8_codes.csv` 1044 个 HS8 码；
  - 税号级“口径内确认全/补全”结论引用 33 号文档（2026-10 已核验批次）。
- 中高端子集分层：类别白名单（汽车/机械/电力设备新能源/TMT/医药/家电/军工/家居）+ 高端材料与加工材白名单（稀土永磁、锂电铜铝箔、铝箔铝板带、锂盐、MDI、制冷剂、钛白粉、饲料添加剂、合金钢、无缝管、玻纤），共 **113/149** 产品；规则与逐产品标注见审计脚本与事实表。
- 不做的事：不修改 catalog、不联网补外部全集、不给外部候选缺口算数（仅列出供确认）。

## 2. 资产现状

| 资产 | 数量 | 说明 |
| :-- | :--: | :-- |
| `good_products.csv` | 149 产品 | 150 行含表头；18 个 category_key（2026-10 恢复 agriculture_and_fishery） |
| `good_h8_codes.csv` | 1044 税号 | 1045 行含表头；全部 8 位末级子目（含 aquatic 6 码；清洁电器合并为 85081100） |
| `gacc_query_codes.txt` | 1039 码 | 由 `scripts/extract_gacc_query_codes.py` 派生的 leaf 码清单（catalog 1044 中剔除 00 父级历史码与无 GACC 报验粒度码） |
| `taxline_segments.csv` | 32 段 | 14 段历史说明过时，现行 32 段（transformer/semi/lithium/silver/cathode/power_cable/battery/solar/auto_parts/inverter/uav/ecig） |

## 3. 覆盖核查结果

### 3.1 内部引用完整性（文件内自洽）

`scripts/check_catalog.py` 覆盖：product_key 唯一性、税号 8 位格式、父码/层级一致性、
税号引用未知产品、6 位前缀跨产品混品告警、loader join 可加载。本审计脚本另补：
**产品无税号行检查**。

- 税号引用完整性：全部 1044 码的 `product_key` 均存在于产品主表（loader 会直接报错，当前通过）。
- **无独立税号的产品（2）**：`fuel_cell`（设计使然——description 明示“无独立 h8，暂由
  battery(85078030/90) 覆盖”，价格/量随 battery 观察）；`vacuum_cleaner`（2026-10 并入
  `robot_vacuum` 合并观察，GACC 仅报 85081100，见 §3.3 第 3 条）。
- 混品品目（同一 6 位前缀跨多个产品，需显式拆分确认）：**3 个**——
  `130219`（pesticide/plant_extract）、`300490`（chinese_patent_medicine/pharma_chemicals）、
  `851762`（network_equipment/optical_module/wireless_earbud）。
  （850811/850819 已于 2026-10 通过合并 robot_vacuum/vacuum_cleaner 消除。）

### 3.2 108 产品回测池 diff（仓库口径产品级缺口）

| diff | 数量 | 名单 |
| :-- | :--: | :-- |
| 108 池存在、现行 catalog 缺失 | **0（已恢复）** | `aquatic_products` 已于 2026-10 按黄金表权威映射回填（6 码：03032300/03032400/03046211/03046290/03061730/03061790） |
| 现行 catalog 超出 108 池 | 41 | 2026 年扩展的观察/出海产品（ATV、割草机、激光机床、无人机等，逐项见脚本事实表 `data/analytics/industry/customs_catalog_coverage_audit_2026_10.csv`） |

> 说明（2026-07 黄金表实测）：恢复前 `customs_trade_gacc.parquet`（管线默认输入）仍含
> `aquatic_products` 189 行、2025-01~2026-07、8 位码 6 个，L3 映射非空——即“断链”是
> **catalog 缺定义、gold 残留旧物料化**。恢复后 catalog↔gold 对该产品闭合；gold 的 hs8
> 层另有 11 个码级历史键（03032300/03032400/03046211/03046219/03046290/03061711/
> 03061719/03061721/03061729/03061730/03061790，作为 product_key 存在），其中 5 个
> （03046219/03061711/03061719/03061721/03061729）是旧 hs6 时代的变体键，不在恢复口径内。
> `ev_charger` 在 gold 中 **0 行**，只在 04 号文档（2026-09 补码记录）出现，属“文档↔文件”漂移。

### 3.3 税号级覆盖（在声明口径内）

沿用 33 号文档（2026-10）：第四组 8 个单码产品 + 医疗轮 9 个产品 + 全量普查 48 个产品
已按“产品定义范围内的现行 8 位末级子目全部进台账”核验，确认全/补全。**剩余开放项**
不能支撑“全”：

1. **黄金表 vs catalog 码级缺口（实测）**：管线默认黄金表
   `data/curated/industry/customs_trade_gacc.parquet`（2026-07 快照）hs8 层仅
   **1015 个码 / 159 个产品**，而 catalog 有 **1044 码 / 149 产品**：
   - catalog 有、gold 无的 **59 码**：HS2027 新码（27101925/27101926）、
     HEV/PHEV 2026 拆分码（87034019/69/72/73/79、87035011/19/29/39/41/42/49/51/61/63/69/71/73/79、
     87036012/13/19/79、87037012/13/19/42/43/49/51/52/53/59/61/62/63/69/71/72/73/79）、
     87012300、88062410/88062910、89013000/89019043、85021300、85176295、74031300、
     29034800、54023213、84135030、84073400/84082000/84089000（老 6 位父级写法）、
     84795010/90181300（历史桥接码）等；
   - gold 有、catalog 无的 **30 码**：03046219/03061711/03061719/03061721/03061729
     （水产品旧变体键）+ 28269010/90、28530010/90、30049060、
     38249910/20/30/91/92/93、39211910、72104900、85030000、85340000、
     85414010/90、85423100/23200/23900、87036000/37000/38000、87119010/90 等历史/替代码
     （旧 catalog 物料化残留）。
   - 33 号文档 §7.2 记录过“新增 272 码尚未在 GACC raw 查询”（raw 此前仅含旧 769 码中
     有数据的 626 码）——与上述 59 码缺口同向，说明 catalog 码齐 ≠ 黄金表已采集。
2. **代理/限定口径产品**（description 代理标记由脚本检出 **12 个**：`aluminum_foil`、
   `battery_aluminum_foil`、`battery_copper_foil`、`battery_electrolyte`、`cathode_material`、
   `cathode_precursor`、`combustion_engine`、`diesel_genset`、`fuel_cell`、`hand_tools`、
   `nylon_filament`、`polyester_filament`；另按 33 号文档补充限定口径）：
   - 代理口径：`battery_electrolyte`（38249999）、`battery_copper_foil`/`battery_aluminum_foil`
     （按材质归铝/铜观察）、`cathode_material`/`cathode_precursor`、`hydrogen_electrolyzer`
     （85433000 单码 + ASP 伪影，description 无标记但属口径限定）、`combustion_engine`/
     `diesel_genset`/`hand_tools`（品目级无数量）、`fuel_cell`（并入 battery，gold 中
     364 行为 85078030/85078090 旧归属，重刷后会并入 battery）；
   - 限定口径（有意不扩）：`server`（847149+847150，847141 不并入）、`electronic_cigarette`
     （24041200+85434000）、`aluminum_foil`（760711 系+76072000，76071900 归锂电铝箔防双计）、
     `nylon_filament`/`polyester_filament`（已补同族，“其他合纤”兜底不扩）、
     `pharma_vaccines`/`plant_extract`/`peptide_api`/`api_paracetamol`（限定/代理口径）；
3. **上游数据缺口**：`robot_vacuum` GACC 采集仅到 2026-05（METHODOLOGY_FINAL §7.5）。
   码级错配已于 2026-10 修复（**根因**：GACC raw 2019-2026 在 850811 下只报
   `85081100` 一个粒度，`85081110/85081190/85081910/85081990` 在 raw 中不存在）——
   `robot_vacuum` 改映射 `85081100`，`vacuum_cleaner` 并入 `robot_vacuum` 合并观察
   （description 留痕，无独立税号属设计内）。`refined_products` 的 HS2027 切换已于
   2026-09-07 对齐（同 §7.5），不算开放缺口。

### 3.4 申万行业层映射空白

- METHODOLOGY_FINAL §2.4：40 个 L2 行业中厨卫电器（方向一致率 0.38，C 级）
  “在 catalog 无产品映射”，行业观察表不出现该行——catalog 对申万 L2 的映射覆盖率
  **39/40**（不含组合码口径 42 个 L2 唯一码）。

## 4. 中高端制造子集分层结论

子集定义见 §1（113/149 产品）。分层结论：

| 层 | 产品数 | 有独立税号 | 无独立税号 | 缺失产品 |
| :-- | :--: | :--: | :--: | :-- |
| 中高端制造子集（审计口径） | 113 | 111 | 2（`fuel_cell` 并入 battery；`vacuum_cleaner` 并入 robot_vacuum） | 仓库池内无；外部候选见 §6 |
| 全池（含大宗/低端） | 149 | 147 | 2（同上） | 108 池已闭合（aquatic_products 已恢复） |

- 中高端子集内的关键产品族（变压器/电网、半导体设备与 IC、光模块/PCB、锂电与材料、
  光伏、风电、工程机械、机床/激光、工业机器人、汽车整车与零部件、家电、白电、医药
  器械/原料药、船舶/无人机/轨交）在 catalog 中均有对应产品行与 HS8 码，税号级在
  “声明口径内”已按 33 号文档核验；
- **子集内仍存在的“不算覆盖全”项**：① `fuel_cell` / `vacuum_cleaner` 无独立税号
  （均按并入口径观察）；② catalog 1044 码中 59 码在黄金表无行（§3.3）；
  ③ `robot_vacuum` 数据缺口（至 2026-05）；④ 公司映射仅 102/149（§5）。

## 5. 公司层覆盖（补充说明，非两文件直接结论）

动态 H8 链路（`customs_company_h8.py`）从 `fina_mainbz` 自动映射到产品，现行结果：
391,873 条映射、10,133 条高置信（match_status=selected）、**102 个产品**有高置信公司映射
（METHODOLOGY_COMPANY_FINAL §7）。即 149 产品中约 47 个没有高置信 A 股公司样本——
这不代表“商品不该覆盖”，而是公司主营构成里尚未映射出这些产品的暴露；若要回答
“A 股哪些公司受益”，47 个产品仍属覆盖盲区。

## 6. 仓库口径之外的中高端出口商品候选缺口（待确认，不计入结论）

以下为外部推断的常见 A 股中高端出海商品（未在现行 catalog，且无仓库口径背书），
若用户确认纳入，需走同一套“产品定义 → HS8 现行码核验 → 申万 L2/L3 映射 → GACC 采集”流程：

| 候选 | 代表公司/品类 | 现状 |
| :-- | :-- | :-- |
| 充电桩 | 特锐德/盛弘股份等 | 04 号文档曾有补码记录，现行无产品行 |
| 轴承 | 新强联/五洲新春/力星股份 | HS 8482 未入 catalog |
| 工业阀门 | 纽威股份/江苏神通/中核科技 | HS 8481 仅电子膨胀阀/减压阀 3 码 |
| 液压件 | 恒立液压/艾迪精密 | HS 8412/8413 未单列 |
| 燃气轮机 | 东方电气等 | HS 8411 未入 catalog |
| 拖拉机 | 一拖股份等 | heavy_truck 仅覆盖 8701 半挂牵引车子目 |
| 集装箱 | 中集集团 | HS 8609 未入 catalog |
| 港口机械 | 振华重工岸桥/场桥 | HS 8426 仅起重机代表码 |
| 工业电机/微电机 | 卧龙电驱/大洋电机 | HS 8501 仅汽车驱动电机段 |
| 半导体材料 | 光刻胶/电子特气/抛光材料 | catalog 仅设备+IC，材料层空白 |

## 7. 建议动作（执行状态：aquatic 恢复 + 清洁电器合并 + 校验固化已完成；其余待确认）

1. **消歧 108 池↔catalog（✅ 已执行）**：`aquatic_products` 已于 2026-10 恢复——
   `categories.csv` 新增 `agriculture_and_fishery`、`good_products.csv` 新增产品行、
   `good_h8_codes.csv` 新增 6 码（黄金表权威映射，L1 农林牧渔/L2 渔业/L3 水产养殖）、
   `gacc_query_codes.txt` 重生成。**未执行**：黄金表重刷（已决定月度 SOP 时随采集一起执行）。
2. **`ev_charger`（已决定暂缓）**：需外部税则核验 850440/8537 现行码后独立成产品或并入
   `inverter`/`power_cable`；当前 gold 0 行，列入待办。
3. **清洁电器码级对齐（✅ 已执行，用户确认合并）**：`robot_vacuum` 改映射 `85081100`
   （GACC 唯一报验粒度），`vacuum_cleaner` 并入 `robot_vacuum` 合并观察（description 留痕；
   移除 85081110/90、85081910/90 四个无效细分码）；混品告警 850811/850819 已消除。
4. **补采集 + 重建黄金表（月度 SOP 执行）**：按 `gacc_query_codes.txt`（1039 码）补齐
   catalog 有而黄金表无的 59 码（HS2027 27101925/26、HEV/PHEV 87035x/87036x/87037x
   拆分码、88062410/88062910、89013000/89019043、85021300、85176295、74031300 等）→
   重建黄金表 → 重跑 `customs_prosperity` 与公司 H8 链路（沿用 04 号文档解冻流程）；
   `robot_vacuum` 补采至最新月。
5. **外部候选**（§6）：暂缓，待税则核验能力可用后按优先级逐个确认。
6. **维护边界（✅ 已执行）**：`scripts/check_catalog.py` 新增 `--pool`（108 池↔catalog）
   与 `--gold`（黄金表↔catalog 双向 diff）检查，月度 SOP 运行时纳入；审计脚本
   `scripts/audit_customs_catalog_coverage.py` 可随时复跑。

## 8. 限制与依据

- **审计后已执行的变更（2026-10）**：① 恢复 `aquatic_products`（categories/good_products/
  good_h8_codes 三表）；② `robot_vacuum` 改映射 85081100、`vacuum_cleaner` 并入合并观察
  （移除 4 个无 GACC 报验粒度的细分码）；③ `gacc_query_codes.txt` 重生成（1039 leaf 码）；
  ④ `check_catalog.py` 新增 `--pool`/`--gold` 校验。**未执行**：黄金表重建（月度 SOP 时
  执行）、`ev_charger` 与外部候选（待税则核验）。本文档数字以恢复后文件为准。
- 税则核验结论引用 33 号文档（2026-10 i5a6/HSCIQ 抓取 + 已声明回退来源）；本次未对
  2026 税则逐码重新联网核验（检索端点当前不可用），2026 年内后续税则微调需在下次月度 SOP 复核。
- 黄金表现状以 2026-07 快照为准（实测 `customs_trade_gacc.parquet`：2016-01~2026-07、
  UN+GACC 混合驻留、197 个 hs6_* 历史键）——与 METHODOLOGY_FINAL §6.5/§7 所述
  “GACC 纯净 108 产品 / 631 税号 / 2019-01 起”不一致，文档口径或文件状态至少有一处
  过时，建议单独核对（影响“108 产品”回测口径的复现性，本文档按文件实测数字引用）。
- 中高端子集边界（§1/§4）为本审计口径假设，逐产品标注见脚本事实表，可按用户口径调整。
- 外部候选清单（§6）仅指出“不在 catalog”，未核实各品类海关出口额显著性及公司出口占比；
  其海关量价口径一律按仓库 SOP 走 Ground Truth First，不凭记忆补数。
