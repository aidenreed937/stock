# DataCatalog 路由安全修复方案

> 状态：实施中（P0/P1、静态门禁和主审计存储角色已完成）
>
> 目标：避免历史物理目录、项目任务名和上游 API 名并存时，人工巡检、审计或分析读取到非运行时事实，进而误判数据缺口、最新水位或基准对齐状态。

## 1. 问题定性

本次误判的根因不是 `index_daily_bar` 数据没有更新，而是核查绕过了项目的事实入口，直接读取了旧物理目录：

- 项目任务名是 `index_daily_bar`，上游 API 名是 `index_daily`；二者由任务解析层和 `TaskSpec` 解耦。
- `StorageCompat.canonical_dataset_name("index_daily", "tushare")` 返回 `index_daily_bar`。
- `DataCatalog.load_dataset("index_daily")` 会解析到规范数据集，并读取运行时实际消费的规范文件。
- 物理目录中仍有历史 `index_daily/` 分区。直接使用 `glob/rglob` 或 DuckDB 扫描时，旧目录与规范目录容易被误当成同一份当前事实。

因此，修复目标不是立即删除旧目录，而是让业务读取、目录摘要、审计和人工核查都明确区分：

```text
业务事实读取  -> DataCatalog / FeatureStore -> canonical dataset
存储治理扫描  -> 物理扫描                 -> canonical / legacy / artifact 分类
```

## 2. 现状证据与风险位置

| 位置 | 当前行为 | 风险 |
| :--- | :--- | :--- |
| `src/stock_data/core/task_resolution.py` / `TaskSpec` | `index_daily -> index_daily_bar` | 路由本身正确，需继续作为规范任务映射来源 |
| `src/stock_data/catalog/service_methods.py` | `load_dataset()` 按规范名及允许别名找文件 | 业务读取正确；`available_datasets()` 仍按物理目录名分组 |
| `src/stock_data/governance/audit/reconciliation.py` | RAW/Curated 对账存在独立物理扫描 | 可用于存储对账，但必须明确 canonical 优先和 legacy 角色 |
| `src/stock_data/governance/audit/reconciliation.py` | `run_index_audit()` 扫描并要求 `year=/month=` | 当前非分区 `index_daily_bar/data.parquet` 可能被完全漏掉 |
| `src/stock_data/governance/audit/master_audit.py` | 全库物理扫描 | 适合治理，但不能把 legacy 结果直接当业务水位 |
| `src/stock_data/governance/quality/gate.py` | 对所有物理 Parquet 做质量检查 | 需要输出文件角色，避免 legacy 污染 canonical 汇总 |
| `src/stock_data/governance/audit/distribution_audit.py` | 按目录 `rglob` 后直接读取 Parquet | 传入历史别名时可能审计到废弃目录 |
| `src/stock_data/governance/audit/backfill_acceptance.py` | 独立扫描别名路径 | 验收结果需要绑定规范数据集和选中的文件 |

现有测试已经覆盖任务别名解析，但没有覆盖“陈旧 `index_daily/` + 最新 `index_daily_bar/` 同时存在”的 Tushare 真实读取场景，也没有覆盖审计入口对非分区规范文件的识别。

## 3. 修复原则

1. **业务层只认 Catalog 结果**：分析、报告、基准计算和业务审计不得自行遍历 `data/curated`。
2. **规范名优先**：新代码、CLI、配置和报告统一使用 `index_daily_bar`；`index_daily` 仅保留兼容解析入口。
3. **legacy 不删除但不参与事实结论**：旧目录继续保留，存储审计单独报告，不能改变 canonical 的最新日期、行数、覆盖率或基准结论。
4. **物理扫描必须带角色**：任何必须直接扫描磁盘的迁移、RAW/Curated 对账和存储治理代码，都要标记 `canonical`、`legacy`、`artifact` 或 `unknown`。
5. **日期结论必须绑定读取收据**：报告记录请求名、规范名、数据源、市场、日期范围、行数、标的数和最新业务日期。
6. **先 fail-closed 再解释缺失**：规范文件不存在或无法读取时报告“规范数据缺失/读取失败”，不能静默回退到陈旧目录并宣称数据正常。

