"""数据管道专用的环境变量、密钥与路径配置。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from stock_data.core.runtime import DataRuntimeContext


def _project_root() -> Path:
    """定位当前 Python 包所属的项目根目录。"""
    module_root = Path(__file__).resolve().parents[3]
    current = Path.cwd().resolve()
    for candidate in (current, module_root):
        for parent in (candidate, *candidate.parents):
            if (parent / "pyproject.toml").exists() and (parent / "src").is_dir():
                return parent
    return module_root


def _main_worktree_root(project_root: Path) -> Path:
    """从 Git worktree 元数据定位主工作区；普通仓库直接返回自身。"""
    git_entry = project_root / ".git"
    if git_entry.is_dir():
        return project_root
    if not git_entry.is_file():
        return project_root

    try:
        git_dir_text = git_entry.read_text(encoding="utf-8").strip()
        if not git_dir_text.startswith("gitdir:"):
            return project_root
        git_dir = Path(git_dir_text.removeprefix("gitdir:").strip())
        if not git_dir.is_absolute():
            git_dir = (project_root / git_dir).resolve()
        common_dir_file = git_dir / "commondir"
        if common_dir_file.exists():
            common_dir = Path(common_dir_file.read_text(encoding="utf-8").strip())
            if not common_dir.is_absolute():
                common_dir = (git_dir / common_dir).resolve()
        else:
            common_dir = git_dir.parent.parent
        return common_dir.resolve().parent
    except (OSError, ValueError):
        return project_root


def _has_curated_data(data_root: Path) -> bool:
    """判断数据根目录是否包含实际 Curated Parquet，而非占位目录。"""
    curated_root = data_root / "curated"
    if not curated_root.is_dir():
        return False
    try:
        return next(curated_root.rglob("*.parquet"), None) is not None
    except OSError:
        return False


@lru_cache(maxsize=1)
def _resolve_default_data_root() -> Path:
    """优先使用当前项目已有数据，否则在 worktree 中回退到主空间数据。"""
    project_root = _project_root()
    local_root = project_root / "data"
    if _has_curated_data(local_root):
        return local_root

    main_root = _main_worktree_root(project_root) / "data"
    if main_root != local_root and _has_curated_data(main_root):
        return main_root
    return local_root


def _read_env_no_proxy() -> list[str]:
    """从 .env 文件显式读取 NO_PROXY 配置列表。"""
    env_file = Path(".env")
    if not env_file.exists():
        return []
    try:
        items: list[str] = []
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NO_PROXY=") or line.startswith("no_proxy="):
                val = line.split("=", 1)[1].strip().strip("\"'")
                items.extend([x.strip() for x in val.split(",") if x.strip()])
        return items
    except OSError:
        return []


class DataSettings(BaseSettings):
    """数据管道专用的环境变量与密钥配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 存储与目录配置
    data_root: Path | None = None
    raw_root: Path | None = None
    curated_root: Path | None = None
    cache_root: Path | None = None
    data_dir: Path = Path("./data")
    raw_data_dir: Path = Path("./data/raw")
    curated_data_dir: Path = Path("./data/curated")
    cache_dir: Path = Path("./data/cache")

    # TuShare 密钥与配置
    tushare_token: str = ""
    tushare_url: str = "http://api.tushare.pro"

    # 理杏仁密钥与配置
    lixinger_token: str = ""
    lixinger_url: str = "https://open.lixinger.com"
    lxr_token: str = ""
    lxr_url: str = ""

    # FRED 密钥
    fred_api_key: str = ""

    # Alpha Vantage 密钥与配置
    alpha_vantage_api_key: str = ""
    alpha_vantage_url: str = "https://www.alphavantage.co/query"
    alpha_vantage_proxy: str = ""

    # 代理配置
    akshare_proxy: str = ""
    yfinance_proxy: str = ""
    yfinance_proxy_pool_file: Path = Path("data/proxy")
    no_proxy: str = ""

    # 默认数据源模式
    data_source_mode: Literal["tushare", "yfinance", "lixinger", "fred", "alphavantage"] = "tushare"
    endpoint_update_time_overrides: dict[str, str] = {}

    @model_validator(mode="after")
    def resolve_storage_paths(self) -> DataSettings:
        """将新旧目录配置收敛为同一组运行时路径，并同步代理排除白名单。"""
        current_no_proxy = os.environ.get("NO_PROXY", "") or os.environ.get("no_proxy", "")
        parts = [p.strip() for p in current_no_proxy.split(",") if p.strip()]
        for p in _read_env_no_proxy():
            if p not in parts:
                parts.append(p)
        if self.no_proxy:
            for p in self.no_proxy.split(","):
                p_s = p.strip()
                if p_s and p_s not in parts:
                    parts.append(p_s)
        if parts:
            merged = ",".join(parts)
            os.environ["NO_PROXY"] = merged
            os.environ["no_proxy"] = merged

        fields_set = self.model_fields_set
        if self.data_root is not None:
            root = self.data_root
        elif "data_dir" in fields_set:
            root = self.data_dir
        else:
            root = _resolve_default_data_root()

        raw_root = self.raw_root
        if raw_root is None:
            raw_root = self.raw_data_dir if "raw_data_dir" in fields_set else root / "raw"
        curated_root = self.curated_root
        if curated_root is None:
            curated_root = (
                self.curated_data_dir if "curated_data_dir" in fields_set else root / "curated"
            )
        cache_root = self.cache_root
        if cache_root is None:
            cache_root = self.cache_dir if "cache_dir" in fields_set else root / "cache"

        self.data_root = root
        self.raw_root = raw_root
        self.curated_root = curated_root
        self.cache_root = cache_root
        self.data_dir = root
        self.raw_data_dir = raw_root
        self.curated_data_dir = curated_root
        self.cache_dir = cache_root
        return self

    @property
    def runtime_context(self) -> DataRuntimeContext:
        """返回本次配置对应的统一目录上下文。"""
        from stock_data.core.runtime import DataRuntimeContext

        return DataRuntimeContext.from_settings(self)

    @property
    def effective_lixinger_token(self) -> str:
        """获取有效的理杏仁 Token（兼容 LIXINGER_TOKEN 与 LXR_TOKEN）。"""
        return self.lixinger_token or self.lxr_token

    @property
    def effective_lixinger_url(self) -> str:
        """获取有效的理杏仁 API 服务器地址。"""
        return self.lixinger_url or self.lxr_url or "https://open.lixinger.com"

    def setup_directories(self) -> None:
        """确保数据与缓存目录存在"""
        self.runtime_context.ensure_directories()


data_settings = DataSettings()
