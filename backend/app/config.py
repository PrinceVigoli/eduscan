from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "EduScan API"
    database_url: str = "sqlite:///./eduscan.db"
    allowed_origins: str = "http://localhost:8080,http://localhost:5173"
    session_days: int = 7
    secure_cookies: bool = False
    offline_signing_key: str = "development-only-change-before-deployment"
    offline_private_key_der: str | None = None
    upload_dir: str = "uploads"
    auto_create_schema: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_prefix="EDUSCAN_")

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]


settings = Settings()
