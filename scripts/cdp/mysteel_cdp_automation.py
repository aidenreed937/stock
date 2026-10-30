#!/usr/bin/env python3
"""Mysteel (我的钢铁网 / 隆众能化) 多产品 CDP 智能自动化采集器。

基于 Chrome DevTools Protocol (CDP) 远程接管宿主机真实浏览器实例，
实现多大宗商品现货行情自动化导航、人机滑块协同感知、智能 DOM 解析与 2-Tier 黄金事实表入库。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import polars as pl  # noqa: E402
import websocket  # noqa: E402
import yaml  # noqa: E402

from stock_data.fetcher.industry.chemicals.models import ChemicalSpotPriceRecord  # noqa: E402
from stock_data.fetcher.industry.chemicals.parsers.mysteel_cdp import (  # noqa: E402
    MysteelArticleMeta,
    MysteelParsedQuote,
    parse_mysteel_article_list,
    parse_mysteel_html,
)
from stock_data.fetcher.industry.chemicals.transforms.spot_price import (  # noqa: E402
    materialize_spot_price_curated,
)

logger = logging.getLogger("mysteel_cdp")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

DEFAULT_CDP_PORT = 9222
DEFAULT_CONFIG_PATH = _ROOT / "config" / "industry" / "mysteel" / "products.yaml"
DEFAULT_SURVEY_CSV = (
    _ROOT
    / "data"
    / "raw"
    / "industry"
    / "chemicals"
    / "operating_rates"
    / "expert_prices_survey.csv"
)
DEFAULT_SNAPSHOT_DIR = _ROOT / "data" / "raw" / "industry" / "mysteel" / "snapshots"
DEFAULT_CURATED_DIR = _ROOT / "data" / "curated" / "industry"


class CdpClient:
    """轻量同步 Chrome DevTools Protocol 客户端。"""

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self._seq = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """向 CDP 发送方法指令并等待响应。"""
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

    def navigate(self, url: str) -> None:
        """导航至指定 URL 并等待初始加载。"""
        self.call("Page.navigate", {"url": url})
        time.sleep(2.5)

    def get_html(self) -> str:
        """提取完整 DOM outerHTML。"""
        html = self.evaluate("document.documentElement.outerHTML")
        return str(html) if html else ""

    def wait_for_human_verification(self, timeout_sec: int = 180) -> bool:
        """检测并人机协同等待极验滑块、点选、验证码或 WAF 频控冷却。"""
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
            print("【Mysteel 触发 WAF 频控拦截 (HTTP 411)】")
            print("-> 页面提示：“您的请求可能存在威胁，已被拦截！”")
            print("-> 正在自动休眠冷却（每 15 秒重新检测，或可切换网络/手机热点更换 IP）...")
            print("=" * 65 + "\n")
        else:
            print("\n" + "=" * 65)
            print("【请在已打开的 Chrome 浏览器中完成安全验证 (点选/滑块)】")
            print("-> Mysteel 页面触发了风控安全验证 (captcha.html / Geetest / 点选)！")
            print("-> 请在已打开的 Chrome 窗口中点击汉字或拖动滑块完成人机验证...")
            print("=" * 65 + "\n")

        start = time.time()
        last_reload = time.time()
        while time.time() - start < timeout_sec:
            time.sleep(2.0)
            if challenge_type == "waf_block" and time.time() - last_reload > 15.0:
                try:
                    self.call("Page.reload", {"ignoreCache": True})
                    last_reload = time.time()
                    time.sleep(2.0)
                except Exception:
                    pass
            try:
                curr_status = self.evaluate(check_challenge_js)
                if not curr_status:
                    logger.info("安全验证/WAF 频控已成功解除！继续执行自动化提取。")
                    time.sleep(2.0)
                    return True
                challenge_type = curr_status
            except Exception:
                return True

        logger.warning("安全验证/冷却等待超时 (%d 秒)，尝试继续提取。", timeout_sec)
        return False

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def is_port_open(port: int = DEFAULT_CDP_PORT) -> bool:
    """检查宿主机 CDP 调试端口是否开放。"""
    try:
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5)
        return int(req.getcode()) == 200
    except Exception:
        return False


def get_or_create_tab(port: int = DEFAULT_CDP_PORT) -> str:
    """获取可用页面标签页 WebSocket 调试地址。"""
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
        raise RuntimeError("无法在 Chrome 实例中新建标签页")
    return str(ws_url)


def load_products_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """加载产品目录配置文件。"""
    if not config_path.exists():
        raise FileNotFoundError(f"未找到产品配置文件: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return dict(data.get("products", {})) if isinstance(data, dict) else {}


def save_raw_snapshot(html: str, symbol: str, output_dir: Path | None = None) -> tuple[Path, str]:
    """保存原始 HTML 网页快照并计算 SHA-256。"""
    target_dir = output_dir or DEFAULT_SNAPSHOT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    now_tag = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    content_bytes = html.encode("utf-8")
    sha256 = hashlib.sha256(content_bytes).hexdigest()
    snapshot_path = target_dir / f"mysteel_{symbol}_{now_tag}.html"
    snapshot_path.write_bytes(content_bytes)
    return snapshot_path, sha256


def append_quotes_to_survey_csv(
    quotes: list[MysteelParsedQuote],
    csv_path: Path | None = None,
    sha256: str = "",
    snapshot_path: Path | None = None,
) -> int:
    """幂等追加抽取记录至 expert_prices_survey.csv。"""
    target_csv = csv_path or DEFAULT_SURVEY_CSV
    target_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trade_date",
        "report_date",
        "product_name",
        "symbol",
        "spec",
        "spot_price_cny",
        "unit",
        "source",
        "source_url",
        "release_date",
        "data_status",
        "collected_at",
        "raw_content_sha256",
        "raw_snapshot_path",
    ]

    existing_rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    if target_csv.exists():
        with target_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                k = (
                    str(r.get("symbol") or ""),
                    str(r.get("trade_date") or ""),
                    str(r.get("spec") or ""),
                )
                if k not in seen_keys:
                    seen_keys.add(k)
                    existing_rows.append(r)

    now_iso = datetime.now(UTC).isoformat()
    added = 0
    snap_str = str(snapshot_path) if snapshot_path else ""

    for q in quotes:
        key = (q.symbol, q.trade_date.isoformat(), q.spec)
        if key not in seen_keys:
            seen_keys.add(key)
            existing_rows.append(
                {
                    "trade_date": q.trade_date.isoformat(),
                    "report_date": q.trade_date.isoformat(),
                    "product_name": q.product_name,
                    "symbol": q.symbol,
                    "spec": q.spec,
                    "spot_price_cny": f"{q.price:.1f}",
                    "unit": q.unit,
                    "source": q.source,
                    "source_url": q.source_url,
                    "release_date": q.release_date.isoformat() if q.release_date else "",
                    "data_status": q.data_status,
                    "collected_at": now_iso,
                    "raw_content_sha256": sha256,
                    "raw_snapshot_path": snap_str,
                }
            )
            added += 1

    existing_rows.sort(
        key=lambda r: (
            str(r.get("symbol") or ""),
            str(r.get("trade_date") or ""),
            str(r.get("spec") or ""),
        )
    )

    with target_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)

    logger.info("已更新 %s (总行数: %d, 新增: %d)", target_csv.name, len(existing_rows), added)
    return added


def materialize_quotes_to_curated(
    quotes: list[MysteelParsedQuote],
    curated_dir: Path | None = None,
    sha256: str = "",
    snapshot_path: Path | None = None,
) -> pl.DataFrame:
    """将抽取记录转化为标准事实记录并幂等物化入 Curated chemical_spot_price.parquet。"""
    now_iso = datetime.now(UTC).isoformat()
    snap_str = str(snapshot_path) if snapshot_path else ""
    target_curated = curated_dir or DEFAULT_CURATED_DIR

    records: list[ChemicalSpotPriceRecord] = []
    for q in quotes:
        records.append(
            ChemicalSpotPriceRecord(
                product_name=q.product_name,
                symbol=q.symbol,
                trade_date=q.trade_date,
                spot_price_cny=q.price,
                spec=q.spec,
                region=q.region,
                unit=q.unit,
                source=q.source,
                source_url=q.source_url,
                release_date=q.release_date,
                data_status=q.data_status,
                collected_at=now_iso,
                raw_content_sha256=sha256,
                raw_snapshot_path=snap_str,
            )
        )

    records_dict: dict[str, list[ChemicalSpotPriceRecord]] = {}
    for r in records:
        records_dict.setdefault(r.symbol, []).append(r)
    for sym in records_dict:
        records_dict[sym].sort(key=lambda r: (r.trade_date, r.spec))

    return materialize_spot_price_curated(records_dict, target_curated)


def run_collection_for_product(
    cdp: CdpClient | None,
    product_meta: dict[str, Any],
    symbol: str,
    custom_url: str | None = None,
    offline_html: str | None = None,
) -> list[MysteelParsedQuote]:
    """对单个品种执行完整的抓取、解析与物化流程。"""
    prod_name = product_meta.get("product_name", symbol)
    target_url = custom_url or product_meta.get("default_url", "")
    logger.info("--- 开始采集品种 [%s: %s] ---", symbol, prod_name)

    if offline_html:
        html = offline_html
        logger.info("使用离线 HTML 文本模式进行解析 (长度: %d)", len(html))
    elif cdp is not None:
        if not target_url:
            logger.error("[%s] 未配置 target_url，跳过", symbol)
            return []
        logger.info("导航目标页面: %s", target_url)
        cdp.navigate(target_url)
        cdp.wait_for_human_verification()
        html = cdp.get_html()
    else:
        raise RuntimeError("未提供 CDP 客户端或离线 HTML 文本")

    if not html:
        logger.warning("[%s] 页面响应为空，跳过", symbol)
        return []

    # 1. 保存 RAW 快照
    snap_path, sha256 = save_raw_snapshot(html, symbol)
    logger.info("RAW 快照已落盘: %s (SHA-256: %s...)", snap_path.name, sha256[:12])

    # 2. 智能解析
    quotes = parse_mysteel_html(html, product_meta, source_url=target_url)
    logger.info("[%s] 成功解析到 %d 条现货报价记录", symbol, len(quotes))

    if not quotes:
        logger.warning("[%s] 未能从页面结构中识别出有效报价，请检查选择器或页面变动", symbol)
        return []

    # 3. 幂等更新 RAW survey CSV
    append_quotes_to_survey_csv(quotes, sha256=sha256, snapshot_path=snap_path)

    # 4. 物化入 Curated Parquet
    df_curated = materialize_quotes_to_curated(quotes, sha256=sha256, snapshot_path=snap_path)
    logger.info("[%s] Curated 物化完成 (当前总行数: %d)", symbol, len(df_curated))

    return quotes


def crawl_weekly_articles_flow(
    cdp: CdpClient,
    product_meta: dict[str, Any],
    symbol: str,
    pages: int = 3,
    max_articles: int = 55,
    sleep_sec: float = 6.0,
    direct_urls: list[str] | None = None,
) -> list[MysteelParsedQuote]:
    """多级爬虫：抓取历史周评列表 -> 逐篇翻页 -> 抽取表格/正文 -> 2-Tier 黄金事实表物化。"""
    import random

    prod_name = product_meta.get("product_name", symbol)
    url_template = product_meta.get("weekly_list_url_template")
    keywords = product_meta.get("weekly_keywords", [prod_name])

    # 预加载已有文章 URL 集合，避免重复抓取已入库的文章
    existing_urls: set[str] = set()
    if DEFAULT_SURVEY_CSV.exists():
        try:
            with DEFAULT_SURVEY_CSV.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    u = row.get("source_url")
                    if u:
                        existing_urls.add(u)
        except Exception:
            pass

    target_articles: list[MysteelArticleMeta] = []

    if direct_urls:
        logger.info("[%s] 采用直连指定 URL 模式 (共 %d 篇目标文章)", symbol, len(direct_urls))
        for u in direct_urls:
            target_articles.append(MysteelArticleMeta(title=f"直连周报: {u}", url=u))
    else:
        if not url_template:
            logger.error("[%s] 未配置 weekly_list_url_template，无法执行周评列表采集", symbol)
            return []

        logger.info("=== 开始多级周评采集流水线 [%s: %s] (页数: %d) ===", symbol, prod_name, pages)

        # 1. 第一级：翻页抓取周评文章列表 (List Stage)
        discovered_articles: list[MysteelArticleMeta] = []
        seen_urls: set[str] = set()

        for page_idx in range(1, pages + 1):
            list_url = url_template.format(page=page_idx)
            logger.info("正在检索周评列表页 [%d/%d]: %s", page_idx, pages, list_url)
            cdp.navigate(list_url)
            cdp.wait_for_human_verification()
            curr_url = str(cdp.evaluate("window.location.href") or "")
            if "captcha.html" in curr_url or list_url not in curr_url:
                cdp.navigate(list_url)
                cdp.wait_for_human_verification()
            list_html = cdp.get_html()
            page_articles = parse_mysteel_article_list(list_html, keywords=keywords)
            for art in page_articles:
                if art.url not in seen_urls:
                    seen_urls.add(art.url)
                    discovered_articles.append(art)
            time.sleep(max(2.0, sleep_sec / 2.0))

        logger.info("[%s] 共发现 %d 篇匹配周评文章", symbol, len(discovered_articles))
        if not discovered_articles:
            logger.warning("[%s] 未检索到有效周评文章，流程结束", symbol)
            return []

        # 先排除已入库的文章，再截取目标篇数
        unfetched = [a for a in discovered_articles if a.url not in existing_urls]
        logger.info(
            "[%s] 待抓取未入库周评: %d 篇 (总发现 %d, 历史已入库 %d)",
            symbol,
            len(unfetched),
            len(discovered_articles),
            len(discovered_articles) - len(unfetched),
        )
        target_articles = unfetched[:max_articles]

    all_quotes: list[MysteelParsedQuote] = []

    # 2. 第二级 & 第三级：逐篇翻页采集与抽取 (Fetch & Extract Stage)
    for idx, art in enumerate(target_articles, 1):
        if art.url in existing_urls and not direct_urls:
            logger.info(
                "  [跳过已入库] [%d/%d]: %s (%s)", idx, len(target_articles), art.title, art.url
            )
            continue
        logger.info("正在深度抓取 [%d/%d]: %s (%s)", idx, len(target_articles), art.title, art.url)
        try:
            cdp.navigate(art.url)
            cdp.wait_for_human_verification()
            art_html = cdp.get_html()
            if not art_html:
                logger.warning("文章页面内容为空: %s", art.url)
                continue

            snap_path, sha256 = save_raw_snapshot(art_html, f"{symbol}_weekly_{idx}")
            quotes = parse_mysteel_html(art_html, product_meta, source_url=art.url)
            logger.info("  -> 提取到 %d 条报价记录", len(quotes))
            for q in quotes:
                all_quotes.append(q)
                append_quotes_to_survey_csv([q], sha256=sha256, snapshot_path=snap_path)

            # 拉大请求间隔，加入随机扰动以防触发 WAF 频控
            jitter = random.uniform(1.0, 2.5)
            actual_sleep = sleep_sec + jitter
            logger.info("  [频控防刷休眠] 等待 %.1f 秒后继续...", actual_sleep)
            time.sleep(actual_sleep)
        except Exception as err:
            logger.warning("抓取文章出错 %s: %s", art.url, err)

    logger.info("[%s] 周评采集完成，累计抽取 %d 条现货报价", symbol, len(all_quotes))
    if all_quotes:
        df_curated = materialize_quotes_to_curated(all_quotes)
        logger.info("[%s] Curated 物化更新完成 (当前总行数: %d)", symbol, len(df_curated))

    return all_quotes


def main() -> int:
    parser = argparse.ArgumentParser(description="Mysteel CDP 多产品智能自动化采集器")
    parser.add_argument("--symbol", type=str, help="指定采集的品种代码 (如 Ti_sponge, ilmenite)")
    parser.add_argument("--all", action="store_true", help="采集 products.yaml 中配置的全部品种")
    parser.add_argument("--url", type=str, help="覆盖品种的抓取目标 URL")
    parser.add_argument("--port", type=int, default=DEFAULT_CDP_PORT, help="Chrome 调试端口")
    parser.add_argument("--offline-html", type=Path, help="离线 HTML 文件路径 (用于回归测试)")
    parser.add_argument(
        "--crawl-weekly",
        action="store_true",
        help="开启多级周报翻页采集流程 (列表翻页 -> 逐篇正文抽取 -> 物化)",
    )
    parser.add_argument("--pages", type=int, default=3, help="周报列表翻页页数 (默认 3 页)")
    parser.add_argument(
        "--max-articles",
        type=int,
        default=55,
        help="周报最大抓取篇数 (默认 55 篇，覆盖 1 年)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=6.0,
        help="单篇抓取间隔休眠秒数 (默认 6.0 秒，加入 1~2.5 秒随机抖动以防频控)",
    )
    parser.add_argument(
        "--urls",
        nargs="+",
        type=str,
        help="直接指定文章 URL 列表执行采集 (跳过列表翻页检索)",
    )
    args = parser.parse_args()

    products_cfg = load_products_config()
    targets: list[str] = []

    if args.symbol:
        if args.symbol not in products_cfg:
            logger.error("未在配置中找到品种: %s (可用: %s)", args.symbol, list(products_cfg))
            return 1
        targets = [args.symbol]
    elif args.all:
        targets = list(products_cfg.keys())
    else:
        logger.info("未指定 --symbol 或 --all，默认采集 Ti_sponge (海绵钛)")
        targets = ["Ti_sponge"]

    # 离线模式
    if args.offline_html:
        if not args.offline_html.exists():
            logger.error("离线 HTML 文件不存在: %s", args.offline_html)
            return 1
        content = args.offline_html.read_text(encoding="utf-8")
        for sym in targets:
            meta = dict(products_cfg[sym])
            meta["symbol"] = sym
            run_collection_for_product(None, meta, sym, offline_html=content)
        return 0

    # CDP 在线模式
    if not is_port_open(args.port):
        print("\n" + "=" * 65)
        print(f"【无法连接至 Chrome CDP 端口: {args.port}】")
        print("请在 macOS 宿主机终端中执行以下命令拉起 Chrome 调试实例：")
        print("  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\")
        print(f"    --remote-debugging-port={args.port} \\")
        print('    --user-data-dir="/tmp/chrome_mysteel_profile" &')
        print("=" * 65 + "\n")
        return 1

    ws_url = get_or_create_tab(args.port)
    cdp = CdpClient(ws_url)
    try:
        for sym in targets:
            meta = dict(products_cfg[sym])
            meta["symbol"] = sym
            if args.crawl_weekly or args.urls:
                pages = args.pages or meta.get("default_pages", 3)
                crawl_weekly_articles_flow(
                    cdp,
                    meta,
                    sym,
                    pages=pages,
                    max_articles=args.max_articles,
                    sleep_sec=args.sleep,
                    direct_urls=args.urls,
                )
            else:
                run_collection_for_product(cdp, meta, sym, custom_url=args.url)
    finally:
        cdp.close()

    logger.info("全部指定品种采集与物化流程执行完毕。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
