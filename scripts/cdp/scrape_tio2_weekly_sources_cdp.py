#!/usr/bin/env python3
"""Mysteel 钛白粉官方周/月评专栏 CDP 深度分页扫描与链接同步工具。

通过宿主机原生 Chrome CDP 实例接管浏览器，穿透 WAF 滑块/点选验证码，
全量抓取专栏列表页（https://nenghua.mysteel.com/list/article/pa11530aaaaaa{page}.html），
将 2024~2026 年（100+ 自然周）的真实连续周评链接注入 config/data_sources/chemicals_weekly_sources.csv。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import websocket  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

logger = logging.getLogger("scrape_tio2_cdp")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

DEFAULT_CDP_PORT = 9222
TIO2_WEEKLY_LIST_TEMPLATE = "https://nenghua.mysteel.com/list/article/pa11530aaaaaa{page}.html"
CSV_PATH = _ROOT / "config" / "data_sources" / "chemicals_weekly_sources.csv"


class CdpClient:
    """轻量同步 Chrome DevTools Protocol 客户端。"""

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self._seq = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
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
                return dict(data.get("result", {}))

    def evaluate(self, expression: str) -> Any:
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

    def navigate(self, url: str) -> None:
        self.call("Page.navigate", {"url": url})
        time.sleep(2.5)

    def get_html(self) -> str:
        html = self.evaluate("document.documentElement.outerHTML")
        return str(html) if html else ""

    def wait_for_human_verification(self, timeout_sec: int = 180) -> bool:
        check_challenge_js = """(() => {
            if (window.location.href.includes('captcha.html') || document.title.includes('安全验证')) {
                return 'captcha';
            }
            const el = document.querySelector('.geetest_radar, .geetest_slider, .geetest_popup, .nc_wrapper, #login-box, .login-modal');
            if (el) {
                const style = window.getComputedStyle(el);
                if (style && style.display !== 'none' && style.visibility !== 'hidden') return 'captcha';
            }
            if (
                document.title.includes('安全威胁') ||
                document.title.includes('已被阻断') ||
                (document.body && (document.body.innerText.includes('已被拦截') || document.body.innerText.includes('411')))
            ) {
                return 'waf_block';
            }
            return null;
        })()"""
        try:
            challenge_type = self.evaluate(check_challenge_js)
        except Exception:
            challenge_type = None

        if not challenge_type:
            return True

        if challenge_type == "waf_block":
            print("\n" + "=" * 65)
            print("【Mysteel 触发 WAF 拦截 (HTTP 411)】")
            print("-> 页面提示：“您的请求可能存在威胁，已被拦截！”")
            print("-> 正在自动冷却重试 (若持续出现可切换手机热点)...")
            print("=" * 65 + "\n")
        else:
            print("\n" + "=" * 65)
            print("【请在已打开的 Chrome 浏览器中完成安全验证 (点选/滑块)】")
            print("-> Mysteel 页面触发了风控安全验证 (captcha.html / Geetest)！")
            print("-> 请在 Chrome 窗口中点击汉字或拖动滑块完成验证...")
            print("=" * 65 + "\n")

        start = time.time()
        last_reload = time.time()
        while time.time() - start < timeout_sec:
            time.sleep(2.0)
            if challenge_type == "waf_block" and time.time() - last_reload > 15.0:
                try:
                    self.call("Page.reload", {"ignoreCache": True})
                    last_reload = time.time()
                    time.sleep(2.5)
                except Exception:
                    pass
            try:
                curr_status = self.evaluate(check_challenge_js)
                if not curr_status:
                    logger.info("安全验证/拦截已成功解除！继续执行列表页抓取。")
                    time.sleep(2.0)
                    return True
                challenge_type = curr_status
            except Exception:
                return True

        logger.warning("安全验证等待超时 (%d 秒)。", timeout_sec)
        return False

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def get_ws_url(port: int = DEFAULT_CDP_PORT) -> str:
    url = f"http://127.0.0.1:{port}/json"
    req = urllib.request.urlopen(url, timeout=2.5)
    tabs: list[dict[str, Any]] = json.loads(req.read().decode())
    page_tabs = [t for t in tabs if t.get("type") == "page"]
    if page_tabs:
        ws_url = page_tabs[0].get("webSocketDebuggerUrl")
        if ws_url:
            return str(ws_url)

    create_url = f"http://127.0.0.1:{port}/json/new"
    req_new = urllib.request.urlopen(create_url, timeout=2.5)
    new_tab = json.loads(req_new.read().decode())
    ws_url = new_tab.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("无法在 Chrome 实例中获取可用标签页")
    return str(ws_url)


def parse_weekly_articles_from_html(html: str) -> list[dict[str, str]]:
    """从专栏列表页 HTML 提取周评文章链接、标题与基准日。"""
    soup = BeautifulSoup(html, "html.parser")
    articles: list[dict[str, str]] = []
    seen: set[str] = set()

    for a in soup.find_all(
        "a", href=re.compile(r"/a/(\d{2})(\d{2})(\d{2})\d{2}/[A-F0-9a-zA-Z_]+\.html")
    ):
        title = a.get_text().strip()
        href = a["href"].strip()
        if href.startswith("//"):
            href = "https:" + href
        href = re.sub(r"https?://nenghua\.m\.mysteel\.com", "https://nenghua.mysteel.com", href)
        href = re.sub(r"_abc\.html", ".html", href)

        if href in seen:
            continue

        # 匹配日期 /a/YYMMDDHH/...
        m = re.search(r"/a/(\d{2})(\d{2})(\d{2})\d{2}/", href)
        if not m:
            continue
        d_str = f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"

        # 重点保留周评、周度数据分析与相关生产动态
        is_weekly = (
            "周评" in title
            or "周度数据" in title
            or "国内钛白粉市场" in title
            or (
                "钛白粉" in title
                and any(k in title for k in ["整理", "稳", "盘整", "下行", "上行", "运行", "博弈"])
            )
        )
        if is_weekly and "早间提示" not in title:
            seen.add(href)
            articles.append(
                {
                    "product_name": "钛白粉",
                    "symbol": "TIO2",
                    "report_date": d_str,
                    "source_url": href,
                    "title": title,
                }
            )
    return articles


def sync_to_sources_csv(new_items: list[dict[str, str]], csv_path: Path = CSV_PATH) -> int:
    """将发现的周评幂等合并写入 config/data_sources/chemicals_weekly_sources.csv。"""
    existing: dict[tuple[str, str, str], dict[str, str]] = {}
    fieldnames = ["product_name", "symbol", "report_date", "source_url"]

    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                key = (r.get("product_name", ""), r.get("symbol", ""), r.get("report_date", ""))
                existing[key] = {k: r.get(k, "") for k in fieldnames}

    added = 0
    for item in new_items:
        key = (item["product_name"], item["symbol"], item["report_date"])
        if key not in existing:
            existing[key] = {
                "product_name": item["product_name"],
                "symbol": item["symbol"],
                "report_date": item["report_date"],
                "source_url": item["source_url"],
            }
            added += 1

    # 排序并写回
    all_rows = list(existing.values())
    all_rows.sort(key=lambda r: (r["product_name"], r["report_date"]), reverse=True)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info("已将 %d 篇新周评源写入 %s，当前总配置数: %d", added, csv_path, len(all_rows))
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description="Mysteel 钛白粉官方周评专栏 CDP 分页扫描")
    parser.add_argument("--port", type=int, default=DEFAULT_CDP_PORT, help="CDP 端口")
    parser.add_argument("--max-pages", type=int, default=15, help="最大扫描页数 (默认 15 页)")
    parser.add_argument(
        "--min-delay", type=float, default=4.0, help="翻页最小随机等待秒数 (默认 4.0)"
    )
    parser.add_argument(
        "--max-delay", type=float, default=7.5, help="翻页最大随机等待秒数 (默认 7.5)"
    )
    args = parser.parse_args()

    logger.info("正在连接宿主机 Chrome CDP 调试端口: %d ...", args.port)
    try:
        ws_url = get_ws_url(args.port)
    except Exception as exc:
        logger.error(
            "无法连接 Chrome CDP 实例 (端口 %d): %s\n"
            "请先在 macOS 终端拉起调试版 Chrome:\n"
            "  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
            '--remote-debugging-port=%d --user-data-dir="/tmp/chrome_mysteel_profile" &',
            args.port,
            exc,
            args.port,
        )
        sys.exit(1)

    client = CdpClient(ws_url)
    all_discovered: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    try:
        # 1. 预热访问专区首页，建立合法 Referer 与 Cookie 上下文，防止直突列表页触发 WAF 411
        breed_url = "https://nenghua.mysteel.com/breed/taibaifen/"
        logger.info("CDP 预热访问钛白粉专区首页以建立会话状态: %s", breed_url)
        client.navigate(breed_url)
        client.wait_for_human_verification()
        time.sleep(3.0)

        for page in range(1, args.max_pages + 1):
            url = TIO2_WEEKLY_LIST_TEMPLATE.format(page=page)
            delay_sec = random.uniform(args.min_delay, args.max_delay)
            logger.info("CDP 导航至专栏第 %d 页 (礼貌延时 %.1f 秒): %s", page, delay_sec, url)
            client.navigate(url)

            # 检测滑块验证码 / WAF 状态
            client.wait_for_human_verification()

            # 模拟轻微平滑滚动以触发完整 DOM 加载
            try:
                client.evaluate("window.scrollTo(0, 300)")
            except Exception:
                pass
            time.sleep(1.5)

            html = client.get_html()
            page_articles = parse_weekly_articles_from_html(html)
            logger.info("第 %d 页提取出 %d 篇周评文章", page, len(page_articles))

            if not page_articles:
                logger.info("第 %d 页未解析出文章，可能已到达最末页或触发空列表，停止扫描。", page)
                break

            for a in page_articles:
                if a["source_url"] not in seen_urls:
                    seen_urls.add(a["source_url"])
                    all_discovered.append(a)

            # 翻页间礼貌休眠，模拟真人阅读
            time.sleep(delay_sec)

        logger.info("CDP 扫描完成，全量去重共发现 %d 篇钛白粉周评文章！", len(all_discovered))
        added = sync_to_sources_csv(all_discovered)
        logger.info("增量同步完成，新增 %d 条新周评配置。", added)
    finally:
        client.close()


if __name__ == "__main__":
    main()
