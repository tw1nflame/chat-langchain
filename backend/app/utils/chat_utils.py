"""
Утилиты для работы с файлами в чат-системе
"""
from fastapi import HTTPException, UploadFile
from typing import List, Optional, Dict, Any
import uuid
import os
import asyncio
import aiofiles
from core.minio_manager import get_minio_manager_from_env
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
    """Сохраняет файл в Minio и возвращает две структуры: для MessageResponse и для вебхука"""
    if not file.filename or file.size <= 0:
        return None
    minio = get_minio_manager_from_env()
    bucket = "client-files"
    file_id = str(uuid.uuid4())
    content_bytes = await file.read()
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = tmp.name
    # Preserve original filename in object key to allow direct downloads by name
    # prefix with uuid to avoid collisions and keep uniqueness
    safe_filename = f"{file_id}_{file.filename}"
    object_name = f"{chat_id}/{safe_filename}"
    minio.upload_file(
        bucket,
        tmp_path,
        object_name,
        content_type=file.content_type
    )
    os.unlink(tmp_path)
    # Для MessageResponse (API)
    api_file = {
        "name": file.filename,
        "size": len(content_bytes),
        "type": file.content_type,
        "chat_id": chat_id,
        # expose the actual downloadable name (we prefixed with uuid)
        "download_url": f"/api/v1/files/{chat_id}/{safe_filename}"
    }
    # Для вебхука
    webhook_file = {
        "fileId": f"client-files/{object_name}",
        "fileName": file.filename,
        "mimeType": file.content_type
    }
    return {"api": api_file, "webhook": webhook_file}


async def process_uploaded_files(files: List[UploadFile], chat_dir: str, chat_id: str):
    """Загружает файлы в Minio и возвращает два массива: для API и для вебхука"""
    if not files or len(files) == 0:
        return [], []
    tasks = [save_single_file(file, chat_dir, chat_id) for file in files]
    results = await asyncio.gather(*tasks)
    api_files = [result["api"] for result in results if result is not None]
    webhook_files = [result["webhook"] for result in results if result is not None]
    return api_files, webhook_files


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
    # prefix demo files with uuid to avoid collisions and match download handler
    "download_url": f"/api/v1/files/{chat_id}/{str(uuid.uuid4())}_{file_name}"
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


