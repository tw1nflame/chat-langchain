from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    app_name: str = "Chat API"
    # Database for application data (chats, messages, history)
    database_url: str = "sqlite:///./chat.db"
    # Database for the Agent to query (business data)
    # If not set, could default to database_url or raise error. 
    # For now, let's allow it to be separate. 
    # If you want them to be the same, set this env var to the same value.
    agent_database_url: str = "sqlite:///./chat.db" 
    
    secret_key: str = "your-secret-key-here"
    cors_origins: str = "http://localhost:3000,http://localhost:3002,http://localhost:5173,http://localhost:4173"
    webhook_url: str = "http://localhost:5678/webhook/7be30e26-6434-46de-8a0f-22b42c1464d8"
    # Supabase (optional) - used to verify frontend user access tokens
    supabase_url: str | None = None
    # Optional: Supabase anon/public API key to allow server-side calls to auth endpoints
    supabase_anon_key: str | None = None
    # Optional table name overrides
    users_table: str = "users"
    chats_table: str = "chats"
    messages_table: str = "messages"
    files_table: str = "files"
    # Development helper: create tables automatically on startup if True
    create_tables_on_startup: bool = True
    
    # DeepSeek Configuration
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    class Config:
        # Resolve env file to the repository backend/.env regardless of cwd
        _here = os.path.dirname(__file__)
        # core/config.py is at backend/app/core/config.py -> go up two levels to backend
        env_file = os.path.abspath(os.path.join(_here, "..", "..", ".env"))

settings = Settings()
