"""Configuration management for Superclaims AI Processor."""
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # API Keys
    google_api_key: str = ""
    openai_api_key: str = ""
    
    # Application
    app_name: str = "Superclaims AI Processor"
    app_version: str = "1.0.0"
    debug: bool = True
    log_level: str = "INFO"
    
    # LLM Configuration
    default_llm_provider: Literal["google", "openai"] = "google"
    gemini_model: str = "gemini-2.0-flash-lite"  # 4000 RPM, faster and cheaper
    openai_model: str = "gpt-4-turbo-preview"
    llm_temperature: float = 0.1
    llm_max_retries: int = 3
    llm_timeout: int = 60
    
    # File Upload
    max_file_size: int = 10485760  # 10MB
    max_files_per_request: int = 10
    allowed_extensions: str = "pdf"
    
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_enabled: bool = False
    cache_ttl: int = 3600
    
    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "superclaims"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_enabled: bool = False
    
    # Vector Store
    chromadb_path: str = "./data/chroma"
    vector_store_enabled: bool = False
    
    # Rate Limiting
    rate_limit_enabled: bool = False
    rate_limit_requests: int = 100
    rate_limit_period: int = 3600
    
    # Monitoring
    enable_metrics: bool = True
    correlation_id_header: str = "X-Correlation-ID"
    
    @property
    def postgres_url(self) -> str:
        """Construct PostgreSQL connection URL."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    @property
    def redis_url(self) -> str:
        """Construct Redis connection URL."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