async def send_webhook_request2(user_message: str, user_files: List[Dict[str, Any]] = None, chat_id: str | None = None) -> Optional[str]:
    """Отправляет запрос на вебхук с файлами в формате base64 и возвращает ответ.

    Добавляет в полезную нагрузку поле `chatId` если оно передано, чтобы внешние
    вебхуки могли связать запрос с конкретным чатом в системе.
    """
    webhook_url = settings.webhook_url
    
    # Формируем промпт с секцией ДОСТУПНЫЕ ФАЙЛЫ
    files_section = ""
    if user_files and len(user_files) > 0:
        import json
        files_section = f"\n\n--- ДОСТУПНЫЕ ФАЙЛЫ ---\n" + json.dumps(user_files, ensure_ascii=False, indent=2)
    prompt = f'ЗАПРОС ПОЛЬЗОВАТЕЛЯ:\n"{user_message.strip()}"' + files_section
    payload = {
        "chatInput": prompt,
        "sessionId": str(uuid.uuid4())
    }
    # Include chat id separately when available so external webhook can map it
    if chat_id:
        try:
            payload["chatId"] = str(chat_id)
        except Exception:
            payload["chatId"] = chat_id
    webhook_logger.info(f"Sending webhook request with {len(user_files) if user_files else 0} files (as metadata)")
    # Detailed logging to help debug 404/other HTTP errors
    request_headers = {"Content-Type": "application/json"}
    try:
        # Log request summary (truncate payload for large messages)
        import json as _json
        payload_str = _json.dumps(payload, ensure_ascii=False)
        webhook_logger.debug("Webhook request -> url=%s headers=%s payload_len=%d payload_preview=%s",
                             webhook_url, request_headers, len(payload_str), payload_str[:200])

        async with httpx.AsyncClient(timeout=540.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers=request_headers
            )

            # Log response status, headers and a preview of the body
            try:
                body_text = response.text
            except Exception:
                body_text = "<unreadable>"

            webhook_logger.info("Webhook response -> status=%s elapsed=%s headers=%s body_preview=%s",
                                response.status_code, getattr(response.elapsed, 'total_seconds', lambda: None)(),
                                dict(response.headers), (body_text or '')[:2000])

            if response.status_code == 200:
                try:
                    response_data = response.json()
                    webhook_logger.info("Webhook response received successfully")
                    result = _json.dumps(response_data, ensure_ascii=False)
                    webhook_logger.debug("Webhook response json length=%d", len(result))
                    return result
                except Exception as json_error:
                    webhook_logger.warning("JSON parsing error: %s", str(json_error))
                    result = body_text
                    webhook_logger.info("Response processed as text, length: %d", len(result) if result else 0)
                    return result
            else:
                webhook_logger.error("Webhook error: HTTP %s", response.status_code)
                # include a snippet of the response body to understand 404 page
                return f"Ошибка вебхука: HTTP {response.status_code} - { (body_text or '')[:1000] }"
    except httpx.TimeoutException:
        webhook_logger.warning("Timeout exception occurred when calling webhook %s", webhook_url)
        return "Превышено время ожидания ответа от вебхука"
    except httpx.ConnectError as e:
        webhook_logger.exception("Connection error when calling webhook %s: %s", webhook_url, str(e))
        return "Не удалось подключиться к вебхуку"
    except Exception as e:
        webhook_logger.exception("General exception when calling webhook %s: %s", webhook_url, str(e))
        return f"Ошибка при обращении к вебхуку: {str(e)}"


