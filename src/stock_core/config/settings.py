"""全局应用与运行时环境配置。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局应用基础配置类，从环境变量或 .env 文件读取配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "StockFinanceApp"
    environment: str = "development"
    log_level: str = "INFO"
    log_retention_days: int = 14
    log_rotation_size: str = "10 MB"
    data_dir: Path = Path("./data")

    # 大语言模型与多模态视觉模型 (LLM / VLM) 统一配置 (基于 litellm)
    llm_model: str = "gemini/gemini-2.5-flash"
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096
    llm_reasoning_effort: str | None = "medium"  # low, medium, high
    llm_stream: bool = True  # 开启流式防超时


settings = Settings()
