"""WSTS 历史底表动态嗅探与下载解析单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from stock_data.fetcher.industry.semiconductor.collectors.sales import (
    DEFAULT_WSTS_EXCEL_FILENAME,
    DEFAULT_WSTS_EXCEL_URL,
    SemiconductorCollector,
)
from stock_data.fetcher.industry.semiconductor.parsers.sales import (
    extract_wsts_excel_download_url,
)

SAMPLE_WSTS_HTML = """
<!DOCTYPE html>
<html>
<body>
<div class="content">
    <h2>Historical Billings Report</h2>
    <p>Please download below:</p>
    <ul>
        <li><a href="https://www.wsts.org/esraCMS/extension/media/f/WST/7735/WSTS-Historical-Billings-Report-Jun_2026.xlsx">Historical Billings Report ( XLSX | 154,48 kB )</a></li>
        <li><a href="https://www.wsts.org/esraCMS/extension/media/f/WST/7736/WSTS-Monthly_data_-_3MMA_-_Jun_2026.pdf">Monthly data - 3MMA ( PDF | 1,12 MB )</a></li>
    </ul>
</div>
</body>
</html>
"""

SAMPLE_WSTS_HTML_RELATIVE = """
<!DOCTYPE html>
<html>
<body>
<a href="/esraCMS/extension/media/f/WST/8888/WSTS-Historical-Billings-Report-Jul_2026.xlsx">Historical Billings Report</a>
</body>
</html>
"""


def test_extract_wsts_excel_download_url_absolute() -> None:
    result = extract_wsts_excel_download_url(SAMPLE_WSTS_HTML)
    assert result is not None
    url, filename = result
    assert (
        url
        == "https://www.wsts.org/esraCMS/extension/media/f/WST/7735/WSTS-Historical-Billings-Report-Jun_2026.xlsx"
    )
    assert filename == "WSTS-Historical-Billings-Report-Jun_2026.xlsx"


def test_extract_wsts_excel_download_url_relative() -> None:
    result = extract_wsts_excel_download_url(SAMPLE_WSTS_HTML_RELATIVE)
    assert result is not None
    url, filename = result
    assert (
        url
        == "https://www.wsts.org/esraCMS/extension/media/f/WST/8888/WSTS-Historical-Billings-Report-Jul_2026.xlsx"
    )
    assert filename == "WSTS-Historical-Billings-Report-Jul_2026.xlsx"


def test_extract_wsts_excel_download_url_none() -> None:
    result = extract_wsts_excel_download_url("<html><body>No excel links here</body></html>")
    assert result is None


def test_collector_discover_target_success(tmp_path: Path) -> None:
    collector = SemiconductorCollector(raw_dir=tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_WSTS_HTML_RELATIVE

    with patch("curl_cffi.requests.get", return_value=mock_resp):
        url, filename = collector._discover_wsts_excel_target()
        assert filename == "WSTS-Historical-Billings-Report-Jul_2026.xlsx"
        assert "8888" in url


def test_collector_discover_target_fallback(tmp_path: Path) -> None:
    collector = SemiconductorCollector(raw_dir=tmp_path)
    with patch("curl_cffi.requests.get", side_effect=RuntimeError("Network down")):
        url, filename = collector._discover_wsts_excel_target()
        assert url == DEFAULT_WSTS_EXCEL_URL
        assert filename == DEFAULT_WSTS_EXCEL_FILENAME
