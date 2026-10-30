"""中国海关总署 (GACC) 在线查询平台 CDP 自动化接管脚本。

通过 Chrome DevTools Protocol (CDP) 连接已运行的 Chrome 实例，
自动完成字段选型、编码填入与查询触发，人机协同滑动验证码后自动导出并入库。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import websocket

# 确保项目根目录在 sys.path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("gacc_cdp")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

DEFAULT_CDP_PORT = 9222
DEFAULT_TARGET_URL = "http://stats.customs.gov.cn/"
DEFAULT_CODES_PATH = Path("config/data/customs/gacc_query_codes.txt")
DEFAULT_DOWNLOAD_DIR = Path("data/raw/industry/customs/gacc/downloads")


class CdpClient:
    """轻量同步 CDP 客户端。"""

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self._seq = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """发送 CDP 请求并等待响应。"""
        self._seq += 1
        msg_id = self._seq
        payload = {"id": msg_id, "method": method, "params": params or {}}
        self.ws.send(json.dumps(payload))
        while True:
            raw = self.ws.recv()
            if not isinstance(raw, str):
                continue
            data = json.loads(raw)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"CDP error on {method}: {data['error']}")
                result = data.get("result", {})
                return dict(result) if isinstance(result, dict) else {}

    def evaluate(self, expression: str) -> Any:
        """在页面上下文执行 JavaScript 并返回结果值。"""
        res = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
        result_obj = res.get("result", {})
        if result_obj.get("subtype") == "error":
            raise RuntimeError(f"JS eval error: {result_obj.get('description')}")
        return result_obj.get("value")

    def close(self) -> None:
        """关闭 WebSocket 连接。"""
        try:
            self.ws.close()
        except Exception:
            pass


def is_port_open(port: int = DEFAULT_CDP_PORT) -> bool:
    """检查 CDP 端口是否开放。"""
    for host in ("localhost", "127.0.0.1"):
        try:
            req = urllib.request.urlopen(f"http://{host}:{port}/json/version", timeout=1)
            if int(req.getcode()) == 200:
                return True
        except Exception:
            pass
    return False


def get_or_create_tab(port: int = DEFAULT_CDP_PORT) -> str:
    """获取海关页面标签页，若无则新建或复用首页。"""
    tabs: list[dict[str, Any]] = []
    for host in ("localhost", "127.0.0.1"):
        try:
            url = f"http://{host}:{port}/json"
            req = urllib.request.urlopen(url, timeout=2)
            tabs = json.loads(req.read().decode())
            if tabs:
                break
        except Exception:
            continue

    page_tabs = [t for t in tabs if t.get("type") == "page"]
    if not page_tabs:
        for host in ("localhost", "127.0.0.1"):
            try:
                new_url = f"http://{host}:{port}/json/new?{DEFAULT_TARGET_URL}"
                new_tab: dict[str, Any] = json.loads(
                    urllib.request.urlopen(new_url, timeout=3).read().decode()
                )
                return str(new_tab["webSocketDebuggerUrl"])
            except Exception:
                continue
        raise RuntimeError("未能创建或获取 Chrome 页面标签页")

    for tab in page_tabs:
        tab_url = tab.get("url", "")
        if "stats.customs.gov.cn" in tab_url:
            return str(tab["webSocketDebuggerUrl"])

    first_tab = page_tabs[0]
    return str(first_tab["webSocketDebuggerUrl"])


def read_query_codes(path: Path = DEFAULT_CODES_PATH) -> str:
    """从清单文件读取单行逗号分隔税号。"""
    if not path.exists():
        raise FileNotFoundError(f"未找到税号清单文件: {path}")
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for line in lines:
        if not line.startswith("=") and "," in line:
            return line
    raise ValueError("未在文件中找到逗号分隔的商品编码行")


def fill_gacc_form(
    client: CdpClient,
    codes_str: str,
    year: int,
    start_month: int = 1,
    end_month: int = 6,
) -> dict[str, Any]:
    """通过注入 JS 精准定位 iframe 表单并填入税号，默认选择半年范围 (1-6月) 防平台截断。"""
    safe_codes = codes_str.replace('"', '\\"').replace("'", "\\'")
    js_code = f"""
    (async () => {{
        const log = [];
        const iframe = document.querySelector("iframe");
        if (!iframe || !iframe.contentDocument) {{
            return {{ status: "error", error: "未找到查询 iframe 或 contentDocument 不可访问" }};
        }}
        const doc = iframe.contentDocument;
        const win = iframe.contentWindow;

        // 1. 设置年份并触发 changeMonthList 异步更新月份列表
        const yearSel = doc.querySelector('#year');
        if (yearSel) {{
            yearSel.value = "{year}";
            if (win && win.changeMonthList) {{
                win.changeMonthList("{year}");
            }} else {{
                yearSel.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
            log.push("已设置年份: {year}");
        }}

        // 等待海关接口返回该年份的可用月份列表（等待 jQuery AJAX 全部完成）
        if (win && win.$) {{
            let waitAjax = 0;
            while (win.$.active > 0 && waitAjax < 50) {{
                await new Promise(r => setTimeout(r, 100));
                waitAjax++;
            }}
        }}
        await new Promise(resolve => setTimeout(resolve, 300));

        // 2. 默认选择半年范围（防止 1000+ 税号 × 12 个月单次数据量超限被海关截断）
        let actualStartMonth = "{start_month}";
        let actualEndMonth = "{end_month}";
        const startM = doc.querySelector('#startMonth');
        if (startM) {{
            startM.value = actualStartMonth;
            startM.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}
        const endM = doc.querySelector('#endMonth');
        if (endM) {{
            const availableVals = Array.from(endM.options).map(o => o.value);
            if (!availableVals.includes(actualEndMonth) && availableVals.length > 0) {{
                actualEndMonth = availableVals[availableVals.length - 1];
            }}
            endM.value = actualEndMonth;
            endM.dispatchEvent(new Event('change', {{ bubbles: true }}));
            log.push("已设置半年范围: " + startM.value + " 至 " + endM.value + " 月 (防数据过大截断)");
        }}

        // 3. 勾选“分月展示” (monthFlag checkbox, value="1")
        const monthBox = doc.querySelector('input[name="monthFlag"]');
        if (monthBox && !monthBox.checked) {{
            monthBox.click();
            log.push("已勾选: 分月展示 (monthFlag=1)");
        }}

        // 4. 进出口方向选“出口” (iEType radio, value="0")
        const flowRadio = doc.querySelector('input[name="iEType"][value="0"]');
        if (flowRadio) {{
            flowRadio.click();
            log.push("已选择: 出口 (iEType=0)");
        }}

        // 5. 币制选“美元” (currencyType radio, value="usd")
        const currRadio = doc.querySelector('input[name="currencyType"][value="usd"]');
        if (currRadio) {{
            currRadio.click();
            log.push("已选择: 美元 (currencyType=usd)");
        }}

        // 6. 第一组输出字段选“商品” (outerField1 = "CODE_TS")
        const outer1 = doc.querySelector('#outerField1');
        if (outer1) {{
            outer1.value = "CODE_TS";
            outer1.dispatchEvent(new Event('change', {{ bubbles: true }}));
            log.push("已设置第一组输出字段: 商品 (CODE_TS)");
        }}

        // 7. 填入商品编码（必须在年份与字段设置后填入，防止被 changeMonthList 冲掉）
        const codes = "{safe_codes}";
        const outerVal1 = doc.querySelector('#outerValue1') || doc.querySelector('#codeTs');
        if (outerVal1) {{
            outerVal1.value = codes;
            outerVal1.dispatchEvent(new Event('input', {{ bubbles: true }}));
            outerVal1.dispatchEvent(new Event('change', {{ bubbles: true }}));
            log.push("已自动填入商品编码清单 (共 " + codes.split(',').length + " 个税号)");
        }}

        // 8. 提交前二次核验确保月份未被异步重置
        if (startM && startM.value !== actualStartMonth) {{
            startM.value = actualStartMonth;
            startM.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}
        if (endM && endM.value !== actualEndMonth) {{
            endM.value = actualEndMonth;
            endM.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}
        log.push("提交前最终核验时间范围: " + (startM ? startM.value : actualStartMonth) + " 至 " + (endM ? endM.value : actualEndMonth) + " 月");

        // 9. 触发查询
        const searchBtn = doc.querySelector('#doSearch');
        if (searchBtn) {{
            searchBtn.click();
            log.push("已触发查询按钮 (点击 #doSearch)");
        }} else if (win && win.doSearch) {{
            win.doSearch(1);
            log.push("已调用 win.doSearch(1)");
        }}

        return {{
            status: "success",
            start_month: (startM ? startM.value : actualStartMonth),
            end_month: (endM ? endM.value : actualEndMonth),
            logs: log
        }};
    }})()
    """
    res = client.evaluate(js_code)
    return dict(res) if isinstance(res, dict) else {"result": res}


def resolve_task_specific_filename(
    raw_csv: Path,
    year: int,
    start_month: int,
    end_month: int,
    flow_type: str = "export",
    currency: str = "usd",
) -> Path:
    """根据任务核心特性（来源/方向/币制/起止期间/分月粒度/采集批次）重命名文件。

    命名规范: gacc_{flow}_{currency}_{start_period}_{end_period}_monthly_{timestamp}.csv
    示例: gacc_export_usd_202501_202506_monthly_20260913_111500.csv
    """
    actual_min = f"{year}{start_month:02d}"
    actual_max = f"{year}{end_month:02d}"

    # 尝试从 CSV 第一列（数据年月）中提取真实期间
    try:
        raw_bytes = raw_csv.read_bytes()
        text = ""
        for enc in ("utf-8-sig", "gb18030", "gbk", "utf-8"):
            try:
                text = raw_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text:
            reader = csv.reader(text.splitlines())
            next(reader, None)  # 跳过表头
            months: set[str] = set()
            for row in reader:
                if row and row[0].isdigit() and len(row[0]) == 6:
                    months.add(row[0])
            if months:
                actual_min = min(months)
                actual_max = max(months)
    except Exception as exc:
        logger.debug("读取 CSV 期间失败，采用参数命名: %s", exc)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_name = f"gacc_{flow_type.lower()}_{currency.lower()}_{actual_min}_{actual_max}_monthly_{timestamp}.csv"
    target_path = raw_csv.parent / target_name
    if raw_csv.resolve() != target_path.resolve():
        shutil.move(raw_csv, target_path)
        logger.info("已根据任务特性将导出文件重命名为: %s", target_name)
    return target_path


def reset_to_clean_query_page(client: CdpClient, timeout_sec: int = 30) -> bool:
    """强制重置并刷新海关页面到初始空白表单状态，彻底杜绝历史查询结果污染。"""
    logger.info("正在检查/重置海关页面至初始表单状态...")
    check_js = """
    (() => {
        const iframe = document.querySelector("iframe");
        if (!iframe || !iframe.contentDocument) return false;
        const doc = iframe.contentDocument;
        const hasYear = Boolean(doc.querySelector("#year"));
        const hasSearch = Boolean(doc.querySelector("#doSearch"));
        return hasYear && hasSearch;
    })()
    """
    try:
        if bool(client.evaluate(check_js)):
            logger.info("海关初始查询表单已处于就绪状态！")
            return True
    except Exception:
        pass

    client.evaluate('window.location.href = "http://stats.customs.gov.cn/";')
    start = time.time()
    while time.time() - start < timeout_sec:
        time.sleep(1.0)
        try:
            status = client.evaluate(check_js)
            if bool(status):
                logger.info("海关初始查询表单已成功就绪！")
                return True
        except Exception:
            pass
    logger.warning("等待海关初始查询表单就绪超时！")
    return False


def dismiss_historical_notice(client: CdpClient) -> bool:
    """自动点击'当前查询时间范围包含非近期数据，查询时间较长，是否继续?'的确定按钮。"""
    js_code = """
    (() => {
        const iframe = document.querySelector("iframe");
        const doc = iframe?.contentDocument || document;
        const layers = Array.from(doc.querySelectorAll(".layui-layer"));
        for (const l of layers) {
            const txt = l.innerText || '';
            if (txt.includes('非近期数据') || txt.includes('是否继续')) {
                const btn0 = l.querySelector(".layui-layer-btn0") ||
                             Array.from(l.querySelectorAll("a, button")).find(b => (b.innerText || '').includes('确定'));
                if (btn0) {
                    btn0.click();
                    return true;
                }
            }
        }
        return false;
    })()
    """
    try:
        return bool(client.evaluate(js_code))
    except Exception:
        return False


def detect_captcha_dialog(client: CdpClient) -> bool:
    """探测海关滑块验证码弹窗是否正在显示。"""
    js_code = """
    (() => {
        const iframe = document.querySelector("iframe");
        const doc = iframe?.contentDocument || document;
        const layers = Array.from(doc.querySelectorAll(".layui-layer"));
        for (const l of layers) {
            const title = l.querySelector(".layui-layer-title")?.innerText || '';
            const hasCaptchaIframe = Boolean(l.querySelector("iframe[src*='toCaptchaView']"));
            const isVisible = (l.offsetWidth > 0 || l.offsetHeight > 0) &&
                              window.getComputedStyle(l).display !== 'none';
            if ((title.includes('验证码') || hasCaptchaIframe) && isVisible) {
                return true;
            }
        }
        return false;
    })()
    """
    try:
        return bool(client.evaluate(js_code))
    except Exception:
        return False


def detect_query_results_ready(client: CdpClient) -> dict[str, Any]:
    """探测本次查询结果是否已经在结果页渲染就绪。

    返回:
    - ready: bool 是否数据就绪
    - total_size: int 总记录条数
    - in_result_page: bool 是否已进入结果页
    """
    js_code = """
    (() => {
        const iframe = document.querySelector("iframe");
        if (!iframe || !iframe.contentDocument) {
            return { ready: false, total_size: 0, in_result_page: false };
        }
        const doc = iframe.contentDocument;
        const href = iframe.contentWindow?.location?.href || '';
        const inResultPage = href.includes('queryDataList');

        // 检查 loading 动画
        const hasLoading = Boolean(
            doc.querySelector(".layui-layer-loading") ||
            doc.querySelector(".layui-layer-load") ||
            document.querySelector(".layui-layer-loading")
        );

        // 检查 totalSize 输入框
        const totalSizeInput = doc.querySelector("#totalSize");
        const totalVal = totalSizeInput ? (totalSizeInput.value || '').trim() : '';
        const totalSize = totalVal && !isNaN(totalVal) ? parseInt(totalVal, 10) : 0;

        const ready = (inResultPage || totalSize > 0) && totalSize > 0 && !hasLoading;

        return {
            ready: ready,
            total_size: totalSize,
            in_result_page: inResultPage,
            has_loading: hasLoading
        };
    })()
    """
    try:
        res = client.evaluate(js_code)
        return (
            dict(res)
            if isinstance(res, dict)
            else {"ready": False, "total_size": 0, "in_result_page": False}
        )
    except Exception as exc:
        logger.debug("探测结果渲染状态失败: %s", exc)
        return {"ready": False, "total_size": 0, "in_result_page": False}


def trigger_result_export(client: CdpClient) -> bool:
    """在结果页触发导出数据并处理弹窗。"""
    js_code = """
    (() => {
        const iframe = document.querySelector("iframe");
        const doc = iframe?.contentDocument || document;
        const win = iframe?.contentWindow || window;

        if (win && typeof win.downLoad === 'function') {
            win.downLoad();
            return true;
        }

        const btns = Array.from(doc.querySelectorAll("a, button, input"));
        const exportBtn = btns.find(b => {
            const txt = b.innerText || b.value || '';
            const id = b.id || '';
            return txt.includes('导出数据') || txt.includes('导出') || id.toLowerCase().includes('download');
        });
        if (exportBtn) {
            exportBtn.click();
            return true;
        }
        return false;
    })()
    """
    try:
        return bool(client.evaluate(js_code))
    except Exception as exc:
        logger.debug("触发导出失败: %s", exc)
        return False


def dismiss_export_confirm_dialog(client: CdpClient) -> bool:
    """自动点击'确认导出数据？'等弹窗的确定按钮。"""
    js_code = """
    (() => {
        const allDocs = [document];
        const iframe = document.querySelector("iframe");
        if (iframe && iframe.contentDocument) allDocs.push(iframe.contentDocument);
        for (const d of allDocs) {
            const layers = Array.from(d.querySelectorAll(".layui-layer"));
            for (const l of layers) {
                const txt = l.innerText || '';
                if (txt.includes('确认导出') || txt.includes('导出数据') || txt.includes('是否导出')) {
                    const btn0 = l.querySelector(".layui-layer-btn0") ||
                                 Array.from(l.querySelectorAll("a, button")).find(b => (b.innerText || '').includes('确定'));
                    if (btn0) {
                        btn0.click();
                        return true;
                    }
                }
            }
        }
        return false;
    })()
    """
    try:
        return bool(client.evaluate(js_code))
    except Exception:
        return False


# --- 保持兼容接口以支持既有单元测试 ---
def check_query_status(client: CdpClient) -> dict[str, Any]:
    """兼容旧测试的查询状态探查接口。"""
    if detect_captcha_dialog(client):
        return {"state": "waiting_captcha", "total_size": 0, "has_confirm_dialog": False}
    res = detect_query_results_ready(client)
    if res.get("ready"):
        return {
            "state": "query_completed",
            "total_size": int(res.get("total_size", 0)),
            "has_confirm_dialog": False,
        }
    return {"state": "waiting_query", "total_size": 0, "has_confirm_dialog": False}


def dismiss_confirm_dialog(client: CdpClient) -> bool:
    """兼容旧测试的弹窗确认接口。"""
    return dismiss_export_confirm_dialog(client)


def trigger_export(client: CdpClient) -> bool:
    """兼容旧测试的导出触发接口。"""
    return trigger_result_export(client)


def run_automation(
    year: int = 2025,
    start_month: int = 1,
    end_month: int = 6,
    port: int = DEFAULT_CDP_PORT,
    auto_import: bool = True,
) -> int:
    """主执行入口。"""
    logger.info("=== GACC 海关自动化下载助手 (CDP 模式) ===")

    # 1. 检测端口
    if not is_port_open(port):
        logger.error(
            "无法连接到 Chrome 调试端口 127.0.0.1:%d！\n"
            "请在终端中运行以下命令拉起原生 Chrome：\n"
            "  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
            '--remote-debugging-port=%d --user-data-dir="/tmp/chrome_gacc_profile" '
            '"%s" &\n',
            port,
            port,
            DEFAULT_TARGET_URL,
        )
        return 1

    # 2. 读取编码
    codes_str = read_query_codes()
    code_count = len([c for c in codes_str.split(",") if c.strip()])
    logger.info("成功加载查询税号: 共 %d 个编码", code_count)

    # 3. 连接 CDP
    tab_ws_url = get_or_create_tab(port)
    logger.info("已连接 Chrome 页面: %s", tab_ws_url)
    client = CdpClient(tab_ws_url)

    try:
        # 配置下载行为
        download_dir = DEFAULT_DOWNLOAD_DIR.resolve()
        download_dir.mkdir(parents=True, exist_ok=True)
        client.call("Page.enable")
        client.call("Runtime.enable")
        try:
            client.call(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(download_dir)},
            )
        except Exception:
            client.call(
                "Page.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(download_dir)},
            )

        # 4. 强制复位并刷新海关页面到初始空白表单状态，彻底杜绝历史查询残留与白屏
        if not reset_to_clean_query_page(client):
            logger.error("重置海关页面失败，请检查浏览器连接状态！")
            return 1

        # 5. 表单自动选择 (默认半年 1-6 月防截断)
        logger.info(
            "正在执行表单自动点选 (出口 / 美元 / 分月 / 商品 / %d-%02d ~ %02d)...",
            year,
            start_month,
            end_month,
        )
        fill_res = fill_gacc_form(client, codes_str, year, start_month, end_month)
        for entry in fill_res.get("logs", []):
            logger.info("  %s", entry)

        logger.info("\n" + "=" * 60)
        logger.info("【操作提示】")
        logger.info(
            "1. 脚本已自动配置表单：出口 / 美元 / 分月 / 商品编码 (共 %d 个税号)；", code_count
        )
        logger.info(
            "2. 默认设置半年范围 (%d-%02d ~ %02d)，避免行数超限被海关截断；",
            year,
            start_month,
            end_month,
        )
        logger.info("3. 表单已自动触发【查询】，请在已打开的 Chrome 中滑动一次验证码；")
        logger.info("4. 滑过验证码后【无需手动点击导出】：")
        logger.info("   -> 脚本将自动监控数据加载进度并在终端打印查询总条数；")
        logger.info("   -> 数据加载完毕后，将全自动触发【导出】并确认下载弹窗；")
        logger.info("   -> 脚本自动按任务特性重命名并无缝导入 Curated 黄金事实表！")
        logger.info("=" * 60 + "\n")

        # 6. 严密的多阶段生命周期状态机监听
        project_download_dir = download_dir
        system_download_dir = Path.home() / "Downloads"

        logger.info("开始监听页面状态与下载目录:")
        logger.info("  1. 项目专用目录: %s", project_download_dir)
        if system_download_dir.exists():
            logger.info("  2. 系统默认目录: %s", system_download_dir)

        existing_proj = set(project_download_dir.glob("*.csv"))
        existing_sys = (
            set(system_download_dir.glob("*.csv")) if system_download_dir.exists() else set()
        )

        timeout_sec = 300
        start_time = time.time()
        last_log_time = 0.0
        downloaded_csv: Path | None = None

        # 阶段守卫标志
        captcha_appeared = False
        captcha_passed = False
        query_completed = False
        export_triggered = False

        while time.time() - start_time < timeout_sec:
            # 阶段 1: 等待验证码弹出（持续自动确认可能出现的'非近期历史数据'提示框）
            if not captcha_appeared:
                if dismiss_historical_notice(client):
                    logger.info("已自动确认海关【非近期数据查询提示】，正在等待验证码弹窗...")

                if detect_captcha_dialog(client):
                    captcha_appeared = True
                    logger.info("\n" + "=" * 60)
                    logger.info("【请滑动验证码】")
                    logger.info("-> 海关拼图滑块验证码已弹出！")
                    logger.info("-> 请在已打开的 Chrome 浏览器中向右拖动滑块完成拼图验证。")
                    logger.info("============================================================\n")

            # 阶段 2: 验证码已弹出，等待用户在浏览器中滑动完成并关闭验证码弹窗
            elif not captcha_passed:
                is_captcha_still_there = detect_captcha_dialog(client)
                if not is_captcha_still_there:
                    captcha_passed = True
                    logger.info(
                        "检测到验证码弹窗已关闭（验证码已通过），海关正在后台检索并渲染数据，请稍候..."
                    )

            # 阶段 3: 验证码已通过，等待海关后台返回本次查询数据并渲染就绪
            elif not query_completed:
                res_status = detect_query_results_ready(client)
                if res_status.get("ready"):
                    total_size = int(res_status.get("total_size", 0))
                    query_completed = True
                    logger.info("\n" + "=" * 60)
                    logger.info("【海关数据查询完毕】")
                    logger.info("-> 验证码已通过，海关平台数据检索完成！")
                    logger.info("-> 本次实际检索返回总记录数: %s 条", f"{total_size:,}")
                    logger.info("============================================================\n")

            # 阶段 4: 数据查询完毕，自动触发导出并自动确认弹窗
            elif not export_triggered:
                if dismiss_export_confirm_dialog(client):
                    logger.info("已自动点击海关【确认导出】弹窗！")

                if trigger_result_export(client):
                    export_triggered = True
                    logger.info("已全自动触发海关前端导出【win.downLoad()】，正在处理确认弹窗...")
                    time.sleep(0.5)
                    if dismiss_export_confirm_dialog(client):
                        logger.info("已自动点击海关【确认导出】弹窗！")

            # 阶段 5: 导出已触发，持续监控并自动确认可能延迟弹出的弹窗
            elif dismiss_export_confirm_dialog(client):
                logger.info("已自动点击海关【确认导出】弹窗！")

            # 友好进度提示
            now = time.time()
            if not query_completed and now - last_log_time >= 6.0:
                last_log_time = now
                if not captcha_appeared:
                    logger.info("正在等待海关弹出验证码...")
                elif not captcha_passed:
                    logger.info("等待在 Chrome 浏览器中手动滑动拼图验证码...")
                else:
                    logger.info("海关平台数据检索中 (1000+ 税号数据量较大，请稍候)...")

            # 检查项目专用下载目录
            curr_proj = set(project_download_dir.glob("*.csv"))
            new_proj = [f for f in curr_proj - existing_proj if not f.name.endswith(".crdownload")]
            if new_proj:
                downloaded_csv = sorted(new_proj, key=lambda x: x.stat().st_mtime)[-1]
                logger.info("在项目下载目录捕获到新 CSV 文件: %s", downloaded_csv.name)
                break

            # 兼容检查系统 ~/Downloads 目录
            if system_download_dir.exists():
                curr_sys = set(system_download_dir.glob("*.csv"))
                new_sys = [
                    f
                    for f in curr_sys - existing_sys
                    if not f.name.endswith(".crdownload") and f.stat().st_mtime >= start_time - 5
                ]
                if new_sys:
                    captured = sorted(new_sys, key=lambda x: x.stat().st_mtime)[-1]
                    logger.info("在系统 ~/Downloads 目录捕获到新 CSV 文件: %s", captured.name)
                    dest = project_download_dir / captured.name
                    shutil.copy2(captured, dest)
                    downloaded_csv = dest
                    logger.info("已自动归集并落盘至项目目录: %s", downloaded_csv)
                    break

            time.sleep(1.0)

        if not downloaded_csv:
            logger.warning("在 %d 秒内未检测到导出的 CSV 文件。", timeout_sec)
            return 2

        # 6. 根据任务特性重命名文件 (来源_方向_币制_期间_粒度_时间戳)
        actual_start_m = int(fill_res.get("start_month", start_month))
        actual_end_m = int(fill_res.get("end_month", end_month))
        standard_csv = resolve_task_specific_filename(
            downloaded_csv,
            year=year,
            start_month=actual_start_m,
            end_month=actual_end_m,
            flow_type="export",
            currency="usd",
        )

        # 7. 自动导入 Curated
        if auto_import:
            logger.info("正在自动导入到 Curated 黄金表...")
            from stock_cli.customs import handle_gacc_import

            import_args = argparse.Namespace(
                file=str(standard_csv),
                start_month=f"{year}-{actual_start_m:02d}",
                end_month=f"{year}-{actual_end_m:02d}",
                flow="export",
                currency="USD",
                force=False,
                catalog="config/data/customs/good_h8_codes.csv",
                raw_dir="data/raw/industry",
                curated="data/curated/industry/customs_trade_gacc.parquet",
            )
            ret_code = handle_gacc_import(import_args)
            if ret_code == 0:
                logger.info("=== GACC 数据已自动导入落盘成功！===")
            else:
                logger.error("gacc-import 处理失败，退出码: %d", ret_code)
                return int(ret_code)

        return 0

    finally:
        client.close()


def main() -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="GACC CDP 自动化下载与导入助手")
    parser.add_argument("--year", type=int, default=2025, help="查询年份 (默认 2025)")
    parser.add_argument(
        "--half",
        choices=["H1", "H2", "h1", "h2"],
        default="H1",
        help="半年度快捷选项: H1 (1-6月, 默认防截断) 或 H2 (7-12月)",
    )
    parser.add_argument("--start-month", type=int, default=None, help="显式起始月份 (覆盖 --half)")
    parser.add_argument("--end-month", type=int, default=None, help="显式结束月份 (覆盖 --half)")
    parser.add_argument("--port", type=int, default=DEFAULT_CDP_PORT, help="Chrome 调试端口")
    parser.add_argument("--no-import", action="store_true", help="仅下载不自动执行 gacc-import")
    args = parser.parse_args()

    if args.start_month is not None or args.end_month is not None:
        start_month = args.start_month if args.start_month is not None else 1
        end_month = args.end_month if args.end_month is not None else 6
    elif args.half.upper() == "H2":
        start_month, end_month = 7, 12
    else:
        start_month, end_month = 1, 6

    return run_automation(
        year=args.year,
        start_month=start_month,
        end_month=end_month,
        port=args.port,
        auto_import=not args.no_import,
    )


if __name__ == "__main__":
    sys.exit(main())
