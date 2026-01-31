"""
Утилиты для работы с файлами в чат-системе
"""
from fastapi import HTTPException, UploadFile
from typing import List, Optional, Dict, Any
import os
import asyncio
from core.logging_config import app_logger, webhook_logger, error_logger
from core.config import settings
from core.agent_graph import run_agent


def validate_message_input(content: str, files: List[UploadFile]) -> None:
    """Проверяет, что сообщение содержит либо текст, либо файлы"""
    if not content.strip() and (not files or len(files) == 0):
        raise HTTPException(status_code=400, detail="Сообщение должно содержать текст или файлы")


def ensure_chat_directory(chat_id: str) -> str:
    """Создает папку для чата и возвращает путь к ней"""
    # Поднимаемся от app/utils/ до backend/
    storage_base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage")
    chat_dir = os.path.join(storage_base, chat_id)
    os.makedirs(chat_dir, exist_ok=True)
    return chat_dir



async def process_uploaded_files(files: List[UploadFile], chat_dir: str, chat_id: str):
    """
    Сохраняет загруженные файлы в директорию чата.
    """
    api_files = []
    
    # Создаем директорию если её нет
    os.makedirs(chat_dir, exist_ok=True)
    
    for file in files:
        file_path = os.path.join(chat_dir, file.filename)
        try:
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
                
            api_files.append({
                "name": file.filename,
                "path": file_path,
                "type": file.content_type,
                "size": len(content)
            })
        except Exception as e:
            app_logger.error(f"Failed to specific save file {file.filename}: {e}")
            
    return api_files, []


async def generate_assistant_response(user_message: str, user_files: List[Dict[str, Any]], chat_id: str, owner_id: str, auth_token: str = None, history: List[str] = None) -> tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Generates a response using the LangGraph agent connected to DeepSeek and the Database.
    Returns: content, files, tables, charts
    """
    app_logger.info(f"Generating response for message: {user_message}")
    
    # If using DeepSeek agent
    if settings.deepseek_api_key:
        app_logger.info("DeepSeek API key configured. Delegating to agent_graph...")
        try:
            # Run the agent
            agent_result = await asyncio.to_thread(run_agent, user_message, owner_id, auth_token, user_files, chat_id, history)
            
            # Identify result structure
            if isinstance(agent_result, dict):
                response_text = agent_result.get("content", "")
                tables = agent_result.get("tables", [])
                charts = agent_result.get("charts", [])
                awaiting_confirmation = agent_result.get("awaiting_confirmation", False)
                confirmation_summary = agent_result.get("confirmation_summary")
                plan_id = agent_result.get("plan_id")
            else:
                # Fallback for old str return
                response_text = str(agent_result)
                tables = []
                charts = []
                awaiting_confirmation = False
                confirmation_summary = None
                plan_id = None

            # If confirmation is pending, prefer to show the generated confirmation summary to the user
            if awaiting_confirmation and confirmation_summary:
                response_text = confirmation_summary

            app_logger.info("Agent response received", extra={"len": len(response_text), "awaiting_confirmation": awaiting_confirmation, "plan_id": plan_id})
            return response_text, [], tables, charts, awaiting_confirmation, confirmation_summary, plan_id
        except Exception as e:
            app_logger.error(f"Error generating response with agent: {e}", exc_info=True)
            return f"Error: {e}", [], [], [], False, None, None
    else:
        app_logger.warning("DeepSeek API Key NOT configured. Using echo stub.")
        return f"DeepSeek API Key not configured. Echo: {user_message}", [], [], [], False, None, None


def get_storage_base_path() -> str:
    """Возвращает базовый путь к папке storage"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage")

