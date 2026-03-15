from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized application settings.

    All required environment variables are validated at startup with
    clear error messages so misconfiguration fails fast.
    """

    SUPABASE_URL: str
    SUPABASE_KEY: str
    GROQ_API_KEY: str

    # Optional Stripe configuration for paid subscriptions.
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_PRICE_MONTHLY: str | None = None
    STRIPE_PRICE_ANNUAL: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


def _format_validation_error(err: ValidationError) -> str:
    missing_keys: List[str] = []
    other_errors: List[str] = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e.get("loc", []))
        msg = e.get("msg", "")
        if "field required" in msg:
            missing_keys.append(loc)
        else:
            other_errors.append(f"{loc}: {msg}")

    parts: List[str] = []
    if missing_keys:
        parts.append(
            "Missing required environment variables: "
            + ", ".join(sorted(missing_keys))
        )
    if other_errors:
        parts.append("Additional configuration errors: " + "; ".join(other_errors))
    if not parts:
        parts.append(str(err))
    return "Configuration error. " + " ".join(parts)


@lru_cache
def get_settings() -> Settings:
    """
    Load and cache application settings.

    This is intended to be called from the FastAPI startup event so
    that configuration is validated exactly once on process start.
    """
    try:
        return Settings()
    except ValidationError as e:
        # Re-raise as RuntimeError with a concise, human-readable message
        message = _format_validation_error(e)
        raise RuntimeError(message) from e

