# ADR 0001：数据集身份与分层存储

## 状态

已接受

## 背景

旧缓存只按数据源、接口和结束日期命名，无法区分标的、日期范围、复权口径和 Schema 版本，导致重复请求时串用数据或覆盖文件。

## 决策

- RAW 使用包含 provider、dataset、endpoint、标的、日期范围、复权口径和 Schema 版本的 `DatasetKey` 请求指纹。
- Curated 使用标准数据集名 `daily_bar` 和业务日期分区，按 `(market, symbol, trade_date)` 幂等合并；`adjustment` 作为行情属性保存，不作为并存版本键。
- 文件写入采用临时文件后原子替换。
- 现有旧路径保留为兼容读取，不再作为新 Pipeline 的写入路径。

## 代价与触发信号

文件数量会增加，且需要后续压实或 catalog。只有 Parquet 文件数量达到万级、扫描 P95 持续超目标或容量达到数百 GB 时，才评估压实、索引或分片。
