# 维护边界、数据质量限制与桥接规则

> 按需加载；内容提取自 [`04_data_gaps_and_repairs.md`](../../../../docs/research/customs_export_forward/04_data_gaps_and_repairs.md)
> 与 METHODOLOGY_FINAL §6.5/§7.5，完整证据链见出处文档。

## 维护边界（2026-09-12 重构为三表）

- **维护 3 个源文件**（`config/data/customs/`，拆自原 good_h8_codes.csv 宽表）：
  1. `categories.csv`——分类枚举（category_key → category_name，唯一；拼写漂移已修复：nonferrous_metals→non_ferrous_metals）；
  2. `good_products.csv`——产品主表（product_key 主键，product_name/category_key/description/L1/L2/L3 默认值，149 行，2026-10 恢复 aquatic_products）；
  3. `good_h8_codes.csv`——税号表（hs_code 主键 8 位，hs 码级字段 + product_key 外键 + 覆盖列 product_name/description/target_l3_*，空=继承产品主表默认值，1,044 行，2026-10 税则核验补全后）；
- **loader 内部 join 还原宽行**：`load_hs_catalog_rows` 按 product_key/category_key join 三表，下游消费方零改动；无 products/categories 时直读旧宽表（向后兼容测试 fixture）；
- **覆盖列语义**：税号行 product_name/description/target_l3_* 非空则覆盖产品主表默认值，空则继承——行级分化（如 coal 动力煤/焦煤、commercial_nev 载货/载客）保留在税号表覆盖列，不折叠丢失；
- **校验器**：`uv run python scripts/check_catalog.py`（引用完整性 + 码格式 + 混品品目告警），`--industry` 追加维度黄金表 L3 parent 断言；改表后先跑校验再重跑管线；
- **GACC 补导出清单**：catalog 已登记但 golden 无数据的码（需在海关官网按码导出）见 `data/analytics/industry/customs_export_backlog.csv`（当前 140 码）；导出后 `make import-customs-gacc` → `make replay-customs-gacc` → 重跑 `customs_prosperity`；
- **拆分/迁移工具**：`scripts/split_catalog.py`（dry-run 审计 + `--apply` 落盘 + 无损校验），旧宽表备份于 `data/backup/customs/`；
- **不再生成/维护 GACC 派生物**：`gacc_query_codes.txt` 由主表派生（`write_gacc_query_codes`），不手改；`gacc_code_catalog.csv` / `gacc_hs_codes.csv` / `gacc_hs_codes.txt` 已删除；
- 税号映射用"8 位精确 + 6 位前缀回退"（`load_hs_catalog` 由 8 位子行合成兜底），码只需归到产品即可。

## 数据质量限制（解读前必读，详见 METHODOLOGY_FINAL §7.5）

