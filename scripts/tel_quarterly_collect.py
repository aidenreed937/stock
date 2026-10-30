"""Tokyo Electron (TEL, 日股 8035.T) 季度财报决算短信采集器（日本 IR 官方源）。

Stage 2 四巨头补全：TEL 不在 SEC EDGAR（日股），走日本 IR 官网英文版
「Summary of Consolidated Financial Results (Japanese GAAP)」PDF（tanshin）。

数据源：https://www.tel.com/ir/library/report/ 的 tanshin-e.pdf 列表（覆盖 2011-2026）。
release_date 取 PDF 首页声明的 earnings release 日期（如 "April 30, 2026"），无前视。

TEL 口径限制（诚实标注，与美系三家不同）：
- 日本 GAAP，GM 需从损益表 (Net sales − Cost of sales) 计算，且为累计口径需差分单季；
- 无下季 GM 指引（只给 net sales/operating income 预测）→ 无法构建 guidance/expansion 腿；
- 无服务/产品拆分 → 无法构建 ibm 腿。
=> TEL 仅能贡献「GM 实际值水平腿」（gm_level），不进入 gm_leading 前瞻复合。

用法：uv run --with pypdf python scripts/tel_quarterly_collect.py
"""

from __future__ import annotations

import logging
import re
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

BASE = "https://www.tel.com"
REPORT_URL = "https://www.tel.com/ir/library/report/"
RAW_DIR = Path("data/raw/industry/semiconductor/equipment/tel/ir_tanshin")

UA = {"User-Agent": "AntigravityResearch/1.0 (contact@research.antigravity.org)"}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)  # noqa: S310
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return resp.read()


def list_tanshin_urls() -> list[str]:
    """抓 report 页面，提取全部 tanshin-e.pdf 相对 URL。"""
    html = _get(REPORT_URL).decode("utf-8", "ignore")
    urls = re.findall(r'href="([^"]*tanshin-e\.pdf)"', html)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urls = list_tanshin_urls()
    logger.info("发现 %d 个 TEL tanshin PDF", len(urls))
    ok = 0
    for u in urls:
        name = u.rsplit("/", 1)[-1]
        raw_path = RAW_DIR / name
        if raw_path.exists():
            ok += 1
            continue
        try:
            content = _get(BASE + u)
        except Exception as e:
            logger.warning("下载失败 [%s]: %s", name, e)
            continue
        if len(content) < 10000:
            logger.warning("过小跳过 [%s len=%d]", name, len(content))
            continue
        raw_path.write_bytes(content)
        ok += 1
        time.sleep(0.5)
    logger.info("完成：%d/%d 落盘 %s", ok, len(urls), RAW_DIR)


if __name__ == "__main__":
    main()
