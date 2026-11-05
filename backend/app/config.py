"""Runtime configuration, sourced from environment variables.

Railway injects PORT; everything else is optional so the app boots with
zero configuration and simply reports engines as unavailable.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- server -------------------------------------------------------
    port: int = Field(default=8000, alias="PORT")
    host: str = "0.0.0.0"
    log_level: str = "info"

    # --- storage ------------------------------------------------------
    data_dir: Path = Field(default=Path("/data"), alias="DATA_DIR")
    max_upload_mb: int = Field(default=50, alias="MAX_UPLOAD_MB")
    retention_hours: int = Field(default=72, alias="RETENTION_HOURS")

    # --- processing ---------------------------------------------------
    raster_dpi: int = Field(default=300, alias="RASTER_DPI")
    max_pages: int = Field(default=25, alias="MAX_PAGES")
    max_concurrent_engines: int = Field(default=4, alias="MAX_CONCURRENT_ENGINES")
    default_timeout_s: int = Field(default=180, alias="DEFAULT_TIMEOUT_S")
    install_heavy: bool = Field(default=False, alias="INSTALL_HEAVY")

    # --- cloud engine credentials (all optional) ----------------------
    ocrspace_key: str | None = Field(default=None, alias="OCRSPACE_KEY")
    google_vision_key: str | None = Field(default=None, alias="GOOGLE_VISION_KEY")
    azure_docintel_endpoint: str | None = Field(default=None, alias="AZURE_DOCINTEL_ENDPOINT")
    azure_docintel_key: str | None = Field(default=None, alias="AZURE_DOCINTEL_KEY")
    gemini_key: str | None = Field(default=None, alias="GEMINI_KEY")
    openrouter_key: str | None = Field(default=None, alias="OPENROUTER_KEY")
    mistral_key: str | None = Field(default=None, alias="MISTRAL_KEY")
    llamaparse_key: str | None = Field(default=None, alias="LLAMAPARSE_KEY")
    aws_access_key_id: str | None = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str | None = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    mathpix_app_id: str | None = Field(default=None, alias="MATHPIX_APP_ID")
    mathpix_app_key: str | None = Field(default=None, alias="MATHPIX_APP_KEY")
    datalab_key: str | None = Field(default=None, alias="DATALAB_KEY")
    deepinfra_key: str | None = Field(default=None, alias="DEEPINFRA_KEY")
    openai_key: str | None = Field(default=None, alias="OPENAI_KEY")
    anthropic_key: str | None = Field(default=None, alias="ANTHROPIC_KEY")
    google_docai_project: str | None = Field(default=None, alias="GOOGLE_DOCAI_PROJECT")
    nanonets_key: str | None = Field(default=None, alias="NANONETS_KEY")
    mindee_key: str | None = Field(default=None, alias="MINDEE_KEY")
    reducto_key: str | None = Field(default=None, alias="REDUCTO_KEY")

    # --- derived paths ------------------------------------------------
    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "masterocr.db"

    @property
    def frontend_dist(self) -> Path:
        return Path(__file__).resolve().parents[2] / "frontend" / "dist"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.uploads_dir, self.work_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
