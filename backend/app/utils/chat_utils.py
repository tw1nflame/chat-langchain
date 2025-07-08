"""
Утилиты для работы с файлами в чат-системе
"""
from fastapi import HTTPException, UploadFile
from typing import List, Optional, Dict, Any
import uuid
import os
import asyncio
import aiofiles
import httpx
import base64
from core.logging_config import app_logger, webhook_logger, error_logger
from core.config import settings


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


async def save_single_file(file: UploadFile, chat_dir: str, chat_id: str) -> Optional[Dict[str, Any]]:
    """Асинхронно сохраняет один файл и возвращает информацию о нем"""
    if not file.filename or file.size <= 0:
        return None
    
    # Сохраняем файл с оригинальным именем
    file_path = os.path.join(chat_dir, file.filename)
    
    # Читаем содержимое файла
    content_bytes = await file.read()
    
    # Асинхронно сохраняем файл
    async with aiofiles.open(file_path, "wb") as buffer:
        await buffer.write(content_bytes)
    
    # Возвращаем информацию о файле
    return {
        "name": file.filename,
        "size": len(content_bytes),
        "type": file.content_type,
        "chat_id": chat_id,  # Добавляем chat_id для работы с webhook
        "download_url": f"/api/v1/files/{chat_id}/{file.filename}"
    }


async def process_uploaded_files(files: List[UploadFile], chat_dir: str, chat_id: str) -> List[Dict[str, Any]]:
    """Асинхронно обрабатывает загруженные файлы и возвращает информацию о них"""
    if not files or len(files) == 0:
        return []
    
    # Сохраняем файлы параллельно
    tasks = [save_single_file(file, chat_dir, chat_id) for file in files]
    results = await asyncio.gather(*tasks)
    
    # Фильтруем успешно обработанные файлы
    processed_files = [result for result in results if result is not None]
    
    return processed_files


async def copy_single_demo_file(source_path: str, dest_path: str, file_name: str, file_type: str, chat_id: str) -> Optional[Dict[str, Any]]:
    """Асинхронно копирует один демо-файл"""
    if not os.path.exists(source_path):
        return None
    
    async with aiofiles.open(source_path, "rb") as src:
        content = await src.read()
    async with aiofiles.open(dest_path, "wb") as dst:
        await dst.write(content)
    
    return {
        "name": file_name,
        "size": len(content),
        "type": file_type,
        "download_url": f"/api/v1/files/{chat_id}/{file_name}"
    }


async def copy_demo_files_to_chat(chat_dir: str, chat_id: str) -> List[Dict[str, Any]]:
    """Асинхронно копирует демонстрационные файлы в папку чата и возвращает информацию о них"""
    # Поднимаемся от app/utils/ до backend/
    storage_base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage")
    demo_source_dir = os.path.join(storage_base, "demo")
    
    # Параллельно копируем файлы
    tasks = [
        copy_single_demo_file(
            os.path.join(demo_source_dir, "demo_file.txt"),
            os.path.join(chat_dir, "assistant_response.txt"),
            "assistant_response.txt",
            "text/plain",
            chat_id
        ),
        copy_single_demo_file(
            os.path.join(demo_source_dir, "demo_data.json"),
            os.path.join(chat_dir, "data_export.json"),
            "data_export.json",
            "application/json",
            chat_id
        )
    ]
    
    results = await asyncio.gather(*tasks)
    
    # Фильтруем успешно скопированные файлы
    assistant_files = [result for result in results if result is not None]
    
    return assistant_files


async def send_webhook_request2(user_message: str, user_files: List[Dict[str, Any]] = None) -> Optional[str]:
    """Отправляет запрос на вебхук с файлами в формате base64 и возвращает ответ"""
    webhook_url = settings.webhook_url
    
    payload = {
        "chatInput": user_message,
        "sessionId": str(uuid.uuid4()),
        "files": []
    }
    
    # Если есть файлы, конвертируем их в base64
    if user_files:
        for file_info in user_files:
            try:
                # Читаем файл и конвертируем в base64
                chat_id = file_info.get("chat_id", "")
                file_path = os.path.join(get_storage_base_path(), chat_id, file_info["name"])
                if os.path.exists(file_path):
                    async with aiofiles.open(file_path, "rb") as f:
                        file_content = await f.read()
                        file_base64 = base64.b64encode(file_content).decode('utf-8')
                        
                        payload["files"].append({
                            "name": file_info["name"],
                            "type": file_info.get("type", "application/octet-stream"),
                            "size": file_info.get("size", len(file_content)),
                            "content": file_base64
                        })
                else:
                    webhook_logger.warning(f"File not found: {file_path}")
            except Exception as e:
                webhook_logger.error(f"Error processing file {file_info.get('name', 'unknown')}: {str(e)}")
    
    webhook_logger.info(f"Sending webhook request with {len(payload['files'])} files")
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code == 200:
                # Пытаемся получить JSON ответ
                try:
                    response_data = response.json()
                    
                    webhook_logger.info(f"Webhook response received successfully")
                    
                    # Возвращаем JSON как строку для дальнейшей обработки
                    import json
                    result = json.dumps(response_data, ensure_ascii=False)
                    webhook_logger.info(f"Response processed, length: {len(result)}")
                    return result
                    
                except Exception as json_error:
                    webhook_logger.warning(f"JSON parsing error: {str(json_error)}")
                    # Если не JSON, возвращаем как текст
                    result = response.text
                    webhook_logger.info(f"Response processed as text, length: {len(result)}")
                    return result
            else:
                webhook_logger.error(f"Webhook error: HTTP {response.status_code}")
                return f"Ошибка вебхука: HTTP {response.status_code}"
                
    except httpx.TimeoutException:
        webhook_logger.warning("Timeout exception occurred")
        return "Превышено время ожидания ответа от вебхука"
    except httpx.ConnectError as e:
        webhook_logger.error(f"Connection error: {str(e)}")
        return "Не удалось подключиться к вебхуку"
    except Exception as e:
        webhook_logger.error(f"General exception: {str(e)}")
        return f"Ошибка при обращении к вебхуку: {str(e)}"


