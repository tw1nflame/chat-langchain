from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "Chat API"
    database_url: str = "sqlite:///./chat.db"
    secret_key: str = "your-secret-key-here"
    
    class Config:
        env_file = ".env"

settings = Settings()
