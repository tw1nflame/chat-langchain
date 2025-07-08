from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List
import uuid
import os
from datetime import datetime
from core.database import get_db
from models.chat import Chat, Message
from schemas.chat import ChatCreate, ChatResponse, MessageResponse, ChatExchangeResponse
from utils.chat_utils import (
    validate_message_input,
    ensure_chat_directory,
    process_uploaded_files,
    generate_assistant_response,
    get_storage_base_path
)
from core.logging_config import app_logger

router = APIRouter()

@router.get("/chats", response_model=List[ChatResponse])
async def get_chats(db: Session = Depends(get_db)):
    """Получить все чаты"""
    # Заглушка - вернем пустой список
    return []

@router.post("/chats", response_model=ChatResponse)
async def create_chat(chat: ChatCreate, db: Session = Depends(get_db)):
    """Создать новый чат"""
    # Заглушка - вернем тестовый чат
    return {
        "id": "test-chat-id",
        "title": chat.title or "Новый чат",
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00"
    }

@router.get("/chats/{chat_id}/messages", response_model=List[MessageResponse])
async def get_messages(chat_id: str, db: Session = Depends(get_db)):
    """Получить сообщения чата"""
    # Заглушка - вернем пустой список
    return []

@router.post("/chats/{chat_id}/messages", response_model=ChatExchangeResponse)
async def send_message_and_get_response(
    chat_id: str, 
    role: str = Form(...),
    content: str = Form(default=""),
    files: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db)
):
    """Отправить сообщение в чат и получить ответ ассистента"""
    
    app_logger.info(f"Received message in chat {chat_id}: role={role}, content_length={len(content)}, files_count={len(files)}")
    
    # Валидация входных данных
    validate_message_input(content, files)
    
    # Подготовка окружения
    chat_dir = ensure_chat_directory(chat_id)
    
    # Обработка сообщения пользователя
    user_processed_files = await process_uploaded_files(files, chat_dir, chat_id)
    user_message = MessageResponse(
        id=str(uuid.uuid4()),
        chat_id=chat_id,
        role=role,
        content=content,
        files=user_processed_files,
        created_at=datetime.now()
    )
    
    app_logger.info(f"User message processed: {user_message.id}")
    
    # Генерация ответа ассистента
    assistant_content, assistant_files = await generate_assistant_response(content, user_processed_files, chat_id)
    assistant_message = MessageResponse(
        id=str(uuid.uuid4()),
        chat_id=chat_id,
        role="assistant",
        content=assistant_content,
        files=assistant_files,  # Теперь включаем файлы от ассистента
        created_at=datetime.now()
    )
    
    app_logger.info(f"Assistant message generated: {assistant_message.id}")
    
    # Возвращаем оба сообщения
    return ChatExchangeResponse(
        user_message=user_message,
        assistant_message=assistant_message
    )

@router.get("/files/{chat_id}/{file_name}")
async def download_file(chat_id: str, file_name: str):
    """Скачать файл по ID чата и имени файла"""
    
    app_logger.info(f"File download request: chat_id={chat_id}, file_name={file_name}")
    
    # Получаем базовую папку storage
    storage_base = get_storage_base_path()
    
    # Путь к файлу в папке чата
    file_path = os.path.join(storage_base, chat_id, file_name)
    
    # Проверяем существование файла
    if not os.path.exists(file_path):
        app_logger.warning(f"File not found: {file_path}")
        raise HTTPException(status_code=404, detail="Файл не найден")
    
    # Проверяем, что путь безопасен (не выходит за пределы storage)
    try:
        real_path = os.path.realpath(file_path)
        real_storage = os.path.realpath(storage_base)
        if not real_path.startswith(real_storage):
            app_logger.warning(f"Access denied for path: {file_path}")
            raise HTTPException(status_code=403, detail="Доступ запрещен")
    except:
        app_logger.error(f"Invalid file path: {file_path}")
        raise HTTPException(status_code=403, detail="Недопустимый путь к файлу")
    
    app_logger.info(f"File download successful: {file_path}")
    return FileResponse(
        path=file_path,
        filename=file_name,
        media_type='application/octet-stream'
    )