async def generate_assistant_response(user_message: str, user_files: List[Dict[str, Any]], chat_id: str) -> tuple[str, List[Dict[str, Any]]]:
    """Генерирует ответ ассистента через вебхук или возвращает дефолтный ответ. Возвращает (текст, файлы)"""
    
    app_logger.info(f"Generating assistant response for message: {user_message}")
    app_logger.debug(f"Files count: {len(user_files) if user_files else 0}")
    
    # Отправляем запрос на вебхук (передаем chat_id, чтобы вебхук мог связать ответ с чатом)
    webhook_response = await send_webhook_request2(user_message, user_files, chat_id)
    app_logger.info(f"Processing webhook response, type: {type(webhook_response)}")
    import json
    from core.minio_manager import get_minio_manager_from_env
    minio = get_minio_manager_from_env()
    text_response = "Ответ получен от ассистента"
    assistant_files = []
    # First, attempt to process response-embedded files (base64) and persist them to Minio.
    try:
        processed_files = await process_webhook_response_files(webhook_response, chat_id)
        if processed_files and len(processed_files) > 0:
            # processed_files are already shaped as {name,size,type,download_url}
            # Add fileId (minio path) so downstream code can stat or reference them
            for pf in processed_files:
                # download_url format: /api/v1/files/{chat_id}/{safe_name}
                try:
                    parts = pf.get('download_url', '').split('/')
                    safe_name = parts[-1] if parts else None
                    if safe_name:
                        pf['fileId'] = f"client-files/{chat_id}/{safe_name}"
                except Exception:
                    pass
            assistant_files = processed_files
    except Exception:
        app_logger.exception("process_webhook_response_files_failed")
    if webhook_response:
        try:
            response_data = json.loads(webhook_response)
            def enrich_file_with_size(f):
                file_id = f.get('fileId')
                size = 0
                if file_id:
                    try:
                        stat = minio.client.stat_object('client-files', '/'.join(file_id.split('/')[1:]))
                        size = stat.size
                    except Exception as e:
                        app_logger.warning(f"Could not get size for {file_id}: {e}")
                return {
                    'name': f.get('fileName'),
                    'type': f.get('mimeType'),
                    'fileId': file_id,
                    'download_url': f"/api/v1/files/{'/'.join(file_id.split('/')[1:])}",
                    'size': size
                }
            if isinstance(response_data, list) and len(response_data) > 0:
                first_item = response_data[0]
                text_response = first_item.get('output',
                    first_item.get('text_response',
                        first_item.get('message',
                            first_item.get('response', 'Ответ получен от ассистента'))))
                # If there are files referenced by the webhook (by fileId or metadata), enrich them.
                if 'files' in first_item and first_item['files'] and not assistant_files:
                    assistant_files = [enrich_file_with_size(f) for f in first_item['files']]
                app_logger.info(f"Extracted response from array format")
            elif isinstance(response_data, dict):
                text_response = response_data.get('output',
                    response_data.get('text_response',
                        response_data.get('message',
                            response_data.get('response', 'Ответ получен от ассистента'))))
                if 'files' in response_data and response_data['files'] and not assistant_files:
                    assistant_files = [enrich_file_with_size(f) for f in response_data['files']]
                app_logger.info(f"Extracted response from object format")
            else:
                app_logger.warning("Using default text response - unknown format")
        except Exception as e:
            app_logger.error(f"Error parsing response for text: {str(e)}")
    app_logger.info(f"Returning webhook response with {len(assistant_files)} files")
    return text_response, assistant_files


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
    from core.minio_manager import get_minio_manager_from_env
    minio = get_minio_manager_from_env()
    
    for i, file_data in enumerate(response_item['files']):
        try:
            # Проверяем, является ли файл объектом с именем и содержимым или просто base64 строкой
            if isinstance(file_data, dict) and 'name' in file_data and 'content' in file_data:
                # Новый формат: файл с именем и содержимым
                file_name = file_data['name']
                file_base64 = file_data['content']
            else:
                # Старый формат: просто base64 строка
                file_name = f"forecast_result_{i + 1}.xlsx"
                file_base64 = file_data
            
            # Декодируем base64 файл
            file_content = base64.b64decode(file_base64)
            
            # Путь для сохранения файла
            # prefix with uuid to avoid collisions and to match how we expose download_url
            safe_name = f"{str(uuid.uuid4())}_{file_name}"
            file_path = os.path.join(chat_dir, safe_name)
            
            # Сохраняем файл асинхронно
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_content)
            
            app_logger.info(f"Saved file: {file_name}, size: {len(file_content)} bytes")
            
            # Определяем MIME тип по расширению файла
            file_type = "application/octet-stream"  # По умолчанию
            if file_name.endswith('.xlsx'):
                file_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif file_name.endswith('.csv'):
                file_type = "text/csv"
            elif file_name.endswith('.txt'):
                file_type = "text/plain"
            elif file_name.endswith('.json'):
                file_type = "application/json"
            
            # Добавляем информацию о файле
            # Also upload saved file to Minio so it can be served via the existing download endpoint
            try:
                bucket = "client-files"
                object_name = f"{chat_id}/{safe_name}"
                if minio and getattr(minio, 'upload_file', None):
                    # minio.upload_file(bucket, local_path, object_name, content_type)
                    minio.upload_file(bucket, file_path, object_name, file_type)
            except Exception:
                app_logger.exception("minio_upload_failed_for_webhook_file")

            processed_files.append({
                "name": file_name,
                "size": len(file_content),
                "type": file_type,
                "chat_id": chat_id,
                "download_url": f"/api/v1/files/{chat_id}/{safe_name}",
                "fileId": f"client-files/{chat_id}/{safe_name}"
            })
            
        except Exception as e:
            app_logger.error(f"Error processing file {i}: {str(e)}")
            continue
    
    app_logger.info(f"Successfully processed {len(processed_files)} files")
    return processed_files
