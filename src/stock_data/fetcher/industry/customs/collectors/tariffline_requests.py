"""Tariffline HTTP 请求与重试实现。"""

from __future__ import annotations

import logging
import multiprocessing as mp
import signal
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, cast

from stock_data.fetcher.industry.customs.collectors.tariffline_types import (
    _HTTP_CONNECT_TIMEOUT_SECONDS,
    _REQUEST_TIMEOUT_SECONDS,
    _TARIFFLINE_API_URL,
    TarifflineCallLimiter,
    TarifflineStatus,
    _raise_request_timeout,
)

logger = logging.getLogger(__name__)


def request_kwargs(
    *,
    subscription_key: str,
    periods: Sequence[str],
    flow_code: str,
    cmd_code: str,
    max_records: int,
) -> dict[str, Any]:
    return {
        "subscription_key": subscription_key,
        "typeCode": "C",
        "freqCode": "M",
        "clCode": "HS",
        "period": ",".join(periods),
        "reporterCode": "156",
        "cmdCode": cmd_code,
        "flowCode": flow_code,
        "partnerCode": None,
        "partner2Code": None,
        "customsCode": None,
        "motCode": None,
        "maxRecords": max_records,
        "format_output": "JSON",
        "includeDesc": True,
    }


def fetch_dataframe(**request: Any) -> Any:
    """以可控长读超时调用官方 Tariffline REST 接口。"""
    import pandas as pd
    import requests

    params = {
        "reporterCode": request["reporterCode"],
        "flowCode": request["flowCode"],
        "period": request["period"],
        "cmdCode": request["cmdCode"],
        "partnerCode": request["partnerCode"],
        "partner2Code": request["partner2Code"],
        "motCode": request["motCode"],
        "customsCode": request["customsCode"],
        "maxRecords": request["maxRecords"],
        "format": request["format_output"],
        "includeDesc": request["includeDesc"],
        "subscription-key": request["subscription_key"],
    }
    params = {key: value for key, value in params.items() if value is not None}
    response = requests.get(
        _TARIFFLINE_API_URL,
        params=params,
        timeout=(_HTTP_CONNECT_TIMEOUT_SECONDS, _REQUEST_TIMEOUT_SECONDS),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Tariffline API 返回格式不是对象")
    data = payload.get("data", []) or []
    if not isinstance(data, list):
        raise ValueError("Tariffline API data 不是列表")
    return pd.json_normalize(data)


def classify_frame(frame: Any, max_records: int) -> tuple[TarifflineStatus, list[dict[str, Any]]]:
    if frame is None:
        return "failed", []
    if frame.empty:
        return "empty", []
    records = cast("list[dict[str, Any]]", frame.to_dict(orient="records"))
    return ("truncated", records) if len(records) >= max_records else ("success", records)


def _request_worker(connection: Any, request: dict[str, Any], max_records: int) -> None:
    try:
        connection.send((*classify_frame(fetch_dataframe(**request), max_records), ""))
    except BaseException as exc:
        connection.send(("failed", [], f"{type(exc).__name__}: {exc}"))
    finally:
        connection.close()


def request_batch_isolated(
    *,
    subscription_key: str,
    periods: Sequence[str],
    flow_code: str,
    cmd_code: str,
    max_records: int,
) -> tuple[TarifflineStatus, list[dict[str, Any]]]:
    """隔离执行单次请求，并对整个请求设置硬超时。"""
    context_name = (
        "fork"
        if threading.current_thread() is threading.main_thread()
        and "fork" in mp.get_all_start_methods()
        else "spawn"
    )
    context = cast("Any", mp.get_context(context_name))
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_request_worker,
        args=(
            child,
            request_kwargs(
                subscription_key=subscription_key,
                periods=periods,
                flow_code=flow_code,
                cmd_code=cmd_code,
                max_records=max_records,
            ),
            max_records,
        ),
    )
    process.start()
    child.close()
    deadline = time.monotonic() + _REQUEST_TIMEOUT_SECONDS
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "failed", []
            if parent.poll(min(0.25, remaining)):
                try:
                    status, records, error = parent.recv()
                except (EOFError, OSError):
                    return "failed", []
                if status == "failed" and error:
                    logger.warning("Tariffline 请求失败: %s", error)
                return status, records
            if not process.is_alive():
                return "failed", []
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        parent.close()


def request_batch(
    *,
    fetcher: Callable[..., Any],
    subscription_key: str,
    periods: Sequence[str],
    flow_code: str,
    cmd_code: str,
    max_records: int,
) -> tuple[TarifflineStatus, list[dict[str, Any]]]:
    """执行一次最小 Tariffline 请求。"""
    try:
        previous_handler: Any | None = None
        if threading.current_thread() is threading.main_thread():
            previous_handler = signal.signal(signal.SIGALRM, _raise_request_timeout)
            signal.setitimer(signal.ITIMER_REAL, _REQUEST_TIMEOUT_SECONDS)
        try:
            frame = fetcher(
                **request_kwargs(
                    subscription_key=subscription_key,
                    periods=periods,
                    flow_code=flow_code,
                    cmd_code=cmd_code,
                    max_records=max_records,
                )
            )
        finally:
            if previous_handler is not None:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous_handler)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Tariffline 请求失败: periods=%s, flow=%s, cmdCode=%s, error=%s",
            ",".join(periods),
            flow_code,
            cmd_code,
            exc,
        )
        return "failed", []
    return classify_frame(frame, max_records)


def request_with_retry(
    *,
    fetcher: Callable[..., Any],
    subscription_key: str,
    periods: Sequence[str],
    flow_code: str,
    cmd_code: str,
    max_records: int,
    retries: int,
    retry_sleep_seconds: float,
    isolate: bool = False,
    limiter: TarifflineCallLimiter | None = None,
) -> tuple[TarifflineStatus, list[dict[str, Any]]]:
    """对网络失败做有限重试，不对截断结果盲目重试。"""
    request_limiter = limiter or TarifflineCallLimiter()
    for attempt in range(retries + 1):
        request_limiter.acquire()
        if isolate:
            status, records = request_batch_isolated(
                subscription_key=subscription_key,
                periods=periods,
                flow_code=flow_code,
                cmd_code=cmd_code,
                max_records=max_records,
            )
        else:
            status, records = request_batch(
                fetcher=fetcher,
                subscription_key=subscription_key,
                periods=periods,
                flow_code=flow_code,
                cmd_code=cmd_code,
                max_records=max_records,
            )
        if status != "failed" or attempt == retries:
            return status, records
        if retry_sleep_seconds > 0:
            time.sleep(retry_sleep_seconds * (attempt + 1))
    return "failed", []


__all__ = ["fetch_dataframe", "request_kwargs", "request_with_retry"]
