from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,
    )

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_base_url: str = "http://127.0.0.1:8000"
    debug: bool = False

    qbo_webhook_verifier_token: str = ""
    qbo_allowed_realm_ids: list[str] = Field(default_factory=list)
    qbo_allowed_events: list[str] = Field(default_factory=lambda: ["estimate.created", "invoice.created"])
    customer_match_terms: list[str] = Field(default_factory=lambda: ["COSTCO"])
    customer_exclude_terms: list[str] = Field(default_factory=lambda: ["COSTCO_WEB", "COSTCO WEB"])

    quickbooks_client_id: str = ""
    quickbooks_client_secret: str = ""
    quickbooks_environment: str = "production"
    quickbooks_realm_id: str = ""
    quickbooks_refresh_token: str = ""
    quickbooks_token_broker_url: str = ""
    quickbooks_token_broker_secret: str = ""

    slack_webhook_url: str = ""

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_messaging_service_sid: str = ""
    twilio_to_numbers: list[str] = Field(default_factory=list)

    @field_validator(
        "qbo_allowed_realm_ids",
        "qbo_allowed_events",
        "customer_match_terms",
        "customer_exclude_terms",
        "twilio_to_numbers",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def state_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / "state"

    @property
    def db_path(self) -> Path:
        return self.state_root / "relay.sqlite3"

    @property
    def quickbooks_api_base_url(self) -> str:
        if self.quickbooks_environment.strip().lower() == "sandbox":
            return "https://sandbox-quickbooks.api.intuit.com"
        return "https://quickbooks.api.intuit.com"

    def ensure_directories(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
