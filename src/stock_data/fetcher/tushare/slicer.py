"""TuShare 多代码批量请求切片与合并调度工具。"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import polars as pl

from stock_core.utils.logger import logger


def batch_slice_and_merge(
    fetch_fn: Callable[..., pl.DataFrame],
    symbols: list[str],
    batch_size: int = 50,
    max_workers: int = 1,
    **kwargs: Any,
) -> pl.DataFrame:
    """自动将多个标的代码切片并发/分批发起请求，并将结果合并为单个 Polars DataFrame。

    Args:
        fetch_fn: 单次请求调用的回调函数（接受 ts_code 字符串参数）。
        symbols: 股票代码列表。
        batch_size: 批次切片大小（默认 50 只股票一组）。
        max_workers: 并发采集线程数（默认 1，即单线程顺序执行；>1 时多线程并发）。
        **kwargs: 传给 fetch_fn 的其他关键字参数。

    Returns:
        pl.DataFrame: 拼接合并后的完整 Polars DataFrame。
    """
    if not symbols:
        return pl.DataFrame()

    chunks = [symbols[i : i + batch_size] for i in range(0, len(symbols), batch_size)]
    logger.debug(
        f"执行批量切片请求: 总标的数 {len(symbols)}，切分 {len(chunks)} 批次，Worker并发数: {max_workers}"
    )

    def _fetch_chunk(chunk: list[str]) -> pl.DataFrame:
        ts_code_str = ",".join(chunk)
        return fetch_fn(ts_code=ts_code_str, **kwargs)

    results: list[pl.DataFrame] = []

    if max_workers > 1 and len(chunks) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            chunk_results = list(executor.map(_fetch_chunk, chunks))
        for df_chunk in chunk_results:
            if not df_chunk.is_empty():
                results.append(df_chunk)
    else:
        for idx, chunk in enumerate(chunks, 1):
            df_chunk = _fetch_chunk(chunk)
            if not df_chunk.is_empty():
                results.append(df_chunk)
            logger.debug(f"批次 [{idx}/{len(chunks)}] 完成，获取记录 {len(df_chunk)} 条")

    if not results:
        return pl.DataFrame()

    return pl.concat(results)