- **炼化及贸易**：HS2027 税则切换（旧码 27101911/23 → 新码 27101913/14/24）已对齐（2026-09-07），商品面板金额 yoy +48%（2026-07，L2 观察表口径 +47.9%，两口径并存）；L2/L3 量价列 NaN 系成品油 kg/l 混单位的行业级事实，商品面板 `refined_products::kg` 段有量价；景气判断仍以财报/价差口径为主（净利 TTM yoy +22.5% 已改善），且其 L2 一致率 A 属油价伪相关；
- `robot_vacuum` 上游税号采集缺口（覆盖止于 2026-05），不参与最新月信号；
- `hydrogen_electrolyzer` 单代码 ASP 伪影（价 +1443%、量 −88%）→ 行业聚合层（L2/L3 面板与观察表）量价已置空、仅金额可用（801733.SI/857336.SI 量价列为 NaN）；商品面板保留原始值供诊断；
- 低基数产品（methanol/ethylene_glycol/zinc 等）量 yoy >300%（2026-07：+1071%/+553%/+319%）需标注"低基数高增长"；compound_fertilizer 量 yoy 已转 −97%（2026-07），退出该列表；
- **phev 柴油版（870370）细分断裂**：catalog 原仅登记已作废父级码 87037000，2026-09-08 已补 12 个现行税则细分（87037011/12/13/19/21/22/23/29/31/32/33/39）并已补进主表；870370 系按 hscIQ 官方口径为"可接插外部电源充电"柴油混动，2026-09 已从 hev 改挂 phev（与 870360 汽油 PHEV 同轴）；但海关整包导出中 870370 系记录极稀少：**2025 整包仅 4 条合计 9 辆（码 87037023/33），2026 整包无任何记录**——近端柴油 PHEV 外需不可见属"出口极稀少"而非采集遗漏——待官网有数据后按主表码自动入库；整包中实际出现的 87037023/33 已由 catalog 码对齐一并登记。
- **电网设备（变压器 85042100）数量污染（2026-10 已修复）**：Comtrade 段 2024-06~09 印度/土耳其/孟加拉单位错位申报曾把月度数量放大至 50 万台（真实约 1.6-3 万），ETL 已加通用剔除规则（详见下方"单位错位申报"节）；修复后 2025-06~09 量价 yoy 恢复正常，当前观察表读数可信。
- **电池隔膜补码（2026-09-12）**：海关为电池隔膜设专门 8 位子目 `39201010`（乙烯聚合物制）与 `39202010`（丙烯聚合物制），已补入 `battery_separator`（原仅有 39211990 泡沫塑料兜底，覆盖差）；注意 2025-01 起的 GACC 月度数据需在海关官网按这两个码补导出导入后才会进入观察表（raw 历史无此码）。核验确认：铜箔 `74101100`/蓄电池零件 `85079010+90` 已准确无需补；锂电池 8 位层面仅 `85076000` 一个主码；`760711` 轧制铝箔归通用 `aluminum_foil`（与 `battery_aluminum_foil` 挂的 76071900 分属产品边界，不重复挂）。
- **元件链补码与归属修正（2026-09-12）**：`mlcc` 由旧码 85322400 改为现行码 `85322410`（片式多层瓷介电容器）；`optical_connector` 原挂 85369011（实为电接插件）改为 `85367000`（光导纤维连接器正码），85369011 移交 `electronic_connector`；`electronic_connector` 补齐 `85369011+85369019+85369090`（电连接器族）；`inductor`(85045000)/`pcb`(85340010+90) 核验无需补。**数据缺口**：元件链这些码（含原有 85366900/85045000）在 GACC raw 从未导出、golden 无数据——元件 L2 出口观察目前实际仅 pcb 单产品支撑，需按码在海关官网补导出（85322410/85367000/85369011/85369019/85369090/85045000/85366900）后重放。
- **P1 电网/音频补码（2026-09-12）**：`circuit_breaker` 由 2 码扩到 10 码——旧码 85352900 替换为现行 85352910/85352920/85352990（72.5/220/750kV 三档自动断路器），补 85351000（熔断器）/85353010/85353020/85353090（隔离开关）/85354000（避雷器）/85359000（其他）——8535 全系 GACC 无数据需补导出；`audio_device` 由 1 码扩到 5 码，补 85181000（麦克风）/85182100+85182200+85182900（音箱扬声器），其中 85183000（耳机）GACC 有数据（127 月）。核验无需补：`wind_turbine`（85023100 唯一码）、`wheel_loader`(84295100)/`aerial_work_platform`(84289090 兜底)、医疗器械（90213100/90181930/90219011/30021500 均为精确码）。
- **储能/燃料电池/电解液归属修正（2026-09-12）**：`85078030`（全钒液流）与 `85078090`（其他蓄电池/钠电/固态）从 `fuel_cell` 移交 `battery`（储能归属，battery 现为 85076000+85078030+85078090 的完整"锂电与储能"代理）；`fuel_cell` 因此**无 8 位可用码**（燃料电池真实所在品目 850131-850134 与普通直流电机共用、且已被 auto_drive_motor 占用，无独立代理）——燃料电池退出海关出口观察，与快周期商品排除同理；`battery_electrolyte` 删除 `38249993`（表面包覆钴化物的氢氧化镍——镍氢正极前驱体，非电解液），仅留 `38249999` 兜底（该兜底混入面大，出口 47B USD 含大量非电解液化学品，电解液信号需按"混入风险"定性）。
- **P2 非主线补码（2026-09-12）**：`uav_drone` 由 2 码扩到 10 码——补 880622/880623/880624/880629 各重量档（250g-7kg 紧凑档为大疆主力出口段）；`refrigeration_compressor` 由 2 码扩到 6 码——补 84143012/13/14/15（0.4kW-5kW 及 >5kW 空调/冷冻档）；`compound_fertilizer` 由 1 码扩到 4 码——补 31055100/31055900/31056000（硝酸盐磷/氮磷/磷钾二元复合肥；磷酸铵 31053000+31054000 归 `phosphate_fertilizer` 不重复挂）；`bicycle` 由 1 码扩到 7 码——补 87120020/41/49/81/89/90（竞赛/越野/其他脚踏车）。核验无需补：`rare_earth_magnet`（85051110 稀土永磁专属码）、`elevator`(84281010+84284000)、`lawn_mower`(84331100)、`injection_molding_machine`(84771010)、`fracturing_equipment`(84135030 无专门码)、`industrial_sewing_machine`(84522110+84522900)、`technical_ceramic`(69091100)、`thermal_expansion_valve`(84818040 无专门码)、`robot_vacuum`(85081100)。

