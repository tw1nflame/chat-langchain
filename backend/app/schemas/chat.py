from pydantic import BaseModel
from datetime import datetime
from typing import Optional

# Схемы для чатов
class ChatCreate(BaseModel):
    title: Optional[str] = None

class ChatResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# Схемы для сообщений
class MessageCreate(BaseModel):
    role: str  # 'user' или 'assistant'
    content: str

class MessageResponse(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    created_at: datetime
    
    class Config:
        from_attributes = True
