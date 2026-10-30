# DCE 官方期货日行情缓存接入说明

## 背景

DCE 四品种（V/PP/L/EB）已切换到“大商所官网逐日官方行情 + 按当日持仓量选主力”的口径，
实现逻辑位于 `src/stock_data/fetcher/industry/chemicals/collectors/official.py`
（`download_dce_daily_text` / `_backfill_dce_days`），由
`scripts/backfill_chemical_futures_daily.py`（`FuturesPriceCollector.backfill_raw`）驱动。

但大商所官网（`www.dce.com.cn`）全站部署了瑞数反爬（412 JS 挑战），
普通 HTTP 客户端与 headless 浏览器均无法稳定取数（headless 会拿到空白页/400）。
因此脚本采用**缓存优先**策略：本地 `dce_daily_cache/` 有官方文件就直接解析，
没有才尝试联网；联网不可达时**安全跳过 DCE 回填，保留现有 CSV**。

## 你需要提供的数据

把官方日行情文件按以下规则放入仓库缓存目录：

```
data/raw/industry/chemicals/futures_daily/dce_daily_cache/{YYYY}/{YYYYMMDD}.txt
```

- `{YYYY}`：年份，例如 `2026`；
- `{YYYYMMDD}`：交易日，例如 `20260915`；
- 扩展名支持 `.txt` / `.csv` / `.tsv`，也支持任意同名后缀（按 `YYYYMMDD*` 匹配）；
- 编码自动识别 UTF-8 / GBK / GB18030，无需手工转码。

文件内容为大商所“日行情”导出/查询响应的原始文本，表头需包含以下字段
（列名以实际导出为准，制表符或 CSV 分隔均可，脚本按表头名定位）：

```
品种 商品名称 合约代码 开盘价 最高价 最低价 收盘价 结算价 成交量 持仓量
```

## 获取方式建议

1. **推荐**：在你本机正常浏览器中打开大商所日行情页
   `http://www.dce.com.cn/publicweb/quotesdata/dayQuotesCh.html`
   （或官网“行情数据 → 日行情”入口），人工通过验证后查询对应交易日，
   将返回的行情文件导出/另存，按 `YYYYMMDD` 命名放入上述缓存目录。
2. 若官网对历史日期有覆盖限制（例如只提供近若干年），按实际覆盖范围放置即可；
   未覆盖的历史日期会缺行（当前选择为“只保留官方行”，缺失日留空）。
3. 若你有 DCE 数据授权 API 或官方镜像，把接口信息给我，我可以改接。

> 说明：浏览器解出的 WAF Cookie 通常绑定浏览器指纹，脚本侧重放通常无效，
> 不建议走 Cookie 导出路线；直接提供响应文件最可靠。

## 回填与物化

放置缓存文件后运行：

```bash
uv run scripts/backfill_chemical_futures_daily.py --full
```

- DCE 四品种会按各品种上市日（L 2007-07-31 / V 2009-05-25 / PP 2014-02-28 / EB 2019-09-26）
  全量官方回填，落盘 `data/raw/industry/chemicals/futures_daily/{symbol}.csv`，
  `source = Exchange_Official/DCE`；
- 缓存目录为空且官网不可达时，脚本打印警告并跳过 DCE 回填（现有 CSV 不受影响）；
- 日常增量同步请保持缓存目录随交易日更新（每交易日放入当日文件即可），
  或等官网反爬策略调整后直接联网。

Curated 物化按仓库 pipeline 流程：

```bash
make sync SOURCE=industry ENDPOINT=chemical_futures_daily
```
