from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from core.database import get_db
from models.chat import Chat, Message
from schemas.chat import ChatCreate, ChatResponse, MessageCreate, MessageResponse

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

@router.post("/chats/{chat_id}/messages", response_model=MessageResponse)
async def send_message(chat_id: str, message: MessageCreate, db: Session = Depends(get_db)):
    """Отправить сообщение в чат"""
    # Заглушка - вернем тестовое сообщение
    return {
        "id": "test-message-id",
        "chat_id": chat_id,
        "role": message.role,
        "content": message.content,
        "created_at": "2025-01-01T00:00:00"
    }
