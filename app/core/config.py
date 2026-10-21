"""Core application configuration and settings."""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    APP_NAME: str = "AI Receptionist Medical Clinic MVP"
    APP_ENV: str = "development"
    PORT: int = 8000
    HOST: str = "127.0.0.1"
    LOG_LEVEL: str = "INFO"

    # Retell AI & Webhook Authentication
    # If set, incoming webhook calls to /api/retell/* must include matching X-Api-Key or Authorization header
    RETELL_API_KEY: str = "key_0f293e950a9456f5d995f640ac81"
    WEBHOOK_SECRET_KEY: str = "demo-clinic-secret-key-12345"

    # Clinic Demo Profile
    CLINIC_NAME: str = "Md Primary Care INC"
    CLINIC_PHONE: str = "(561) 208-6041"
    CLINIC_HOURS: str = "Monday to Friday, 8:00 AM to 5:00 PM EST"

    # Global Medical Prototype Disclaimer
    DISCLAIMER: str = (
        "DEMO PROTOTYPE ONLY: This application uses synthetic demo data and is NOT "
        "connected to live electronic health records (EHR), national pharmacy networks, or 911 emergency services. "
        "No real appointments are booked, no prescriptions are dispensed, and identity is unverified."
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