- **catalog 补码后采集缺口（33 号 §7.2，2026-10）**：catalog 1,044 码中新增 275 码
  **尚未在 GACC raw 查询过**（raw 仅 626 码有数据）；黄金表另缺 59 码待补采
  （HS2027 27101925/26、HEV/PHEV 87035x/87036x/87037x 拆分码、88062410/88062910 等）。
  下次 GACC 采集按 `gacc_query_codes.txt`（1,039 码）执行后重建黄金表、重跑
  `customs_prosperity` 与公司 H8 链路（沿用 04 号文档解冻流程）。
**处置原则**（§7.5 强制）：**有问题的产品标注问题本身**，不用"金额 yoy 替代量价"或删行掩盖；HS 口径类问题修复落点是数据层（税号级重对齐），不通过改面板数字。

## 税则切换 / 数据冻结解冻处置流程（04 §4 + §7.5 炼化 SOP）

**成因**：Comtrade 采集止于 2024-12，2025+ 数据 100% 来自 GACC 回放；catalog 是唯一维护源，raw 导出文件不回写目录。

**解冻/切码 SOP**（遇 2025+ 数据缺失或税则切换时执行）：

1. 按现行税则确认产品的 8 位现行码（警惕 HS2017→2022 拆并，如疫苗 300220→300241；870370 柴油插电混动 2026-09 已按官方口径归 phev，合并复核时注意与 870360 汽油 PHEV 分轴）；
2. 只在税号表 `good_h8_codes.csv` 新增/修正 8 位码行（写 hs 码级字段 + product_key，
   覆盖列留空即继承产品默认）；**新产品先**在 `good_products.csv` 加产品行
   （category_key 须在 categories.csv 枚举内）；现行和历史 H8 均进入 GACC 查询清单，
   `description` 历史标记仅说明税则口径、不作排除条件，显式 `gacc_active=0` 仍可排除指定编码；
3. 按主表 8 位码在海关官网人工查询下载 CSV 入 `data/raw/industry/customs/gacc/export/`；
4. `gacc_collector` 回放刷新 curated → 重跑 4 个 build 脚本；
5. 历史码处置：官网查 6 位无编码 = 历史码 → 找现行替代码（同品名/同 6 位前缀整包现有码，或税则核验），替代码近端有数据即可结案；历史码保留于主表并进入 GACC 查询清单。

**唯一信任源**：三表 `categories.csv` / `good_products.csv` / `good_h8_codes.csv`（全 8 位主键，含现行与历史码）；GACC 采集运行时按主表 `derive_gacc_code_catalog()` 内存派生，不落盘派生文件。现行码和历史码有效性均靠海关查询确认（人工下载是流程固有人工环节）。

## 品目污染与错位修复记录（04 §6，防复发规则）

