from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Vertex AI
    google_cloud_project: str
    google_cloud_location: str = "us-central1"
    google_application_credentials: str = ""

    gemini_flash_model: str = "gemini-2.5-flash-preview-04-17"
    gemini_pro_model: str = "gemini-2.5-pro-preview-03-25"

    # OpenAI (임베딩 전용)
    openai_api_key: str
    embedding_model: str = "text-embedding-3-small"

    # Gmail
    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str

    gmail_query: str = Field(
        default="is:unread (category:updates OR label:newsletters)",
        description="Gmail search query for ingestion",
    )
    gmail_fetch_limit: int = Field(
        default=20,
        ge=1,
        le=2000,
        description="Max number of Gmail messages to ingest per run (daily when scheduled once/day)",
    )

    # # Outlook
    # outlook_client_id: str
    # outlook_client_secret: str
    # outlook_tenant_id: str
    # outlook_refresh_token: str

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_webhook_url: str

    # DB
    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "newsletter-agent"

    # S3
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_bucket_name: str = "newsletter-images"

    # Schedule
    schedule_hour: int = 8
    schedule_timezone: str = "Asia/Seoul"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
