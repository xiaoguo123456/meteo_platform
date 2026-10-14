from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "全球天气态势浏览器 API"
    data_dir: Path = Path("../data")
    cors_origins: str = "http://localhost:5173"
    # 站点预测统一走本机自部署 Open-Meteo，不直接让浏览器访问上游。
    open_meteo_base_url: str = "http://127.0.0.1:8090/v1/forecast"

    model_config = SettingsConfigDict(env_prefix="METEO_", env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