async def generate_assistant_response(user_message: str, user_files: List[Dict[str, Any]], chat_id: str) -> tuple[str, List[Dict[str, Any]]]:
    """Генерирует ответ ассистента через вебхук или возвращает дефолтный ответ. Возвращает (текст, файлы)"""
    
    app_logger.info(f"Generating assistant response for message: {user_message}")
    app_logger.debug(f"Files count: {len(user_files) if user_files else 0}")
    
    # Отправляем запрос на вебхук с файлами в base64
    webhook_response = await send_webhook_request2(user_message, user_files)
    
    app_logger.info(f"Processing webhook response, type: {type(webhook_response)}")
    
    if webhook_response:
        # Обрабатываем файлы из ответа вебхука
        assistant_files = await process_webhook_response_files(webhook_response, chat_id)
        
        # Извлекаем текстовый ответ
        import json
        try:
            response_data = json.loads(webhook_response)
            
            # Обрабатываем разные форматы ответа
            if isinstance(response_data, list) and len(response_data) > 0:
                # Если ответ - массив, берем первый элемент
                first_item = response_data[0]
                text_response = first_item.get('output', 
                    first_item.get('text_response', 
                        first_item.get('message', 
                            first_item.get('response', 'Ответ получен от ассистента'))))
                app_logger.info(f"Extracted response from array format")
            elif isinstance(response_data, dict):
                # Если ответ - объект, извлекаем напрямую
                text_response = response_data.get('output', 
                    response_data.get('text_response', 
                        response_data.get('message', 
                            response_data.get('response', 'Ответ получен от ассистента'))))
                app_logger.info(f"Extracted response from object format")
            else:
                text_response = "Ответ получен от ассистента"
                app_logger.warning("Using default text response - unknown format")
        except Exception as e:
            app_logger.error(f"Error parsing response for text: {str(e)}")
            text_response = "Ответ получен от ассистента"
        
        app_logger.info(f"Returning webhook response with {len(assistant_files)} files")
        return text_response, assistant_files
    else:
        # Если вебхук недоступен, возвращаем дефолтный ответ
        app_logger.warning("Webhook failed, returning default response")
        return generate_assistant_content(user_files), []


def generate_assistant_content(user_files: List[Dict[str, Any]]) -> str:
    """Генерирует содержимое ответа ассистента в зависимости от файлов пользователя (дефолтный ответ)"""
    if user_files:
        file_list = ", ".join([f["name"] for f in user_files])
        return f"Я получил ваши файлы: {file_list}. Спасибо!"
    else:
        return "Спасибо за ваше сообщение!"


def get_storage_base_path() -> str:
    """Возвращает базовый путь к папке storage"""
    # Поднимаемся от app/utils/ до backend/
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage")


async def process_webhook_response_files(webhook_response: str, chat_id: str) -> List[Dict[str, Any]]:
    """Обрабатывает ответ вебхука и извлекает файлы из base64, сохраняя их в папке чата"""
    import json
    
    try:
        # Пытаемся распарсить ответ как JSON
        response_data = json.loads(webhook_response)
        
        if isinstance(response_data, list) and len(response_data) > 0:
            first_item = response_data[0]
            
            # Проверяем наличие файлов в ответе
            if 'files' in first_item and first_item['files']:
                app_logger.info(f"Found {first_item.get('file_count', len(first_item['files']))} files in webhook response")
                return await process_files_from_response(first_item, chat_id)
                
        elif isinstance(response_data, dict):
            
            # Проверяем наличие файлов в ответе
            if 'files' in response_data and response_data['files']:
                app_logger.info(f"Found {response_data.get('file_count', len(response_data['files']))} files in webhook response")
                return await process_files_from_response(response_data, chat_id)
        else:
            app_logger.warning(f"Response format not supported: {type(response_data)}")
                
    except json.JSONDecodeError as e:
        app_logger.error(f"JSON decode error: {str(e)}")
    except Exception as e:
        app_logger.error(f"Error processing webhook response: {str(e)}")
    
    return []


async def process_files_from_response(response_item: Dict[str, Any], chat_id: str) -> List[Dict[str, Any]]:
    """Вспомогательная функция для обработки файлов из ответа вебхука"""
    chat_dir = ensure_chat_directory(chat_id)
    processed_files = []
    
    for i, file_base64 in enumerate(response_item['files']):
        try:
            # Декодируем base64 файл
            file_content = base64.b64decode(file_base64)
            
            # Генерируем имя файла 
            file_name = f"forecast_result_{i + 1}.xlsx"  # Excel файл с результатами прогноза
            file_path = os.path.join(chat_dir, file_name)
            
            # Сохраняем файл асинхронно
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_content)
            
            app_logger.info(f"Saved file: {file_name}, size: {len(file_content)} bytes")
            
            # Добавляем информацию о файле
            processed_files.append({
                "name": file_name,
                "size": len(file_content),
                "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "chat_id": chat_id,
                "download_url": f"/api/v1/files/{chat_id}/{file_name}"
            })
            
        except Exception as e:
            app_logger.error(f"Error processing file {i}: {str(e)}")
            continue
    
    app_logger.info(f"Successfully processed {len(processed_files)} files")
    return processed_files
