# 数据底座（本地黄金表，Ground Truth First）

| 数据集 | 路径 | 用途 |
| :--- | :--- | :--- |
| 海关黄金表 | `data/curated/industry/customs_trade.parquet` | 商品→L1/L2/L3 映射、金额/数量/单位，2016-01 ~ 最新月 |
| 金额面板 | `data/analytics/industry/customs_export_prosperity_panel.parquet` | hs8/L3/L2 三层 3MMA yoy（跨源统一重算） |
| 量价面板 | `data/analytics/industry/customs_l2_volume_price_monthly.parquet` | L2/L3 量价分解（量 yoy / 价 yoy / 驱动类型） |
| 商品量价拐点面板 | `data/analytics/industry/customs_product_volume_price.parquet` | 商品级三 yoy + 驱动 + 拐点/二阶导 + 行业映射（新增脚本产物） |
| 观察表 | `data/analytics/industry/customs_forward_watch_l2(_l3).parquet` | 金额/量/价/驱动/36 月分位/财报 yoy/一致率（新增脚本产物） |
| 共振面板（辅助） | `data/analytics/industry/comm_global_resonance_panel.parquet` | 全球 AI 资本开支 6 信号共振（云 CapEx/SEMI 设备/台积电/SIA/ASML 毛利率/渠道 DOI，通信设备光模块拐点定性用） |
| 财报 | `sw_2021_l2_fs_non_financial` / `sw_2021_l3_fs_non_financial` | 营收/净利 TTM yoy（后视验证）；银行/证券/保险分表 |
| 维度黄金表 | `sw_2021_industry_dimension_golden`（derived） | `index_code ↔ industry_code ↔ parent_code` 桥接唯一信任源 |
