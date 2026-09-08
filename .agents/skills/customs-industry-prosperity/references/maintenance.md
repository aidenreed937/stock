# 维护边界、数据质量限制与桥接规则

> 按需加载；内容提取自 [`04_data_gaps_and_repairs.md`](../../../../docs/research/customs_export_forward/04_data_gaps_and_repairs.md)
> 与 METHODOLOGY_FINAL §6.5/§7.5，完整证据链见出处文档。

## 维护边界（2026-09-08 定稿）

- **只需维护 2 个文件**：
  1. `config/data/customs/hs_codes_catalog.csv`——产品→L1/L2/L3 映射唯一源（400 行 / 109 产品）；
  2. `config/data/customs/gacc_hs_codes_tariffline_candidates.txt`——**全量查询清单（645 码）**，GACC 官网查询 2025+ 近端数据的唯一依据；新增出口商品（2025 税则新码等）查证后手工 append，**勿重跑 `scripts/extract_tariffline_hs8_candidates.py`（会全量覆盖，仅作初始生成器）**；
- 不再维护（派生物，已 gitignore）：`gacc_code_catalog.csv` / `gacc_hs_codes.csv` / `gacc_hs_codes.txt`——由 `make rebuild-customs-catalog` 从 catalog 派生，仅供开发对照，不作为官网查询清单；
- 645 码的 L3 归属**不需要逐码维护**：catalog 双索引（8 位精确 + 6 位前缀回退）已覆盖全部 645 码（实测 248 精确 + 397 回退，0 无法解析），码只需归到产品即可；
- **645 码含 73 个历史码（2026-09-08 官网实测完证）**：A 9 历史父级 + B 64 改码，GACC 整包无记录属正常——**官网查询时跳过，勿当采集遗漏**；645 = 572 已有数据 + 73 历史码，断点零待查；鉴别与处置规则见 04 §7，证据档 `data/analytics/industry/gacc_73_broken_review.csv`。

## 数据质量限制（解读前必读，详见 METHODOLOGY_FINAL §7.5）

- **炼化及贸易**：HS2027 税则切换（旧码 27101911/23 → 新码 27101913/14/24）已对齐（2026-09-07），商品面板金额 yoy +48%（2026-07，L2 观察表口径 +47.9%，两口径并存）；L2/L3 量价列 NaN 系成品油 kg/l 混单位的行业级事实，商品面板 `refined_products::kg` 段有量价；景气判断仍以财报/价差口径为主（净利 TTM yoy +22.5% 已改善），且其 L2 一致率 A 属油价伪相关；
- `robot_vacuum` 上游税号采集缺口（覆盖止于 2026-05），不参与最新月信号；
- `hydrogen_electrolyzer` 单代码 ASP 伪影（价 +1443%、量 −88%）→ 行业聚合层（L2/L3 面板与观察表）量价已置空、仅金额可用（801733.SI/857336.SI 量价列为 NaN）；商品面板保留原始值供诊断；
- 低基数产品（methanol/ethylene_glycol/zinc 等）量 yoy >300%（2026-07：+1071%/+553%/+319%）需标注"低基数高增长"；compound_fertilizer 量 yoy 已转 −97%（2026-07），退出该列表；
- **hev 柴油混动（870370）细分断裂**：catalog 原仅登记已作废父级码 87037000，2026-09-08 已补 12 个现行税则细分（87037011/12/13/19/21/22/23/29/31/32/33/39）并重建 GACC 查询清单；但海关整包导出中 870370 系记录极稀少：**2025 整包仅 4 条合计 9 辆（码 87037023/33），2026 整包无任何记录**——近端柴油 PHEV 外需不可见属"出口极稀少"而非采集遗漏——待官网有数据后按新清单自动入库；整包中实际出现的 87037023/33 已由 catalog 码对齐一并登记。
- **电网设备（变压器 85042100）数量污染（2026-10 已修复）**：Comtrade 段 2024-06~09 印度/土耳其/孟加拉单位错位申报曾把月度数量放大至 50 万台（真实约 1.6-3 万），ETL 已加通用剔除规则（详见下方"单位错位申报"节）；修复后 2025-06~09 量价 yoy 恢复正常，当前观察表读数可信。

