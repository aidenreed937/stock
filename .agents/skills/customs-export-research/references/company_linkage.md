# 公司下沉操作手册（数据流、产物与维护）

> 本文件只保留**怎么跑、产什么、怎么维护**；方法论权威（为什么下沉/股价验证/判读口径/三层信号/回测结论）
> 见 [`docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md`](../../../../docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md)
> （唯一权威，改动口径需同步该文档并重跑回测）；行业研究方法论见 [`methodology.md`](methodology.md)。
> **规模类数字一律以实测为准，不在此固化**：CSV 行数 = `wc -l` 减表头，Mart/面板行数看最新 Manifest。

## 1. 资产清单与装载器（config/data/customs/）

| 文件 | 内容 | 维护方 |
| :-- | :-- | :-- |
| `good_products.csv` | 产品主表（product_key 主键；**行数以 CSV 行数减表头为准**） | 既有 catalog（行业 skill 共享） |
| `good_h8_codes.csv` | 税号表（hs_code 主键 8 位；**行数以 CSV 行数减表头为准**；product_key 外键 + 覆盖列） | 既有 catalog（行业 skill 共享） |
| `categories.csv` | 分类枚举（**数量以 CSV 行数减表头为准**） | 既有 catalog（行业 skill 共享） |
| `taxline_segments.csv` | 高分化产品税号段定义（**段数/覆盖产品数以 CSV 去重统计为准**） | 人工，需审计后新增（HS 码互斥、单位一致） |
| `company_segment_binding.csv` | 人工修正单表（binding + override 二合一；**行数以 CSV 行数减表头为准，带 exposure 行数 = exposure 列非空计数**；override 段必须 ⊆ 同(产品,公司) binding 段，loader 校验） | 人工逐家核验（34 号文档） |
| `gacc_query_codes.txt` | GACC 采集查询码清单（由 catalog 派生，数量以文件首行自述为准） | 派生产物，不手改 |

加载器：catalog 三表（`good_h8_codes.csv` / `good_products.csv` / `categories.csv`）经 catalog 解析器
（`load_hs_catalog`）与 `stock_analytics.marts.customs_company_h8` 消费；`taxline_segments.csv` 经
company_exposure 解析器（`load_taxline_segments`，段引用非法报错）与 H8 Mart（`_attach_segment`）消费；
`company_segment_binding.csv` 经 H8 Mart（`_load_segment_binding` / `_validate_override_segments`，override 段错位报错）消费。
（具体文件路径以代码库为准：`rg 'load_hs_catalog|_validate_override_segments' src` 定位。）

## 2. 动态 H8 链路（公司下沉主路径，当前可运行）

> `fina_mainbz(P)` 按报告期截断 + `jieba + rapidfuzz` 自动映射到 `good_h8_codes.csv` 产品，
> 叠加 `company_segment_binding.csv` 人工修正（绑定段过滤 + exposure override），校验 H8/H6 父码、
> 三级行业映射与重复编码，生成公司-H8 月度出口加权序列
> （`mapping_report_period < report_date` 无报告期前视；`report_date >= list_date` 上市日过滤）。
> 旧 CSV 链（calibrate / `stock_cli.customs_company` / `backtest_customs_company_signal.py` /
> `backtest_customs_multi.py`）已于 2026-10 删除，历史口径见 METHODOLOGY_COMPANY_FINAL。

```bash
# 公司观察表 + 三层信号（月度抓机会）一键执行
uv run python -m stock_cli.customs_company_h8 --as-of-period <报告期> --with-signal

# 动态 H8 链路股价验证（两轮，只读）
uv run python scripts/analyze_h8_a_pool_price_strength.py
uv run python scripts/backtest_customs_company_h8_event.py
```

产物（`--with-signal`）：
- `data/curated/mart/customs_company_product_mapping.parquet / _latest.csv`——公司产品映射
  （match_status: selected/ambiguous/no_match/generic，含 product_exposure、match_score）；
- `data/curated/mart/customs_company_h8_exposure.parquet / _latest.csv`——公司×月份×H8 暴露
  （`company_h8_export_value_usd = export_value_usd × product_exposure`；**行数以最新重建 Manifest / parquet 实测为准**）；
- `data/analytics/industry/customs_company_h8_product_panel.parquet / _latest.csv`——公司×产品×月份面板
  （3MMA yoy/驱动/拐点/二阶导）；
- `data/analytics/industry/customs_company_h8_signal.parquet / _latest.csv`——三层信号（A/B/C/D/回避 评级）；
- `data/analytics/industry/customs_company_h8_manifest.json`——产物与数据水位。

口径要点：
- 海关源统一 GACC 单源（`data/curated/industry/customs_trade_gacc.parquet`），聚合仅用 `trade_direction=export` + `hs_level=8` 行；
- 数量仅段内已知单位唯一时加总（否则置空，驱动不判）；金额全量；
- 补全月序（黄金表全序~末月）重算 3MMA yoy，与 `customs_prosperity` 产品面板（`product_panel._derive`）同口径；
- 公司多段绑定 → 每 (company, product, segment) 一行；空段 → 产品级序列（对比基线）；
- 人工修正单表语义：binding-only 行 exposure 空、override 行 exposure 非空；override 段必须 ⊆ 同(产品,公司) binding 段
  （`_validate_override_segments` 校验段错位）；绑定公司只保留绑定段 H8 码（段级暴露），未绑定公司保留全产品（产品级）；
- 未来公司前视：Mart 层 `report_date >= list_date` 双重点-in-time 过滤（`list_date` 已从最终 mapping/exposure 列剥离），
  回测脚本另加防御性过滤，未来公司样本归 0。

## 3. 抓机会手册（月度执行）

1. **8 月下旬**：刷黄金表 → 跑行业管线（见 SKILL.md SOP）→ `uv run python -m stock_cli.customs_company_h8 --as-of-period <报告期> --with-signal`；
2. **选池**：`rating=="A强机会"`（三腿共振）优先；`B确认中` 做前瞻仓；`risk_flag=="顶背离⚠"` 一律回避（出口仍强但资金撤 = 利好兑现）；
3. **建仓**：产品出口**金额** yoy 连续 2 月 >0 → 分 3 批建仓（月度 1/3，base 基线）；量拐门（量价齐升/量驱动）为可选中性层；
4. **监控**：段级 yoy 二阶导连续 2 月回落减半、转负清仓；`f2_state` 主力/融资由正转负 = 资金背离预警（即便出口仍正）；
5. **组合纪律**：多产品分散（transformer/battery/semi/cathode/wind 等信号强的池子），单产品不重仓；快周期商品（锂/铜/银）不用本信号；
6. **后视确认**：财报双正（f3=真扩张）验证"真扩张"，增收不增利（净利负）降级。

## 4. 维护边界

- 段定义新增需人工审计（HS 码互斥、单位一致），不经 LLM 自动生成；
- `company_segment_binding.csv` 新增 override 行须人工核验主营占比（evidence 留来源）；override 段必须 ⊆ 同(产品,公司) binding 段（loader 校验报错，防段错位）；改动后重跑 H8 Mart 与其单测（`rg customs_company_h8 tests` 定位）；
- 公司段引用非法（段未定义）时 loader 直接报错，防止手误静默失效；
- 映射匹配与校验（H8/H6 父码、三级行业映射、重复编码）调整需同步 H8 Mart 实现并重跑 H8 链路测试；
- 信号口径与回测结论改动（确认月数/质量门/三腿阈值）需同步 METHODOLOGY_COMPANY_FINAL.md 并重跑回测。