- **851762 品目污染（2026-10 修复）**：`851762` 是混合品目（光通讯 21/22/29、网络设备 31~39/92/93/99、无线耳机 94 显式归消费电子 801085.SI/850853.SI、电话交换机 11/12/19），原单一 8 位码 h6 前缀回挂把整品目历史段继承为光模块、污染通信设备/消费电子两个 L2。已拆 18 个 8 位码（6 位父行已随全面 8 位码化删除，6 位历史段由 8 位子行合成兜底）——**跨行业混品品目必须显式拆分**，未来若出现新混品（如 850440 内充电桩变流器 vs 光伏逆变器分家）按此流程拆分；
- **单位映射缺口（2026-10 修复）**：Comtrade 段 HS 计量单位代码（`u`/`l`/`m²`/`条`）补进 `UNIT_CANONICAL` 后 94/106 产品数量可加总（修复前 1/106）；真混用剩 12 个（半导体设备/PCB/轮胎 kg vs units 等）数量置空、金额照常计入；注意黄金表 `quantity_unit_norm`/`unit_known`/`volume_aggregable` 三列仍为旧口径，量价面板脚本自行重算；
- **L1 残留错位（2026-10 修复）**：6 行 L1 列残留错位（叉车/挖掘机/电动工具挂 801710.SI 建筑材料，应为 801890.SI 机械设备）——名称列正确时代码可能仍错，需逐码核对；
- **复用校验工具（防复发）**：`scratch/check_catalog_mapping_alignment.py`（L1/L2/L3 代码存在性+名称一致性+h6/h8 挂载一致性）、`scratch/check_fallback_mapping.py`（主表兜底挂载跨行业错挂扫描）、`scratch/refresh_catalog_mapping.py`（catalog 修改后标准重刷入口）；
- **兜底挂载核验结论**：主表 474 个 catalog 未维护的真实细分码走 6 位前缀兜底，全量扫描无真实跨行业错挂，**不需要批量补行**；主表聚合用"8 位精确 + 6 位前缀回退"（6 位前缀由 8 位子行合成兜底），避免 double count。

## 单位错位申报与 ETL 通用规则（85042100 变压器案例，2026-10 修复）

**根源**：Comtrade 源申报中部分国家按错误单位/数量级上报（数量巨大 × 金额微小），
非本地聚合 bug、GACC 段无此问题。**特征 = 单行数量 >1 万 且 ASP 远低于该 hs8 码正常中位数**
（85042100 正常 ASP 中位约 $3,050/台，污染行 ASP $0.001-1.4）。

- **污染行分布**：全周期 29 条（2018-2023 印度/台湾/沙特/韩国等零星，2024-06~09 集中：
  印度 48.75 万台/$588、土耳其 10 万台/$2,808、印度 20.07 万台/$90,948、孟加拉
  20.01 万台/$275,711、孟加拉 30.06 万台/$52,281）；
- **失效机制**：错位行数量参与月度聚合（撑起该月数量 86-97%）→ 作为 lag12 分母把
  2025-06~09 的量 yoy 打成 −86%~−92%、价 yoy（金额/数量）打成 +900%~+2000% 假"价驱动"；
  金额几乎不受影响（污染行金额仅占月度 0.002%），2026 年读数干净（分母为 2025 实际值）；
- **修复（ETL 通用规则，非定点）**：`tariffline_gold_loader.py` 聚合前先统计各 hs8 码
  u 单位 ASP 中位数（样本 ≥3），命中**u 单位（非 kg）+ 码中位数 ≥$500 + 单行数量 >1 万 +
  行 ASP < 中位数/100** 的行数量剔除、金额保留；实测剔除 307 行 / 2,120 万单位；
  规则仅作用于 u 单位（kg 计量商品如服装/底盘/肝素不适用，防误伤）；已加单测
  `test_tariffline_gold_drops_unit_shift_volume_keeps_value` / `_keeps_low_asp_code_untouched`；
- **验证**：85042100 2024-06 数量 50.5 万 → **1.66 万**（与 2025 的 1.1-3.5 万/月自然衔接）；
  电网设备 2025-06 价 yoy **+925.98% → +6.5%**、2025-08 +2092% → +22.6%，驱动类型恢复合理；
  4 个 build 脚本重跑后观察表 2026-07 读数不变（量 −10.5%、价 +49.9%、价驱动，本就干净）；
- **未纳入本次规则（残留）**：汽车底盘系统（45 个映射码全 kg）2025-03 起量 yoy −76%~−80%
  持续 10 个月——kg 口径跨源差异或个别 kg 码申报问题，独立问题待单独排查；
- **合规**：修复落点是数据层（ETL 清洗），符合"有问题的产品标注问题本身、不删行掩盖"原则
  （§7.5）；金额全程保留，仅剔除不可信数量。

