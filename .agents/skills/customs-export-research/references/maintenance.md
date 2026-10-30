# 维护边界、数据质量限制与桥接规则

> 按需加载；内容提取自 [`04_data_gaps_and_repairs.md`](../../../../docs/research/customs_export_forward/04_data_gaps_and_repairs.md)
> 与 METHODOLOGY_FINAL §6.5/§7.5，完整证据链见出处文档。
> **规模类数字一律以实测为准，不在此固化**：税号行数看 `uv run python scripts/check_catalog.py`，
> CSV 行数 = `wc -l` 减表头，Mart/面板行数看最新 Manifest。

## 维护边界（当前）

- **维护 3 个源文件**（`config/data/customs/`）：
  1. `categories.csv`——分类枚举（category_key → category_name，唯一）；
  2. `good_products.csv`——产品主表（product_key 主键，L1/L2/L3 默认值；**行数以 CSV 行数减表头为准**）；
  3. `good_h8_codes.csv`——税号表（hs_code 主键 8 位，product_key 外键 + 覆盖列；**行数以 CSV 行数减表头为准**）；
- **loader 内部 join 还原宽行**：`load_hs_catalog_rows` 按 product_key/category_key join 三表，下游消费方零改动；
- **覆盖列语义**：税号行覆盖列（product_name/description/target_l3_*）非空则覆盖产品默认值，空则继承——保留行级分化，不折叠丢失；
- **校验器**：`uv run python scripts/check_catalog.py`（引用完整性 + 码格式 + 混品品目告警），`--industry` 追加维度黄金表 L3 parent 断言；改表后先跑校验再重跑管线；
- **GACC 补导出清单**：catalog 已登记但 golden 无数据的码见 `data/analytics/industry/customs_export_backlog.csv`
  （catalog − golden 差集派生，**行数随采集进度变化，以文件行数减表头为准**）；导出后 `make import-customs-gacc` → `make replay-customs-gacc` → 重跑 `customs_prosperity`；
- **拆分/迁移工具**：`scripts/split_catalog.py`（dry-run 审计 + `--apply` 落盘 + 无损校验），旧宽表备份于 `data/backup/customs/`；
- **GACC 派生物不手改**：`gacc_query_codes.txt` 由主表派生（`write_gacc_query_codes`），数量以文件首行自述为准；
- 税号映射用"8 位精确 + 6 位前缀回退"（`load_hs_catalog` 由 8 位子行合成兜底）。

## 表职责（纯 GACC）

- `customs_trade_gacc.parquet` 只存 GACC 官方行（source=GACC，hs8）；UN Comtrade 数据（含 Tariffline
  物化输出）一律写入 `customs_trade.parquet`，不得再写入 GACC 表。

## 数据质量限制（解读前必读；详见 METHODOLOGY_FINAL §7.5）

- **炼化及贸易**：HS2027 税则切换已对齐；L2/L3 量价列 NaN 系成品油 kg/l 混单位的行业级事实
  （商品面板 `refined_products::kg` 段有量价）；景气判断以财报/价差口径为主，其 L2 一致率 A 属油价伪相关；
- **`robot_vacuum` 采集缺口**（以 golden 实测为准），不参与最新月信号；
- **`hydrogen_electrolyzer` 单代码 ASP 伪影** → 行业聚合层（L2/L3 面板与观察表）量价已置空、仅金额可用；商品面板保留原始值供诊断；
- **低基数产品**（methanol/ethylene_glycol/zinc 等）量 yoy 高增需标注"低基数高增长"，不当作趋势强度；
- **phev 柴油版（870370）**：现行税则细分已补入主表（87037011~39），按 hscIQ 口径归 phev；整包记录极稀少属"出口极稀少"而非采集遗漏（以 golden/整包实测为准）；
- **处置原则**（§7.5 强制）：有问题的产品标注问题本身，不用"金额 yoy 替代量价"或删行掩盖；修复落点是数据层（税号级重对齐），不通过改面板数字。

> 历史修复记录（851762 品目拆分、变压器 85042100 单位错位、元件链/P1/P2 补码、储能/电解液归属修正、catalog 补码缺口等）
> 见 `04_data_gaps_and_repairs.md` 与 33/34 号审计文档，不在本文件复制。

## 税则切换 / 数据冻结解冻处置流程（04 §4 + §7.5 炼化 SOP）

**成因**：数据源统一 GACC 黄金表（`customs_trade_gacc.parquet`，source=GACC 2018-01 起）；catalog 是唯一维护源，raw 导出文件不回写目录。

**解冻/切码 SOP**（遇数据缺失或税则切换时执行）：

1. 按现行税则确认产品的 8 位现行码（警惕 HS2017→2022 拆并，如疫苗 300220→300241）；
2. 只在税号表 `good_h8_codes.csv` 新增/修正 8 位码行（覆盖列留空即继承产品默认）；**新产品先**在 `good_products.csv` 加产品行（category_key 须在 categories.csv 枚举内）；
3. 按主表 8 位码在海关官网人工查询下载 CSV 入 `data/raw/industry/customs/gacc/export/`；
4. `gacc_collector` 回放刷新 curated → 重跑 4 个 build 脚本；
5. 历史码处置：官网查 6 位无编码 = 历史码 → 找现行替代码（同品名/同 6 位前缀整包现有码，或税则核验），替代码近端有数据即可结案；历史码保留于主表并进入 GACC 查询清单。

**唯一信任源**：三表 `categories.csv` / `good_products.csv` / `good_h8_codes.csv`（全 8 位主键，含现行与历史码）；GACC 采集运行时按主表 `derive_gacc_code_catalog()` 内存派生。现行码和历史码有效性均靠海关查询确认（人工下载是流程固有人工环节）。

## 桥接强制规则（L2/L3，§6.5 定稿）

- 映射唯一源 `config/data/customs/good_h8_codes.csv`（全 8 位主键；**行数随 catalog 变化，以 CSV 行数减表头为准**）；raw 不含映射；
- 指数码 ↔ 行业码一律走维度黄金表（`sw_2021_industry_dimension_golden`，derived 数据集），禁止手工猜匹配；
- **L3 归属断言**：`parent_code == 该行 L2 industry_code`，不一致即报错，不静默产出；
- **组合码（`;` 多映射行）在行业聚合中跳过**（`801033.SI;801034.SI`、`tio2` 钛白粉），报告披露被跳过产品与规模；
- **空映射行**：L2/L3 映射任一为空的产品行，行业级面板剔除并在报告标注（防御规则）；
- **复用校验函数**：catalog 解析 与 `product_panel.validate_bridge` 的 bridge/join 逻辑不在新脚本中复制，统一 import 现有实现（防口径漂移；实现以代码为准）；
- 审计基线：L3 存在性与归属一致性以最近一次审计为准；L3 归属断言**单点内置于 `product_panel.validate_bridge`**（不一致即报错，不静默产出），上游金额/量价/观察表面板均经其校验；新增脚本沿用该口径（§6.5 规则 6：校验逻辑不在脚本间复制，统一复用）。
