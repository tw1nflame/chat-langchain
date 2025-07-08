from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    app_name: str = "Chat API"
    database_url: str = "sqlite:///./chat.db"
    secret_key: str = "your-secret-key-here"
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://localhost:4173"
    webhook_url: str = "http://localhost:5678/webhook/7be30e26-6434-46de-8a0f-22b42c1464d8"
    
    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    class Config:
        env_file = ".env"

settings = Settings()
