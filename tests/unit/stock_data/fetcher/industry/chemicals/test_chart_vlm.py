"""ChartVlmParser 单元测试。

验证:
1. PDF 页面渲染为高清 Base64 图片 (PyMuPDF);
2. LiteLLM 统一抽象调用与 Tenacity 重试机制 (Mock 模式);
3. JSON 响应解析、Pydantic 验证与容错清洗;
4. 结构化结果落盘为标准年度产能 CSV 及单位换算 (亿吨 -> 万吨)。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock_data.fetcher.industry.chemicals.parsers.chart_vlm import (
    ChartVlmExtractionResult,
    ChartVlmParser,
    ExtractedDataPoint,
)


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """创建一个微型测试 PDF。"""
    import pymupdf

    pdf_path = tmp_path / "test_report.pdf"
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "图15: PVC 产能及产量 (万吨)")
    page.insert_text((50, 100), "数据来源: 百川盈孚")
    doc.save(str(pdf_path))  # type: ignore[no-untyped-call]
    doc.close()  # type: ignore[no-untyped-call]
    return pdf_path


def test_render_pdf_page_to_base64(sample_pdf: Path) -> None:
    """测试 PDF 页面渲染与 Base64 编码。"""
    parser = ChartVlmParser(model="gemini/gemini-2.5-flash")
    b64_str, data_url = parser.render_pdf_page_to_base64(sample_pdf, page_number=1, dpi=72)
    assert len(b64_str) > 0
    assert data_url.startswith("data:image/png;base64,")


def test_render_pdf_page_invalid_page(sample_pdf: Path) -> None:
    """测试无效页码抛出异常。"""
    parser = ChartVlmParser()
    with pytest.raises(IndexError):
        parser.render_pdf_page_to_base64(sample_pdf, page_number=99)


def test_parse_and_validate_response_markdown_json() -> None:
    """测试清洗被 Markdown 围栏包裹的 JSON。"""
    parser = ChartVlmParser()
    raw = """
    ```json
    {
        "product": "pvc",
        "metric": "effective_capacity",
        "unit": "万吨",
        "chart_title": "图15：PVC 产能投放接近尾声",
        "source_declared": "百川盈孚",
        "data_points": [
            {"year": 2016, "value": 2320.0, "confidence": "high"},
            {"year": 2017, "value": 2410.0, "confidence": "high"}
        ],
        "notes": "测试备注"
    }
    ```
    """
    res = parser._parse_and_validate_response(raw, "pvc", "effective_capacity")
    assert res.product == "pvc"
    assert res.chart_title == "图15：PVC 产能投放接近尾声"
    assert len(res.data_points) == 2
    assert res.data_points[0].year == 2016
    assert res.data_points[0].value == 2320.0


def test_parse_and_validate_response_invalid_json() -> None:
    """测试非 JSON 内容报错。"""
    parser = ChartVlmParser()
    with pytest.raises(ValueError, match="无法解析 VLM 输出为 JSON"):
        parser._parse_and_validate_response("This is not json", "pvc", "effective_capacity")


def test_save_to_annual_capacity_csv(tmp_path: Path) -> None:
    """测试结果落盘 CSV 及亿吨自动换算为万吨。"""
    result = ChartVlmExtractionResult(
        product="methanol",
        metric="effective_capacity",
        unit="亿吨",
        chart_title="图：中国甲醇产能",
        source_declared="智研咨询",
        data_points=[
            ExtractedDataPoint(year=2020, value=0.91, confidence="high"),
            ExtractedDataPoint(year=2025, value=1.15, confidence="high"),
        ],
    )
    dest_csv = tmp_path / "methanol_annual_capacity.csv"
    meta = {
        "title": "中国甲醇深度报告",
        "publishDate": "2026-10-10",
        "infoCode": "AP123456",
    }
    ChartVlmParser.save_to_annual_capacity_csv(result, dest_csv, report_meta=meta)

    content = dest_csv.read_text(encoding="utf-8")
    lines = content.strip().splitlines()
    assert lines[0] == "year,effective_capacity_w_tons,is_forecast,data_source,notes"
    # 0.91 亿吨 -> 9100.0 万吨
    assert "2020,9100.0,false,智研咨询,[实际落地]" in lines[1]
    # 1.15 亿吨 -> 11500.0 万吨
    assert "2025,11500.0,false,智研咨询,[实际落地]" in lines[2]


@patch("litellm.completion")
def test_execute_litellm_call_with_tenacity_retry(mock_completion: MagicMock) -> None:
    """测试 Tenacity 指数退避重试机制。"""
    # 前两次抛出异常，第三次成功
    success_resp = MagicMock()
    success_resp.choices = [MagicMock(message=MagicMock(content='{"status": "ok"}'))]
    mock_completion.side_effect = [
        ConnectionError("网络闪断"),
        TimeoutError("超时"),
        success_resp,
    ]

    parser = ChartVlmParser(model="gemini/gemini-2.5-flash", stream=False)
    messages = [{"role": "user", "content": "hello"}]
    res = parser._execute_litellm_call(messages, "gemini/gemini-2.5-flash")
    assert res == '{"status": "ok"}'
    assert mock_completion.call_count == 3


@patch("litellm.completion")
def test_execute_litellm_call_streaming(mock_completion: MagicMock) -> None:
    """测试流式 stream=True 分块接收与思考链聚合。"""
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock(delta=MagicMock(reasoning_content="正在思考...", content=None))]
    chunk2 = MagicMock()
    chunk2.choices = [
        MagicMock(delta=MagicMock(reasoning_content=None, content='{"status": "ok"}'))
    ]
    mock_completion.return_value = [chunk1, chunk2]

    parser = ChartVlmParser(model="gemini/gemini-2.5-flash", stream=True)
    messages = [{"role": "user", "content": "hello"}]
    res = parser._execute_litellm_call(messages, "gemini/gemini-2.5-flash")
    assert res == '{"status": "ok"}'
