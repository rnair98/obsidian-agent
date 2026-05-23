from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from app.core.paths import (
    DEFAULT_LOGS_DIR,
    DEFAULT_MEMORIES_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_VAULT_DIR,
)
from app.engine.agents.types import AgentName
from app.engine.backends.factory import FilesystemBackendType

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class GithubConfig(BaseModel):
    """GitHub auth config using app-installation (primary/only method)."""

    app_id: int = 0
    private_key: SecretStr = SecretStr("")
    installation_id: int = 0


class ReasoningConfig(BaseModel):
    """Reasoning controls passed through to the Responses API.

    Mirrors the ``reasoning={...}`` kwarg shape that ``langchain_openai``'s
    ``ChatOpenAI`` forwards to the OpenAI Responses API. Kept as a typed
    sub-model so YAML overrides are validated rather than silently
    accepted via ``extra="allow"``.
    """

    effort: Literal["low", "medium", "high", "xhigh"] | None = None
    summary: Literal["auto", "concise", "detailed"] | None = None
    model_config = ConfigDict(extra="forbid")


class LLMConfig(BaseModel):
    """LLM configuration. Only model is required; all other params pass through."""

    model: str
    use_responses_api: bool = True
    reasoning: ReasoningConfig | None = None
    verbosity: Literal["low", "medium", "high"] | None = None
    streaming: bool = False
    stream_usage: bool = False
    timeout: int | None = None
    temperature: float = 1.0
    model_kwargs: dict[str, JsonValue] = Field(default_factory=dict)
    api_key: str | None = None
    model_config = ConfigDict(extra="allow")


class AgentPromptConfig(BaseModel):
    """Per-agent runtime override for the system prompt.

    Empty string (or omission) falls through to the default defined on
    the corresponding ``AgentSpec`` in ``app/engine/agents/<name>.py``.
    """

    system_prompt: str = ""


class AgentsConfig(BaseModel):
    researcher: AgentPromptConfig
    summarizer: AgentPromptConfig
    zettelkasten: AgentPromptConfig

    def prompt_for(self, name: AgentName) -> AgentPromptConfig:
        match name:
            case "researcher":
                return self.researcher
            case "summarizer":
                return self.summarizer
            case "zettelkasten":
                return self.zettelkasten
            case _:
                raise ValueError(f"unknown agent name: {name}")


class FilesystemConfig(BaseModel):
    """Filesystem backend configuration for local artifact persistence.

    ``base_path`` sandboxes every relative path written through the backend.
    It defaults to the current working directory so that the documented
    artifact dirs (``.memories``, ``.vault``, ``outputs``) land at repo root
    rather than nested under ``.assets``. GitHub snapshots opt into the
    ``.assets`` sandbox explicitly via ``GitHubRepositoryService``.
    """

    backend_type: FilesystemBackendType = FilesystemBackendType.IN_PROCESS
    base_path: Path = Path(".")


class Settings(BaseSettings):
    github: GithubConfig | None = None
    filesystem: FilesystemConfig = FilesystemConfig()

    # Paths
    MEMORIES_DIR: Path = DEFAULT_MEMORIES_DIR
    VAULT_DIR: Path = DEFAULT_VAULT_DIR
    OUTPUT_DIR: Path = DEFAULT_OUTPUT_DIR
    LOGS_DIR: Path = DEFAULT_LOGS_DIR

    # Logging
    LOG_LEVEL: str = "INFO"

    # Telemetry
    PHOENIX_ENABLED: bool = True

    # Checkpointer (LangGraph AsyncPostgresSaver connection string)
    DATABASE_URL: str = ""

    # API Keys
    JINA_API_KEY: str = ""

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