**处置原则**（§7.5 强制）：**有问题的产品标注问题本身**，不用"金额 yoy 替代量价"或删行掩盖；HS 口径类问题修复落点是数据层（税号级重对齐），不通过改面板数字。

## 税则切换 / 数据冻结解冻处置流程（04 §4 + §7.5 炼化 SOP）

**成因**：Comtrade 采集止于 2024-12，2025+ 数据 100% 来自 GACC 回放；catalog 是唯一维护源，raw 导出文件不回写目录。

**解冻/切码 SOP**（遇 2025+ 数据缺失或税则切换时执行）：

1. 按现行税则确认产品的 8 位现行码（警惕 HS2017→2022 拆并，如疫苗 300220→300241；HEV 870370 有合并风险需复核）；
2. 只在 `hs_codes_catalog.csv` 新增/修正主表行；若编码对 Comtrade 是历史码、但对 GACC 当前税则有效，加 `gacc_active=1`；
3. 新码查证后 **append 进 `gacc_hs_codes_tariffline_candidates.txt`**（勿重跑初始生成器）；
4. 按 candidates 645 码清单在海关官网人工查询下载 CSV 入 `data/raw/industry/customs/gacc/export/`；
5. `gacc_collector` 回放刷新 curated → 重跑 4 个 build 脚本；
6. 历史码处置：官网查 6 位无编码 = 历史码 → 找现行替代码（同品名/同 6 位前缀整包现有码，或税则核验），替代码近端有数据即可结案；candidates 保留历史码（Comtrade 段续接需要）但官网查询时跳过，不从清单删除。

**生成链唯一入口**：`hs_codes_catalog.csv`（含 `gacc_active` 标记）→ `src/stock_data/fetcher/industry/customs/parsers/gacc_catalog.py` 的 `write_gacc_code_catalog()` 重建 `gacc_code_catalog.csv`（派生逻辑在 `derive_gacc_code_catalog()`）→ `scripts/extract_gacc_hs_codes.py` 导出 `gacc_hs_codes.csv`/`.txt`。不能全自动的两类：6 位码无法派生（品目细分未知）、现行码有效性靠海关查询确认（人工下载是流程固有人工环节）。

## 品目污染与错位修复记录（04 §6，防复发规则）

- **851762 品目污染（2026-10 修复）**：`851762` 是混合品目（光通讯 21/22/29、网络设备 31~39/92/93/99、无线耳机 94 显式归消费电子 801085.SI/850853.SI、电话交换机 11/12/19），原单一 8 位码 h6 前缀回挂把整品目历史段继承为光模块、污染通信设备/消费电子两个 L2。已拆 18 个 8 位码 + 保留 1 个 6 位父行（`comm_equipment_mixed` 仅作 h6 聚合载体）——**跨行业混品品目必须显式拆分**，未来若出现新混品（如 850440 内充电桩变流器 vs 光伏逆变器分家）按此流程拆分；
- **单位映射缺口（2026-10 修复）**：Comtrade 段 HS 计量单位代码（`u`/`l`/`m²`/`条`）补进 `UNIT_CANONICAL` 后 94/106 产品数量可加总（修复前 1/106）；真混用剩 12 个（半导体设备/PCB/轮胎 kg vs units 等）数量置空、金额照常计入；注意黄金表 `quantity_unit_norm`/`unit_known`/`volume_aggregable` 三列仍为旧口径，量价面板脚本自行重算；
- **L1 残留错位（2026-10 修复）**：6 行 L1 列残留错位（叉车/挖掘机/电动工具挂 801710.SI 建筑材料，应为 801890.SI 机械设备）——名称列正确时代码可能仍错，需逐码核对；
- **复用校验工具（防复发）**：`scratch/check_catalog_mapping_alignment.py`（L1/L2/L3 代码存在性+名称一致性+h6/h8 挂载一致性）、`scratch/check_fallback_mapping.py`（主表兜底挂载跨行业错挂扫描）、`scratch/refresh_catalog_mapping.py`（catalog 修改后标准重刷入口）；
- **兜底挂载核验结论**：主表 474 个 catalog 未维护的真实细分码走 6 位前缀兜底，全量扫描无真实跨行业错挂，**不需要批量补行**；主表聚合需"8 位优先、6 位行不叠加"，避免 double count。

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

