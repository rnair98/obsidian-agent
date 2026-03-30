from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class GithubConfig(BaseModel):
    """GitHub auth config using app-installation (primary/only method)."""

    app_id: int = 0
    private_key: SecretStr = SecretStr("")
    installation_id: int = 0


class LLMConfig(BaseModel):
    """LLM configuration. Only model is required; all other params pass through."""

    model: str
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


class Settings(BaseSettings):
    github: GithubConfig | None = None
    workflow: WorkflowConfig = WorkflowConfig()

    # Paths
    MEMORIES_DIR: Path = Path(".memories")
    VAULT_DIR: Path = Path(".vault")
    OUTPUT_DIR: Path = Path("outputs")
    LOGS_DIR: Path = Path(".logs")

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
        yaml_file=Path(__file__).parent.parent / "resources" / "agent_config.yaml",
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
