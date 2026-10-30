"""基于多模态视觉大模型 (VLM) 的研报图表历史时序数据逆向解析器。

职责:
1. 利用 PyMuPDF 将券商研报指定关键页或裁剪区域渲染为高清图像;
2. 通过 LiteLLM 统一抽象层调用具备视觉能力的多模态大模型 (Gemini, Claude, GPT-4o, DeepSeek, Ollama 等);
3. 结合 Tenacity 实现指数退避重试 (防网络闪断、API 限流与高并发波动);
4. 结构化逆向提取柱状图/折线图中的历史连续时序数据 (如 2016-2025 年有效产能、产量);
5. 执行 Pydantic 字段级强校验与单位标准化换算，输出经审计认证的年度产能数据。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, cast

import litellm
import pymupdf
from pydantic import BaseModel, Field
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from stock_core.config.settings import settings

logger = logging.getLogger(__name__)

# 关闭 litellm 冗余 debug 日志及远程 cost 映射阻塞
litellm.suppress_debug_info = True
litellm.drop_params = True
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

_VLM_RETRY = Retrying(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((Exception,)),
    reraise=True,
)


class ExtractedDataPoint(BaseModel):
    """单个年份的数据点。"""

    year: int = Field(..., description="年份，如 2018")
    value: float = Field(..., description="数值")
    confidence: str = Field(default="high", description="置信度: high / medium / low")
    is_forecast: bool = Field(
        default=False, description="是否为机构预测值(如2026E/2027E/预测/预期)"
    )


class ChartVlmExtractionResult(BaseModel):
    """图表 VLM 逆向解析结构化实体。"""

    product: str = Field(..., description="化工品种标识，如 caustic_soda, pvc, methanol")
    metric: str = Field(..., description="提取的指标名称，如 effective_capacity, production")
    unit: str = Field(..., description="原始单位，如 万吨/年, 亿吨/年, 万吨, %")
    chart_title: str = Field(..., description="研报图表原标题")
    source_declared: str | None = Field(default=None, description="图表下方标注的数据来源")
    data_points: list[ExtractedDataPoint] = Field(default_factory=list, description="历年数据序列")
    notes: str | None = Field(default=None, description="补充说明或限制条件")
    raw_response: str | None = Field(default=None, description="模型原始回复文本")


VLM_CHART_SYSTEM_PROMPT = """你是一名严谨的化工大宗商品量化投研分析师。
你的任务是从提供的券商研报页面或图表截图中，精确逆向提取指定指标的历史时序数据（如柱状图、折线图中的历年数值）。

【提取原则与严厉约束】
1. 真实客观第一：只提取图表中清晰展示的数据点。
2. 严禁脑补与插值：未标注或模糊不清的年份绝对不要猜测或伪造。
3. 准确识别单位：仔细确认图表 Y 轴或标题中注明的单位（如“万吨”、“亿吨”、“万吨/年”、“%”）。
4. 区分产能与产量：若图表同时包含“产能（柱状）”和“产量（折线）”，必须严格提取用户指定的目标指标。
5. 数据来源溯源：提取图表底部或旁侧标注的“数据来源”（如“百川盈孚”、“隆众资讯”、“中国氯碱工业协会”等）。
6. 严格区分实际落地与机构预测：
   - 仔细观察横坐标年份是否带有“E”、“F”、“预测”、“规划”字样（如“2026E”、“2027E”）；
   - 若为预测值，将 "is_forecast": true，置信度标记为 medium；
   - 若为已发生的历史实际落地值（如 2016-2025），将 "is_forecast": false。

