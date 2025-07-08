from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

# Схемы для файлов
class FileData(BaseModel):
    name: str
    size: int
    type: Optional[str] = None
    download_url: Optional[str] = None  # URL для скачивания файла

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
class MessageResponse(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    files: Optional[List[FileData]] = []
    created_at: datetime
    
    class Config:
        from_attributes = True

# Схема для ответа с двумя сообщениями
class ChatExchangeResponse(BaseModel):
    user_message: MessageResponse
    assistant_message: MessageResponse
    
    class Config:
        from_attributes = True