## 4. 分阶段实施方案

### P0：修复事实入口和指数审计

#### 4.1 增加统一的规范文件解析入口

涉及：

- `src/stock_data/catalog/service_methods.py`
- `src/stock_data/catalog/ops.py`
- 必要时复用 `src/stock_data/storage/compat_aliases.py`

实施要点：

- 保持 `StorageCompat.canonical_dataset_name()` 和 `dataset_aliases()` 作为别名解析 SSOT，不在审计模块重复维护 `index_daily` 字符串规则。
- 调整 `available_datasets()` / `summary()`：业务摘要按规范数据集汇总，不能把 `index_daily` 旧目录作为独立当前数据集。
- canonical 文件不存在时，不把 legacy 文件偷偷提升为 canonical 事实；应显示规范数据缺失，并由存储治理报告旧目录仍存在。
- 如需展示旧目录，增加单独的 legacy/存储诊断字段或诊断入口，不混入业务摘要的 `latest_date`、`total_rows` 和覆盖率。

#### 4.2 重写 `run_index_audit()` 的读取方式

涉及：

- `src/stock_data/governance/audit/reconciliation.py`

实施要点：

- 使用 `DataCatalog(data_source=data_source).load_dataset("index_daily_bar", start_date=target_date, end_date=target_date, columns=["symbol", "trade_date"])` 获取实际事实。
- 通过 `DataCatalog` 结果计算 `actual_indices`，不再自行假定必须存在 `year=YYYY/month=MM` 分区。
- 保留观察池 `base_dates` 截断规则；将“无规范文件”“规范文件读取失败”“目标日无记录”区分为可解释状态。
- 对 Tushare、yfinance 和其他支持该任务的数据源统一走同一读取协议。

这一步必须优先完成，因为当前 `TaskSpec` 明确将 Tushare `index_daily_bar` 定义为非分区数据集，而现有指数审计的物理扫描条件只匹配分区目录。

#### 4.3 收紧分布审计和回填验收的别名行为

涉及：

- `src/stock_data/governance/audit/distribution_audit.py`
- `src/stock_data/governance/audit/backfill_acceptance.py`

实施要点：

- 分布审计优先通过 `DataCatalog` 加载规范数据；`base_dir` 测试参数继续转换为 `DataCatalog(storage_dir=base_dir)`，保证离线测试可用。
- 回填验收区分“业务验收读取”和“RAW/Curated 物理对账”：业务验收只读取规范数据；物理对账才允许扫描路径，并输出选中文件及角色。
- 传入 `index_daily` 时先解析为 `index_daily_bar`，禁止仅凭请求字符串匹配旧目录。

### P1：建立防回归测试和读取收据

#### 4.4 增加双目录回归夹具

涉及：

- `tests/unit/stock_data/catalog/test_catalog.py`
- `tests/unit/stock_data/storage/test_storage_compat.py`
- `tests/unit/stock_data/governance/audit/test_audit.py`
- `tests/unit/stock_data/governance/audit/test_master_audit.py`
- `tests/unit/stock_data/governance/audit/test_distribution_audit.py`

最小测试场景：

1. 创建陈旧 `tushare/market=CN/index_daily/` 分区，最新日期为 `2026-08-14`。
2. 创建规范 `tushare/market=CN/index_daily_bar/data.parquet`，最新日期为 `2026-08-25`。
3. 断言 `load_dataset("index_daily")` 与 `load_dataset("index_daily_bar")` 读取结果一致。
4. 断言 `get_latest_trade_date("index_daily")` 为 `2026-08-25`。
5. 断言 `summary()` 不把旧目录作为独立业务事实，也不以旧目录日期覆盖规范日期。
6. 断言 `run_index_audit(2026-08-25)` 能读取非分区规范文件。
7. 断言分布审计传入 `index_daily` 时不会审计旧分区目录。
8. 断言物理主审计仍能发现旧目录，但把它标为 legacy/废弃存储，而不是 canonical 当前事实。

#### 4.5 增加跨表日期不变量测试

涉及行业结构面板或其测试模块，具体落点以现有实现为准。

在生成 `relative_return_20d` 的环节增加以下可审计字段或断言：

