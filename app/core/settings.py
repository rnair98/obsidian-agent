from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from app.core.paths import (
    DEFAULT_ASSETS_DIR,
    DEFAULT_LOGS_DIR,
    DEFAULT_MEMORIES_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_VAULT_DIR,
)
from app.engine.backends.factory import FilesystemBackendType


class GithubConfig(BaseModel):
    """GitHub auth config using app-installation (primary/only method)."""

    app_id: int = 0
    private_key: SecretStr = SecretStr("")
    installation_id: int = 0


class LLMConfig(BaseModel):
    """LLM configuration. Only model is required; all other params pass through."""

    model: str
    use_responses_api: bool = True
    reasoning_effort: Optional[Literal["low", "medium", "high", "xhigh"]] = None
    verbosity: Optional[Literal["low", "medium", "high"]] = None
    streaming: bool = False
    stream_usage: bool = False
    timeout: Optional[int] = None
    temperature: float = 1.0
    model_kwargs: dict = Field(default_factory=dict)
    api_key: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class AgentPromptConfig(BaseModel):
    system_prompt: str


class AgentsConfig(BaseModel):
    researcher: AgentPromptConfig
    summarizer: AgentPromptConfig
    zettelkasten: AgentPromptConfig


class WorkflowConfig(BaseModel):
    """Workflow execution configuration resolved from settings sources."""

    search_limit: int = 15
    exa_search_type: str = "auto"
    fetch_code_context: bool = False


class FilesystemConfig(BaseModel):
    """Filesystem backend configuration for local artifact persistence."""

    backend_type: FilesystemBackendType = FilesystemBackendType.IN_PROCESS
    base_path: Path = DEFAULT_ASSETS_DIR


class Settings(BaseSettings):
    github: GithubConfig | None = None
    workflow: WorkflowConfig = WorkflowConfig()
    filesystem: FilesystemConfig = FilesystemConfig()

    # Paths
    MEMORIES_DIR: Path = DEFAULT_MEMORIES_DIR
    VAULT_DIR: Path = DEFAULT_VAULT_DIR
    OUTPUT_DIR: Path = DEFAULT_OUTPUT_DIR
    LOGS_DIR: Path = DEFAULT_LOGS_DIR

    # Logging
    LOG_LEVEL: str = "INFO"

    # API Keys
    BRAVE_SEARCH_API_KEY: str = ""
    EXA_API_KEY: str = ""
    JINA_API_KEY: str = ""

    # Search Config
    BRAVE_SEARCH_URL: str = "https://api.search.brave.com/res/v1/web/search"
    EXA_SEARCH_URL: str = "https://api.exa.ai/search"
    EXA_CONTEXT_URL: str = "https://api.exa.ai/context"
    DEFAULT_SEARCH_LIMIT: int = 10

    # LLM & Agent Config
    llm: LLMConfig | None = None
    agents: AgentsConfig | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        yaml_file=Path(__file__).parent / "resources" / "agent_config.yaml",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


settings = Settings()
