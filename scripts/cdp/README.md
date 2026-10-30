# CDP (Chrome DevTools Protocol) 自动化采集工具集

本目录集中管理本仓库所有基于**宿主机真实 Chrome 浏览器接管**的自动化采集脚本。通过复用真实 Chrome 环境的会话与 Cookie，天然解决瑞数安全防护（412 动态挑战）、极验滑块验证码及前端 SPA 动态渲染等高难反爬机制。

---

## 模块与能力清单

| 采集器脚本 | 对应数据源 / 机构 | 核心数据产出 | 对应 Agent 技能 |
| :--- | :--- | :--- | :--- |
| [`dce_cdp_automation.py`](file:///Users/mac/workspace/personal/finance/stock/scripts/cdp/dce_cdp_automation.py) | **大连商品交易所 (DCE)** 官方报表前端 | `EG`（乙二醇）、`V`（PVC）、`EB`（苯乙烯）、`PP`、`L` 日行情与交割仓单日报 | `.agents/skills/dce-cdp-automation` |
| [`mysteel_cdp_automation.py`](file:///Users/mac/workspace/personal/finance/stock/scripts/cdp/mysteel_cdp_automation.py) | **Mysteel (我的钢铁网 / 隆众资讯)** | 海绵钛、钛精矿、碳酸锂、工业硅、螺纹钢等多品种现货调研价格 | `.agents/skills/mysteel-cdp-automation` |
| [`gacc_cdp_automation.py`](file:///Users/mac/workspace/personal/finance/stock/scripts/cdp/gacc_cdp_automation.py) | **中国海关总署 (GACC)** 在线查询平台 | 8 位 HS 编码重点商品月度出口量价数据 | `.agents/skills/customs-gacc-automation` |

---

## 统一运行前置条件

在 macOS 终端启动宿主机原生 Chrome 调试实例：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="/Users/mac/.chrome_cdp_profile" \
  --disable-blink-features=AutomationControlled &
```

---

## 常用命令

```bash
# 1. 大商所期货行情与仓单智能增量采集与 2-Tier 物化
make dce-harvest SYNC=1
# 或直接调用
uv run python scripts/cdp/dce_cdp_automation.py --sync

# 2. Mysteel 现货价格采集 (如海绵钛)
uv run python scripts/cdp/mysteel_cdp_automation.py --symbol Ti_sponge

# 3. 海关数据采集调度
uv run python scripts/gacc_batch_scheduler.py
```
