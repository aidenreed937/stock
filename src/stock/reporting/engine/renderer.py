"""Markdown 报告渲染引擎 (Report Renderer)。

基于 Jinja2 构建，封装了针对 Markdown 语法的空白符修剪规则、专用 Filter 注册与单例环境管理。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from stock.reporting.engine.filters import register_filters


class ReportRenderer:
    """Markdown 报告渲染引擎。"""

    _instance: ReportRenderer | None = None

    def __init__(self, template_dir: Path | None = None) -> None:
        """初始化 ReportRenderer，配置 Jinja2 模板环境。

        Args:
            template_dir: 模板文件所在目录，默认为 stock/reporting/templates
        """
        if template_dir is None:
            # 默认为 stock/reporting/templates 目录
            template_dir = Path(__file__).resolve().parent.parent / "templates"

        self._template_dir = template_dir
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            trim_blocks=True,  # 移除块标签后的首个换行符
            lstrip_blocks=True,  # 移除块标签所在行的前导空格/Tab
            keep_trailing_newline=True,  # 保持模板末尾的换行
            autoescape=select_autoescape([]),  # 禁用 HTML 转义，保留 Markdown 原始符号
        )
        register_filters(self._env)

    @property
    def env(self) -> Environment:
        """获取底层的 Jinja2 Environment 实例。"""
        return self._env

    @classmethod
    def get_instance(cls) -> ReportRenderer:
        """获取或创建默认的全局 ReportRenderer 单例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置全局单例（主要用于单元测试）。"""
        cls._instance = None

    def render(
        self,
        template_name: str,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """加载指定模板并渲染为 Markdown 文本。

        Args:
            template_name: 相对 template_dir 的模板路径 (如 "scan/investor.md.j2")
            context: 渲染上下文变量字典
            **kwargs: 附加关键字参数，将合并入 context

        Returns:
            渲染生成的 Markdown 字符串
        """
        merged_context = dict(context or {})
        merged_context.update(kwargs)
        template = self._env.get_template(template_name)
        return str(template.render(**merged_context))

    def render_string(
        self,
        source: str,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """直接渲染内存中的 Markdown 模板字符串。"""
        merged_context = dict(context or {})
        merged_context.update(kwargs)
        template = self._env.from_string(source)
        return str(template.render(**merged_context))
