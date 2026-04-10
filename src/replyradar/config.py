from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

_YAML_PATH = Path("config/default.yaml")


class _YamlSource(PydanticBaseSettingsSource):
    def __init__(self, settings_cls: type[BaseSettings], yaml_path: Path = _YAML_PATH) -> None:
        super().__init__(settings_cls)
        self._data: dict[str, Any] = {}
        if yaml_path.exists():
            with yaml_path.open(encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        val = self._data.get(field_name)
        return val, field_name, self.field_is_complex(field)

    def prepare_field_value(
        self, field_name: str, field: Any, value: Any, value_is_complex: bool
    ) -> Any:
        return value

    def __call__(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for field_name, field_info in self.settings_cls.model_fields.items():
            val, key, _ = self.get_field_value(field_info, field_name)
            if val is not None:
                d[key] = val
        return d


class ActivationConfig(BaseModel):
    min_mentions: int = 3
    min_chats: int = 2


class ConfidenceConfig(BaseModel):
    display_threshold: float = 0.75
    hedged_threshold: float = 0.40
    source_weights: dict[str, float] = {"self": 1.0, "other": 0.7, "inferred": 0.5}
    half_life_days: int = 365
    max_corroboration_boost: float = 0.40
    corroboration_step: float = 0.10
    contradiction_penalty_factor: float = 0.5


class EntityResolutionConfig(BaseModel):
    similarity_threshold: float = 0.85


class ProcessingConfig(BaseModel):
    backfill_batch_size: int = 20
    entity_extract_batch_size: int = 15
    max_retries_before_quarantine: int = 3
    backfill_concurrency: int = 1
    context_window_size: int = 5  # кол-во предыдущих сообщений чата для контекста (0 = отключено)


class LLMConfig(BaseModel):
    base_url: str = "http://host.docker.internal:1234/v1"
    model: str = "local-model"
    api_key: str = "lm-studio"


class EmbeddingConfig(BaseModel):
    provider: str = "lmstudio"
    model: str = "text-embedding-nomic-embed-text-v1.5"
    base_url: str = "http://host.docker.internal:1234/v1"


class DatabaseConfig(BaseModel):
    url: str = "postgresql://postgres:postgres@localhost:5432/replyradar"


class TelegramConfig(BaseModel):
    api_id: int = 0
    api_hash: str = ""
    session_name: str = "replyradar"
    session_dir: str = "."  # путь относительно CWD


class ImportConfig(BaseModel):
    max_file_size_mb: int = 200  # максимальный размер result.json для /import/telegram-export


class LogConfig(BaseModel):
    level: str = "INFO"       # DEBUG | INFO | WARNING | ERROR
    format: str = "text"      # text | json  (json — для Docker/продакшн)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    activation: ActivationConfig = ActivationConfig()
    confidence: ConfidenceConfig = ConfidenceConfig()
    entity_resolution: EntityResolutionConfig = EntityResolutionConfig()
    processing: ProcessingConfig = ProcessingConfig()
    llm: LLMConfig = LLMConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    database: DatabaseConfig = DatabaseConfig()
    telegram: TelegramConfig = TelegramConfig()
    tg_import: ImportConfig = ImportConfig()
    log: LogConfig = LogConfig()

    @classmethod
    def settings_customise_sources(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Приоритет: init > env vars > .env file > config/default.yaml
        return (init_settings, env_settings, dotenv_settings, _YamlSource(settings_cls))


@lru_cache
def get_settings() -> Settings:
    return Settings()