## 公司下沉资产维护（2026-10 更新；细节以本 skill 操作手册 company_linkage.md 与 docs 方法论定稿为准）

- **公司下沉不再维护旧双表**：`company_exposure_map.csv` / `bz_item_alias_map.csv`
  已于 2026-09 移除（旧链 calibrate/customs_company 待下线）；人工修正收敛为
  **单表 `company_segment_binding.csv`**（binding + override 一表两用，144 行，
  其中 59 行带 exposure override；binding-only 行 exposure 空；override 段必须 ⊆
  同(产品,公司) binding 段，loader 校验段错位即报错）；
- **段定义表 `taxline_segments.csv`**——税号段定义（**31 段 / 12 产品**），新增段须人工审计
  （hs 码互斥、单位一致），不经 LLM 自动生成；2026-09-13 恢复版段行待人工复核；
- **主消费方**：`src/stock_analytics/marts/customs_company_h8.py`（Mart 构建 +
  `_load_segment_binding` / `_validate_override_segments` / `_attach_segment`）——
  改动任一 CSV 后重跑 H8 Mart 与
  `tests/unit/stock_analytics/marts/test_customs_company_h8.py`，不静默漂移；
- 产物路径：`data/curated/mart/customs_company_product_mapping.parquet` /
  `customs_company_h8_exposure.parquet`（2026-10 储能修复后重建 348,713 行 / 1,045 家 / 104 产品）、
  `data/analytics/industry/customs_company_h8_product_panel.parquet` /
  `customs_company_h8_signal.parquet`（三层信号 A/B/C/D/回避 评级）。

### 信号/回测脚本（结论口径见 METHODOLOGY_COMPANY_FINAL §5-6、§8）

- `stock_cli.customs_company_h8 --with-signal`（H8 主链）→ `customs_company_h8_signal_latest.csv`：
  三层信号（出口段级 × 资金 moneyflow/margin_detail × 财报 fina_indicator）→ A/B/C/D/回避 评级；
  实现见 `src/stock_analytics/pipelines/customs_company_h8/`；
- `backtest_customs_company_signal.py` / `backtest_customs_multi.py` →
  `customs_signal_backtest*.parquet` / `customs_signal_multi.parquet`：研究验证工具，
  当前默认路径仍指已删除的 `company_exposure_map.csv`（旧链断，仅结论保留、待改指 H8）；
- 信号口径与回测结论（含普适性局限）固化在
  `docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md` §5-6、§8
  （操作细节见 `company_linkage.md`），**改动口径
  （确认月数/质量门/三腿阈值）需同步更新该文档并重跑回测**。

## 桥接强制规则（L2/L3，2026-09 审计 + §6.5 定稿）

- 映射唯一源 `config/data/customs/good_h8_codes.csv`（1,044 行 / 149 产品，全 8 位主键）；raw 不含映射；
- 指数码 ↔ 行业码一律走维度黄金表（`sw_2021_industry_dimension_golden`，derived 数据集），禁止手工猜匹配；
- **L3 归属断言**：`parent_code == 该行 L2 industry_code`，不一致即报错，不静默产出；
- **组合码（`;` 多映射行）在行业聚合中跳过**（`801033.SI;801034.SI` 化学原料;化学制品、
  `tio2` 钛白粉，组合码行随 catalog 更新，当前主表 1,044 行），报告披露被跳过产品与规模；
- **空映射行**：L2/L3 映射任一为空的产品行，行业级面板剔除并在报告标注（当前 L3 无空值，防御规则）；
- **复用校验函数**：`stock_data.fetcher.industry.customs.parsers.catalog` 或
  `src/stock_analytics/pipelines/customs_prosperity/product_panel.validate_bridge`
  的 bridge/join 逻辑不在新脚本中复制，统一 import（防口径漂移）；
- 审计基线：L3 73/73 存在、归属 109/109 一致（curated hs8 出口层）；L3 归属断言**单点内置于
  `pipelines/customs_prosperity/product_panel.validate_bridge`**（parent_code == L2 码，
  不一致即报错，不静默产出），上游金额/量价/观察表面板均经其校验；新增脚本沿用该口径
  （§6.5 规则 6：校验逻辑不在脚本间复制，统一复用）。
