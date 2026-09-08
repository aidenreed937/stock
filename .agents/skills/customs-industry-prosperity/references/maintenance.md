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

## 桥接强制规则（L2/L3，2026-09 审计 + §6.5 定稿）

- 映射唯一源 `config/data/customs/hs_codes_catalog.csv`（400 行 / 109 产品，2026-09-08 完成 catalog 码对齐：旧"00 补齐父级码"替换为 277 个 hs8 现行税则细分码，其中 248 个有自身 8 位数据）；raw 不含映射；
- 指数码 ↔ 行业码一律走维度黄金表（`sw_2021_industry_dimension_golden`，derived 数据集），禁止手工猜匹配；
- **L3 归属断言**：`parent_code == 该行 L2 industry_code`，不一致即报错，不静默产出；
- **组合码（`;` 多映射行）在行业聚合中跳过**（`801033.SI;801034.SI` 化学原料;化学制品、
  `tio2` 钛白粉，主表 786 行），报告披露被跳过产品与规模；
- **空映射行**：L2/L3 映射任一为空的产品行，行业级面板剔除并在报告标注（当前 L3 无空值，防御规则）；
- **复用校验函数**：`stock_data.fetcher.industry.customs.parsers.catalog` 或 `build_customs_export_prosperity.py` 的 bridge/join 逻辑不在新脚本中复制，统一 import（防口径漂移）；
- 审计基线：L3 73/73 存在、归属 109/109 一致（curated hs8 出口层）；L3 归属断言**单点内置于 `build_customs_product_volume_price.py`**（parent_code == L2 码，不一致即报错，不静默产出），上游金额/量价/观察表面板均经其校验；新增脚本沿用该口径（§6.5 规则 6：校验逻辑不在脚本间复制，统一复用）。
