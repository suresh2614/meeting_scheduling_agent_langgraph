"""Configuration management for the LangGraph Meeting Scheduler"""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # OpenAI
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    
    # Google
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    service_account_file: str = os.getenv("SERVICE_ACCOUNT_FILE", "Backend/service_account_key.json")
    
    # Database
    database_url: str = os.getenv("DATABASE_URL", "postgresql://localhost/meeting_scheduler")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    # Email
    smtp_email: str = os.getenv("SMTP_EMAIL", "")
    smtp_app_password: str = os.getenv("SMTP_APP_PASSWORD", "")
    
    # Application
    environment: str = os.getenv("ENVIRONMENT", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    port: int = int(os.getenv("PORT", "8001"))
    
    # Security
    secret_key: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # Business Logic
    business_hours_start: int = 8
    business_hours_end: int = 17
    default_meeting_duration: int = 60
    max_attendees: int = 20
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()