- `anchor_date`：行业收益和基准收益共同使用的最终交易日；
- `lookback_date`：20 个交易日前的共同起始日；
- `benchmark_symbol`：实际使用的基准标的；
- `benchmark_return_20d`：基准 20 日收益。

验证：

```text
industry_return_20d - relative_return_20d
    == benchmark_return_20d
```

在浮点允许误差内逐行业成立；若日期或基准不一致，质量门禁应失败或明确降级，不能静默降权。

#### 4.6 输出最小读取收据

优先采用现有日志/Manifest 结构，不新增大规模抽象。每次关键数据读取至少记录：

```yaml
requested_dataset: index_daily
canonical_dataset: index_daily_bar
data_source: tushare
market: CN
latest_trade_date: 2026-08-25
rows: 1320
symbols: 10
```

报告生成和人工复核优先展示该收据。若实现中已有 Manifest 字段，应扩展现有字段而不是另建平行格式。

### P2：静态门禁与运维隔离

#### 4.7 增加 catalog-only 静态检查

新增或扩展一个轻量 AST 检查脚本，例如：

- `scripts/lint_catalog_boundaries.py`

检查范围：

- `src/stock_analytics/`
- `src/stock_reporting/`
- 面向业务报告的 `scripts/`

默认禁止这些目录直接对 `data/curated` 使用 `glob`、`rglob`、`read_parquet`、`scan_parquet`。允许名单仅限：

- `DataCatalog` 内部实现；
- `FeatureStore` 内部实现；
- 明确标记为迁移、存储审计、RAW/Curated 对账的 `stock_data` 模块。

将检查接入 `make lint`，并为允许的治理模块保留精确白名单，避免把所有直接读盘行为一刀切禁掉。

#### 4.8 为物理治理工具补充角色输出

涉及：

- `src/stock_data/governance/audit/master_audit.py`
- `src/stock_data/governance/quality/gate.py`
- `src/stock_data/governance/audit/reconciliation.py`

输出至少包含：

- `physical_dataset`；
- `canonical_dataset`；
- `storage_role`；
- `selected_for_business_read`；
- `latest_business_date`；
- `warning`。

这样可以继续发现旧目录、坏文件和迁移残留，同时不会让治理扫描结果被误读成业务事实水位。

## 5. 验收顺序

按以下顺序执行，避免先改物理数据掩盖读取逻辑问题：

1. 定向运行 Catalog、StorageCompat、指数审计和分布审计测试。
2. 用双目录夹具验证 alias/canonical 结果一致，确认旧目录不会影响最新日期。
3. 运行 `make lint`，确认业务层无新增直接物理扫描。
4. 在真实本地数据上运行只读核验：

   ```bash
   make audit TYPE=factor DATE=2026-08-25
   make audit TYPE=all DATE=2026-08-25
   make master-audit
   ```

5. 对比修复前后的 `index_daily_bar` 读取收据、指数完整率和行业基准对账结果。
6. 最后再决定是否对 `data/curated/tushare/market=CN/index_daily/` 做归档或清理；该动作必须单独 dry-run，并按仓库规则获得明确授权。

## 6. 非目标与风险控制

- 本方案不删除、不覆盖、不迁移现有 `index_daily/` 数据。
- 不修改 `config/universe/watchlist.yaml` 及用户已有未提交改动。
- 不改变 `relative_return_20d` 的计算结论；只增加读取来源和日期一致性防线。
- 不把所有 `pl.read_parquet()` 从数据治理模块中移除；迁移、审计和质量门禁仍可直接读盘，但必须区分存储角色。
- 不把历史兼容别名立即移除；先让兼容入口安全解析，再评估废弃窗口和清理计划。

## 7. 完成标准

修复完成后，下面四个结论必须同时成立：

1. 任何业务层请求 `index_daily` 或 `index_daily_bar` 都落到同一个 canonical 数据集。
2. 旧 `index_daily/` 目录存在时，不会改变 Catalog 最新日期、业务摘要或行业基准结论。
3. 指数审计能够识别非分区的 `index_daily_bar/data.parquet`。
4. 任何人工或自动审计输出都能明确回答“本次结论读取了哪个规范数据集、哪个日期、哪个基准、哪些文件”。
