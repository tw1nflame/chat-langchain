from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from api.chat import router as chat_router
from core.config import settings
from core.logging_config import app_logger

app = FastAPI(
    title="Chat API",
    description="Минимальный чат API на FastAPI",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем статические файлы
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Роуты
app.include_router(chat_router, prefix="/api/v1", tags=["chat"])

@app.get("/")
async def root():
    app_logger.info("Root endpoint accessed")
    return {"message": "Chat API is running"}

@app.get("/health")
async def health_check():
    app_logger.info("Health check endpoint accessed")
    return {"status": "healthy"}