【输出格式】
必须严格输出纯 JSON 对象，格式如下（不要包含任何多余的前言或结语）：
{
  "product": "品种英文名",
  "metric": "指标名(如 effective_capacity)",
  "unit": "原始单位",
  "chart_title": "识别出的图表标题",
  "source_declared": "识别出的数据来源机构",
  "data_points": [
    {"year": 2024, "value": 2893.0, "confidence": "high", "is_forecast": false},
    {"year": 2026, "value": 3038.0, "confidence": "medium", "is_forecast": true}
  ],
  "notes": "必要的说明"
}
"""


class ChartVlmParser:
    """基于 LiteLLM + Tenacity 的研报图表多模态数据提取器。"""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        stream: bool | None = None,
    ) -> None:
        """初始化 VLM 提取器，优先读取入参，其次读取 settings 与系统环境变量。"""
        self.model = (
            model
            or settings.llm_model
            or os.getenv("LLM_MODEL")
            or os.getenv("GEMINI_MODEL")
            or "gemini/gemini-2.5-flash"
        )
        self.api_key = (
            api_key
            or settings.llm_api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        self.api_base = (
            api_base
            or settings.llm_api_base
            or os.getenv("LLM_API_BASE")
            or os.getenv("GOOGLE_GEMINI_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
        )
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.max_tokens = (
            max_tokens if max_tokens is not None else (settings.llm_max_tokens or 4096)
        )
        self.max_tokens = max(self.max_tokens, 4096)
        self.reasoning_effort = (
            reasoning_effort
            if reasoning_effort is not None
            else (settings.llm_reasoning_effort or os.getenv("LLM_REASONING_EFFORT") or "medium")
        )
        self.stream = stream if stream is not None else settings.llm_stream

    def render_pdf_page_to_base64(
        self,
        pdf_path: Path | str,
        page_number: int,
        dpi: int = 100,
        clip_rect: tuple[float, float, float, float] | None = None,
    ) -> tuple[str, str]:
        """将 PDF 指定页或局部区域渲染为高清 PNG 并转为 Base64 编码。

        Args:
            pdf_path: PDF 文件物理路径。
            page_number: 目标页码 (从 1 开始计数)。
            dpi: 渲染分辨率，默认 150 DPI。
            clip_rect: 可选裁剪区域 (x0, y0, x1, y1)。

        Returns:
            (base64_str, data_url) 元组。
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {path}")

        doc = cast("Any", pymupdf).open(str(path))
        if page_number < 1 or page_number > len(doc):
            raise IndexError(f"页码超出范围: {page_number} (总页数: {len(doc)})")

        page = doc[page_number - 1]
        rect = cast("Any", pymupdf).Rect(*clip_rect) if clip_rect else None
        pixmap = page.get_pixmap(dpi=dpi, clip=rect)
        img_bytes = cast("Any", pixmap).tobytes("png")
        b64_str = base64.b64encode(img_bytes).decode("utf-8")
        data_url = f"data:image/png;base64,{b64_str}"
        return b64_str, data_url

    def _execute_litellm_call(
        self,
        messages: list[dict[str, Any]],
        model_name: str,
    ) -> str:
        """调用 LiteLLM 统一接口并配合 Tenacity 指数退避重试。"""
        effective_model = (
            f"openai/{model_name}" if self.api_base and "/" not in model_name else model_name
        )
        kwargs: dict[str, Any] = {
            "model": effective_model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort

        logger.info(
            f"正在调用 VLM 模型: {effective_model} (base={self.api_base or 'default'}, stream={self.stream})"
        )
        for attempt in _VLM_RETRY:
            with attempt:
                if self.stream:
                    kwargs["stream"] = True
                    stream_resp = litellm.completion(**kwargs)
                    content_chunks: list[str] = []
                    reasoning_chunks: list[str] = []
                    for chunk in stream_resp:
                        if not getattr(chunk, "choices", None):
                            continue
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                            reasoning_chunks.append(delta.reasoning_content)
                        if getattr(delta, "content", None):
                            content_chunks.append(delta.content)
                    final_content = "".join(content_chunks)
                    if not final_content.strip() and reasoning_chunks:
                        final_content = "".join(reasoning_chunks)
                    return final_content

                resp = litellm.completion(**kwargs)
                choice = resp.choices[0]
                content = choice.message.content or ""
                if not content.strip() and hasattr(choice.message, "reasoning_content"):
                    content = getattr(choice.message, "reasoning_content", "") or ""
                return content
        return ""

    def extract_time_series_from_page(
        self,
        pdf_path: Path | str,
        page_number: int,
        product: str,
        target_metric: str = "effective_capacity",
        hint_text: str | None = None,
        clip_rect: tuple[float, float, float, float] | None = None,
        dpi: int = 150,
    ) -> ChartVlmExtractionResult:
        """从研报指定页码逆向抽取指定品种的目标指标连续时序。

        Args:
            pdf_path: 研报物理路径。
            page_number: 包含图表的研报页码 (1-indexed)。
            product: 目标品种标识 (如 pvc, caustic_soda, methanol 等)。
            target_metric: 目标指标 (默认 effective_capacity)。
            hint_text: 额外线索 (如“重点看图15中的有效产能柱状图”)。
            clip_rect: 可选的图表区域坐标。
            dpi: 图像渲染 DPI。

        Returns:
            ChartVlmExtractionResult 结构化提取结果实体。
        """
        _, data_url = self.render_pdf_page_to_base64(
            pdf_path=pdf_path,
            page_number=page_number,
            dpi=dpi,
            clip_rect=clip_rect,
        )

        user_prompt = (
            f"请从附带的研报图片中，逆向提取【{product}】的【{target_metric}】历年时序数据。\n"
        )
        if hint_text:
            user_prompt += f"提示线索: {hint_text}\n"
        user_prompt += "请严格以 JSON 格式输出，包含历年年份、数值、单位、图表标题和来源。"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": VLM_CHART_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            },
        ]

        raw_resp = self._execute_litellm_call(messages, self.model)
        parsed_result = self._parse_and_validate_response(
            raw_resp=raw_resp,
            default_product=product,
            default_metric=target_metric,
        )
        parsed_result.raw_response = raw_resp
        return parsed_result

    def _parse_and_validate_response(
        self,
        raw_resp: str,
        default_product: str,
        default_metric: str,
    ) -> ChartVlmExtractionResult:
        """解析并清洗 LLM 返回的 JSON 文本。"""
        cleaned = raw_resp.strip()
        # 去除 markdown 标记
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            cleaned = match.group(1).strip()

        try:
            data_dict = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error(f"VLM 返回的非有效 JSON 内容: {raw_resp[:300]}")
            raise ValueError(f"无法解析 VLM 输出为 JSON: {exc}") from exc

        # 确保关键默认字段存在
        if "product" not in data_dict:
            data_dict["product"] = default_product
        if "metric" not in data_dict:
            data_dict["metric"] = default_metric

        return ChartVlmExtractionResult(**data_dict)

    @staticmethod
    def save_to_annual_capacity_csv(
        result: ChartVlmExtractionResult,
        dest_csv_path: Path | str,
        report_meta: dict[str, Any] | None = None,
    ) -> Path:
        """将提取的时序结果转换为标准化的 *_annual_capacity.csv 黄金文件。

        CSV 格式对齐:
            year,effective_capacity_w_tons,data_source,notes
        """
        dest_path = Path(dest_csv_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # 单位换算系数（统一换算为“万吨”）
        unit_multiplier = 1.0
        unit_str = str(result.unit).lower()
        if "亿吨" in unit_str:
            unit_multiplier = 10000.0

        meta = report_meta or {}
        source_str = result.source_declared or meta.get("org_name") or "券商研报"
        report_title = meta.get("title", "")
        pub_date = meta.get("publishDate", "")
        info_code = meta.get("infoCode", "")

        lines = ["year,effective_capacity_w_tons,is_forecast,data_source,notes"]
        for pt in sorted(result.data_points, key=lambda x: x.year):
            val_in_w_tons = round(pt.value * unit_multiplier, 2)
            forecast_tag = "[机构预测]" if pt.is_forecast else "[实际落地]"
            notes_detail = (
                f"{forecast_tag} VLM抽取({result.chart_title}); 研报:《{report_title}》({pub_date}); "
                f"Code:{info_code}; 置信度:{pt.confidence}"
            )
            # 转义逗号
            safe_notes = notes_detail.replace(",", "，")
            lines.append(
                f"{pt.year},{val_in_w_tons},{str(pt.is_forecast).lower()},{source_str},{safe_notes}"
            )

        dest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info(f"已生成年度产能权威 CSV: {dest_path} (共 {len(result.data_points)} 年)")
        return dest_path