## 公司下沉资产维护（2026-09 新增，见 company_linkage.md）

- **3 个新文件纳入维护**（不再是"只需维护 2 个文件"的例外，属公司层链路）：
  1. `config/data/customs/company_exposure_map.csv`——109 产品 → 393 公司暴露度；
     `status=verified`（fina_mainbz 校准）/ `estimated`（人工估计）；`taxline_segment` 列绑定段，空=整产品；
  2. `config/data/customs/taxline_segments.csv`——税号段定义（14 段/5 产品），新增段须人工审计
     （hs 码互斥、单位一致），不经 LLM 自动生成；
  3. `config/data/customs/bz_item_alias_map.csv`——LLM 语义别名表（1395 条），`bz_item` → product_key；
- **别名表再生成**：fina_mainbz 新报告期 → 提取每公司最新期 bz_item → LLM 批量归一化 →
  合并校验（product_key 必须为 catalog 键、条数全覆盖）→ 落盘后重跑
  `scripts/calibrate_company_exposure.py` 与 `scripts/build_customs_company_exposure.py`；
- **段引用非法即报错**：公司 `taxline_segment` 不在段定义表时 loader 直接 ValueError，防手误静默失效；
- **消费方唯一**：`calibrate_company_exposure.py`（exposure 校准）+ `build_customs_company_exposure.py`
  （公司观察表）——改动任一 CSV 后重跑两者验证，不静默漂移；
- 产物路径：`data/analytics/industry/customs_company_exposure.parquet`（全序列）/
  `customs_company_exposure_latest.csv`（最新月公司快照，含 segment_minus_product 区分度列）。

## 桥接强制规则（L2/L3，2026-09 审计 + §6.5 定稿）

- 映射唯一源 `config/data/customs/hs_codes_catalog.csv`（400 行 / 109 产品，2026-09-08 完成 catalog 码对齐：旧"00 补齐父级码"替换为 277 个 hs8 现行税则细分码，其中 248 个有自身 8 位数据）；raw 不含映射；
- 指数码 ↔ 行业码一律走维度黄金表（`sw_2021_industry_dimension_golden`，derived 数据集），禁止手工猜匹配；
- **L3 归属断言**：`parent_code == 该行 L2 industry_code`，不一致即报错，不静默产出；
- **组合码（`;` 多映射行）在行业聚合中跳过**（`801033.SI;801034.SI` 化学原料;化学制品、
  `tio2` 钛白粉，主表 786 行），报告披露被跳过产品与规模；
- **空映射行**：L2/L3 映射任一为空的产品行，行业级面板剔除并在报告标注（当前 L3 无空值，防御规则）；
- **复用校验函数**：`stock_data.fetcher.industry.customs.parsers.catalog` 或 `build_customs_export_prosperity.py` 的 bridge/join 逻辑不在新脚本中复制，统一 import（防口径漂移）；
- 审计基线：L3 73/73 存在、归属 109/109 一致（curated hs8 出口层）；L3 归属断言**单点内置于 `build_customs_product_volume_price.py`**（parent_code == L2 码，不一致即报错，不静默产出），上游金额/量价/观察表面板均经其校验；新增脚本沿用该口径（§6.5 规则 6：校验逻辑不在脚本间复制，统一复用）。
