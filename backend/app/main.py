
# Загрузка переменных окружения из .env
import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from api.chat import router as chat_router
from api.confirm import router as confirm_router
from core.config import settings
from core.logging_config import app_logger
from core.database import engine, Base
from core.config import settings
from core.vector_store import init_vector_store

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
app.include_router(confirm_router, prefix="/api/v1", tags=["confirm"])

@app.on_event("startup")
def startup_create_tables():
    try:
        if settings.create_tables_on_startup:
            app_logger.info("create_tables_on_startup is True — creating missing tables if any (skipping auth schema)")
            # Filter out auth tables to support split-db architecture
            tables_to_create = [
                table for table in Base.metadata.tables.values() 
                if table.schema != 'auth'
            ]
            Base.metadata.create_all(bind=engine, tables=tables_to_create)
            app_logger.info("Database tables ensured (create_all completed)")
            
        # Initialize Vector Store (Qdrant)
        app_logger.info("Initializing Vector Database...")
        try:
            init_vector_store()
            app_logger.info("Vector Database initialized.")
        except Exception as e:
            app_logger.warning(f"Vector Database initialization warning (non-critical): {e}")

    except Exception as e:
        app_logger.error(f"Error creating tables on startup: {e}")

@app.get("/")
async def root():
    app_logger.info("Root endpoint accessed")
    return {"message": "Chat API is running"}

@app.get("/health")
async def health_check():
    app_logger.info("Health check endpoint accessed")
    return {"status": "healthy"}