from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Any

# Схемы для файлов
class FileData(BaseModel):
    name: str
    size: int
    type: Optional[str] = None
    download_url: Optional[str] = None  # URL для скачивания файла
    owner_id: Optional[str] = None
    fileId: Optional[str] = None
    message_id: Optional[str] = None
    id: Optional[str] = None

# Схемы для таблиц
class TableData(BaseModel):
    headers: List[str]
    rows: List[List[Any]]
    title: Optional[str] = None
    download_url: Optional[str] = None  # URL для скачивания Excel


# Схемы для графиков
class ChartData(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    spec: Any # JSON spec


# Схемы для чатов
class ChatCreate(BaseModel):
    title: Optional[str] = None
    owner_id: Optional[str] = None

class ChatResponse(BaseModel):
    id: str
    title: str
    owner_id: Optional[str] = None
    last_message: Optional[str] = None
    last_message_role: Optional[str] = None
    first_message: Optional[str] = None
    first_message_role: Optional[str] = None
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
    tables: Optional[List[TableData]] = []
    charts: Optional[List[ChartData]] = []
    created_at: datetime
    owner_id: Optional[str] = None

    # Optional fields used for plan confirmation flow
    awaiting_confirmation: Optional[bool] = False
    confirmation_summary: Optional[str] = None
    # Plan identifier for pending confirmations (frontend should pass back this id when confirming)
    plan_id: Optional[str] = None
    
    class Config:
        from_attributes = True

# Схема для ответа с двумя сообщениями
class ChatExchangeResponse(BaseModel):
    user_message: MessageResponse
    assistant_message: MessageResponse
    
    class Config:
        from_attributes = True
