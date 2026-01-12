from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
from collections import defaultdict
import uuid
import os
from datetime import datetime
from core.database import get_db
from models.chat import Chat, Message, User, File as FileModel
from schemas.chat import ChatCreate, ChatResponse, MessageResponse, ChatExchangeResponse
from utils.chat_utils import (
    validate_message_input,
    ensure_chat_directory,
    process_uploaded_files,
    generate_assistant_response
)
from core.minio_manager import get_minio_manager_from_env
from core.logging_config import app_logger
from core.config import settings
from sqlalchemy import text
from .deps import get_current_owner

router = APIRouter()

# Log key config flags at import time to detect environment misconfiguration quickly
try:
    app_logger.info("auth_config", extra={"supabase_url_configured": bool(settings.supabase_url)})
except Exception:
    # Best effort
    pass


def _serialize_chat(chat: Chat) -> dict:
    return {
        "id": str(chat.id) if chat and getattr(chat, 'id', None) is not None else None,
        "title": getattr(chat, 'title', None),
        "owner_id": str(chat.owner_id) if getattr(chat, 'owner_id', None) is not None else None,
        "created_at": getattr(chat, 'created_at', None),
        "updated_at": getattr(chat, 'updated_at', None),
    }


def _serialize_message(msg: Message) -> dict:
    return {
        "id": str(msg.id) if msg and getattr(msg, 'id', None) is not None else None,
        "chat_id": str(msg.chat_id) if getattr(msg, 'chat_id', None) is not None else None,
        "role": getattr(msg, 'role', None),
        "content": getattr(msg, 'content', None),
        "files": getattr(msg, 'files', []) if hasattr(msg, 'files') else [],
        "created_at": getattr(msg, 'created_at', None),
        "owner_id": str(getattr(msg, 'owner_id')) if getattr(msg, 'owner_id', None) is not None else None,
    }


def _headers_preview_from_request(request: Request | None) -> str:
    """Return a compact, redacted string preview of request headers for logging."""
    try:
        hdrs = dict(request.headers) if request is not None else {}
    except Exception:
        return ""

    parts = []
    try:
        for k, v in hdrs.items():
            kl = k.lower()
            if kl in ("authorization", "cookie", "set-cookie"):
                parts.append(f"{k}:<REDACTED>")
            else:
                val = v if v is not None else ""
                shortened = (val[:50] + "...") if len(val) > 50 else val
                parts.append(f"{k}:{shortened}")
        return ", ".join(parts)
    except Exception:
        return ""


def _get_request_id(request: Request | None) -> str:
    """Return an existing x-request-id header or generate a short UUID for correlation."""
    try:
        if request is None:
            return str(uuid.uuid4())
        rid = request.headers.get("x-request-id")
        if rid:
            return rid
    except Exception:
        pass
    return str(uuid.uuid4())

@router.get("/chats", response_model=List[ChatResponse])
async def get_chats(request: Request, db: Session = Depends(get_db), owner_id: str = Depends(get_current_owner)):
    """Получить все чаты"""
    try:
        # Log incoming request and headers (redacted) to diagnose auth issues
        headers_preview = _headers_preview_from_request(request)
        req_id = _get_request_id(request)
        # Print to stdout for immediate debugging visibility
        print(f"[DEBUG] incoming_request request_id={req_id} method={request.method} path={request.url.path} headers_preview={headers_preview} supabase_url_configured={bool(settings.supabase_url)}")
        app_logger.info("incoming_request", extra={
            "method": request.method,
            "path": str(request.url.path),
            "headers_preview": headers_preview,
            "supabase_url_configured": bool(settings.supabase_url),
            "request_id": req_id,
            # don't include tokens
        })

        # Only return chats that belong to this owner (owner_id resolved by dependency)
        chats = db.query(Chat).filter(Chat.owner_id == owner_id).order_by(Chat.created_at.desc()).all()
        results = []
        for c in chats:
            serial = _serialize_chat(c)
            # If title is missing or default, try to compute a nicer title from the first user message
            try:
                # Compute first_message: prefer the earliest user message, otherwise use the earliest message of any role.
                first_msg = None
                try:
                    first_user_msg = db.query(Message).filter(Message.chat_id == c.id, Message.role == 'user').order_by(Message.created_at).first()
                    if first_user_msg and getattr(first_user_msg, 'content', None):
                        first_msg = first_user_msg
                    else:
                        # fall back to earliest message of any role
                        first_msg = db.query(Message).filter(Message.chat_id == c.id).order_by(Message.created_at).first()

                    if first_msg and getattr(first_msg, 'content', None):
                        t = first_msg.content.strip()[:60]
                        if len(first_msg.content.strip()) > 60:
                            t += "..."
                        # Only override title when missing or a default placeholder
                        if not serial.get("title") or serial.get("title") in ("Новый чат", ""):
                            serial["title"] = t
                        # Include the first_message explicitly for frontend use
                        serial["first_message"] = first_msg.content.strip()
                        serial["first_message_role"] = getattr(first_msg, 'role', None)
                    else:
                        serial["first_message"] = None
                        serial["first_message_role"] = None
                except Exception:
                    # best-effort: don't fail the whole listing if first message lookup fails
                    serial["first_message"] = None
                    serial["first_message_role"] = None

                # Also include a short preview of the last message (if any) so frontend can show it immediately
                last_msg = db.query(Message).filter(Message.chat_id == c.id).order_by(Message.created_at.desc()).first()
                if last_msg and getattr(last_msg, 'content', None):
                    # Return the full last message; let frontend decide how to preview/truncate it
                    serial["last_message"] = last_msg.content.strip()
                    # Also include the role of the last message so frontend can display an appropriate label
                    try:
                        serial["last_message_role"] = getattr(last_msg, 'role', None)
                    except Exception:
                        serial["last_message_role"] = None
            except Exception:
                app_logger.debug("get_chats_title_compute_failed", extra={"chat_id": getattr(c, 'id', None)})
            results.append(serial)
        # Debug: print a small preview of results to help frontend diagnostics (do not log tokens)
        try:
            preview_sample = []
            for r in results[:3]:
                preview_sample.append({
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "first_message_present": bool(r.get("first_message")),
                    "last_message_present": bool(r.get("last_message")),
                })
            print(f"[DEBUG] get_chats_preview request_id={req_id} sample={preview_sample}")
            app_logger.debug("get_chats_preview", extra={"request_id": req_id, "sample": preview_sample})
        except Exception:
            pass
        return results
    except HTTPException:
        # Expected client error (auth/ownership) - log at warning without traceback
        app_logger.warning("get_chats_client_error")
        raise
    except Exception as e:
        app_logger.exception("get_chats_failed")
        raise HTTPException(status_code=500, detail=f"Failed to fetch chats: {str(e)}")

@router.post("/chats", response_model=ChatResponse)
async def create_chat(chat: ChatCreate, request: Request, db: Session = Depends(get_db), owner_id: str = Depends(get_current_owner)):
    """Создать новый чат"""
    try:

        # owner_id is resolved by dependency; if not present, dependency already raised 401

        chat_id = str(uuid.uuid4())
        db_chat = Chat(id=chat_id, title=chat.title or "Новый чат", owner_id=owner_id)
        db.add(db_chat)
        db.commit()
        db.refresh(db_chat)
        # Return a serialized dict so Pydantic receives string ids (not UUID objects)
        return _serialize_chat(db_chat)
    except Exception as e:
        app_logger.exception("create_chat_failed")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to create chat: {str(e)}")

@router.get("/chats/{chat_id}/messages", response_model=List[MessageResponse])
async def get_messages(chat_id: str, request: Request, db: Session = Depends(get_db), owner_id: str = Depends(get_current_owner)):
    """Получить сообщения чата"""
    try:
        # Log incoming request and headers (redacted) to diagnose auth issues
        headers_preview = _headers_preview_from_request(request)
        app_logger.info("incoming_request", extra={
            "method": request.method,
            "path": str(request.url.path),
            "headers_preview": headers_preview,
            "supabase_url_configured": bool(settings.supabase_url),
        })

        # owner_id resolved by dependency

        # Verify that the chat belongs to this owner
        chat_row = db.query(Chat).filter(Chat.id == chat_id).first()
        # Deny access if chat missing or owner is not set or owner doesn't match
        if not chat_row or (chat_row.owner_id is None) or (str(chat_row.owner_id) != str(owner_id)):
            # Print to stdout for quick debugging: show resolved owner and the chat owner in DB
            try:
                db_owner = getattr(chat_row, 'owner_id', None) if chat_row else None
                print(f"[DEBUG] unauthorized_chat_access request_id={_get_request_id(request)} requested_chat={chat_id} resolved_owner={owner_id} chat_owner_in_db={db_owner}")
            except Exception:
                pass
            app_logger.warning("unauthorized_chat_access", extra={"requested_chat": chat_id, "owner_id": owner_id})
            raise HTTPException(status_code=404, detail="Chat not found")

        msgs = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.created_at).all()

        # Load all files for the chat once. Newer files should have message_id set.
        # Older/legacy files may have message_id=NULL; assign those to the nearest message by timestamp.
        files_for_chat = db.query(FileModel).filter(FileModel.chat_id == chat_id).all()

        # Build mapping from message_id -> list[FileModel]
        files_by_message = defaultdict(list)
        legacy_files = []
        for fr in files_for_chat:
            try:
                if getattr(fr, 'message_id', None):
                    files_by_message[str(fr.message_id)].append(fr)
                else:
                    legacy_files.append(fr)
            except Exception:
                # On any unexpected attribute issue, treat as legacy
                legacy_files.append(fr)

        # If there are legacy files, assign each to the nearest message by created_at (best-effort)
        if legacy_files and msgs:
            # prepare list of (msg_id, created_at) for distance computation
            msg_tuples = []
            for m in msgs:
                try:
                    msg_tuples.append((str(m.id), getattr(m, 'created_at', None)))
                except Exception:
                    msg_tuples.append((str(m.id), None))

            for lf in legacy_files:
                assigned_msg_id = None
                try:
                    f_ts = getattr(lf, 'created_at', None)
                    # If either timestamp missing, assign to the last message as a safe default
                    if f_ts is None:
                        assigned_msg_id = msg_tuples[-1][0]
                    else:
                        # find message with minimal absolute time delta
                        best_id = None
                        best_delta = None
                        for mid, mts in msg_tuples:
                            if mts is None:
                                continue
                            delta = abs((f_ts - mts).total_seconds())
                            if best_delta is None or delta < best_delta:
                                best_delta = delta
                                best_id = mid
                        assigned_msg_id = best_id or msg_tuples[-1][0]
                except Exception:
                    assigned_msg_id = msg_tuples[-1][0]
                files_by_message[assigned_msg_id].append(lf)

        # MessageResponse includes files, which are stored in FileModel; attach them per message
        serialized = []
        for m in msgs:
            sm = _serialize_message(m)
            try:
                files_rows = files_by_message.get(str(m.id), [])
                files_list = []
                for fr in files_rows:
                    owner_val = getattr(fr, 'owner_id', None)
                    files_list.append({
                        "name": getattr(fr, 'name', None),
                        "size": getattr(fr, 'size', None),
                        "type": getattr(fr, 'type', None),
                        "download_url": getattr(fr, 'download_url', None),
                        # Ensure owner_id is a string (Pydantic expects str), handle UUIDs safely
                        "owner_id": str(owner_val) if owner_val is not None else None,
                    })
                sm['files'] = files_list
            except Exception:
                sm['files'] = []
            serialized.append(sm)
        try:
            # Log count and a small preview to help debug frontend issues
            app_logger.info(
                "get_messages_fetched",
                extra={
                    "chat_id": chat_id,
                    "count": len(serialized),
                    "preview": serialized[:5],
                },
            )
        except Exception:
            # Best-effort logging; don't fail request if logging preview fails
            app_logger.debug("get_messages_fetched_preview_failed", extra={"chat_id": chat_id})

        return serialized
    except HTTPException:
        app_logger.warning("get_messages_client_error", extra={"chat_id": chat_id})
        raise
    except Exception as e:
        app_logger.exception(f"get_messages_failed chat_id={chat_id}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch messages: {str(e)}")


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, request: Request, db: Session = Depends(get_db), owner_id: str = Depends(get_current_owner)):
    """Delete a chat and its related messages/files. Requires owner auth."""
    try:
        headers_preview = _headers_preview_from_request(request)
        app_logger.info("incoming_request", extra={
            "method": request.method,
            "path": str(request.url.path),
            "headers_preview": headers_preview,
            "supabase_url_configured": bool(settings.supabase_url),
        })
        # owner_id resolved by dependency

        # Verify ownership
        chat_row = db.query(Chat).filter(Chat.id == chat_id).first()
        # Deny delete if chat missing or has no owner or owner doesn't match
        if not chat_row or (chat_row.owner_id is None) or (str(chat_row.owner_id) != str(owner_id)):
            try:
                db_owner = getattr(chat_row, 'owner_id', None) if chat_row else None
                print(f"[DEBUG] unauthorized_chat_delete request_id={_get_request_id(request)} requested_chat={chat_id} resolved_owner={owner_id} chat_owner_in_db={db_owner}")
            except Exception:
                pass
            app_logger.warning("unauthorized_chat_access", extra={"requested_chat": chat_id, "owner_id": owner_id})
            raise HTTPException(status_code=404, detail="Chat not found")

        # Delete associated files from Minio (best-effort) and DB
        try:
            files = db.query(FileModel).filter(FileModel.chat_id == chat_id).all()
            minio = get_minio_manager_from_env()
            bucket = "client-files"
            for f in files:
                try:
                    if minio and getattr(minio, 'client', None):
                        object_name = f"{chat_id}/{f.name}"
                        try:
                            minio.client.remove_object(bucket, object_name)
                            app_logger.info("minio_object_deleted", extra={"object": object_name, "chat_id": chat_id})
                        except Exception:
                            app_logger.warning("minio_object_delete_failed", extra={"object": object_name, "chat_id": chat_id})
                except Exception:
                    app_logger.exception("minio_delete_iteration_failed")
            # Remove FileModel rows
            try:
                db.query(FileModel).filter(FileModel.chat_id == chat_id).delete(synchronize_session=False)
            except Exception:
                app_logger.exception("delete_file_rows_failed")
        except Exception:
            app_logger.exception("files_cleanup_failed")

        # Delete messages and chat row
        try:
            db.query(Message).filter(Message.chat_id == chat_id).delete(synchronize_session=False)
            db.delete(chat_row)
            db.commit()
            app_logger.info("chat_deleted", extra={"chat_id": chat_id, "owner_id": owner_id})
            return {"detail": "Chat deleted"}
        except Exception as e:
            app_logger.exception("chat_delete_failed")
            raise HTTPException(status_code=500, detail=f"Failed to delete chat: {str(e)}")

    except HTTPException:
        app_logger.warning("delete_chat_client_error", extra={"chat_id": chat_id})
        raise
    except Exception as e:
        app_logger.exception("delete_chat_unexpected_failed")
        raise HTTPException(status_code=500, detail=f"Failed to delete chat: {str(e)}")

@router.post("/chats/{chat_id}/messages", response_model=ChatExchangeResponse)
async def send_message_and_get_response(
    chat_id: str, 
    role: str = Form(...),
    content: str = Form(default=""),
    files: List[UploadFile] = File(default=[]),
    request: Request = None,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_owner),
):
    """Отправить сообщение в чат и получить ответ ассистента"""
    
    # Log request basics and headers for debugging. Redact sensitive headers (Authorization, Cookie).
    try:
        hdrs = dict(request.headers) if request else {}
    except Exception:
        hdrs = {}
    try:
        preview_parts = []
        for k, v in hdrs.items():
            kl = k.lower()
            if kl in ("authorization", "cookie", "set-cookie"):
                preview_parts.append(f"{k}: <REDACTED>")
            else:
                val = v if v is not None else ""
                shortened = (val[:50] + "...") if len(val) > 50 else val
                preview_parts.append(f"{k}:{shortened}")
        headers_preview = ", ".join(preview_parts)
    except Exception:
        headers_preview = ""

    app_logger.info(
        "received_message",
        extra={
            "chat_id": chat_id,
            "role": role,
            "content_length": len(content),
            "files_count": len(files),
            "headers_preview": headers_preview,
            "method": request.method if request is not None else None,
            "path": str(request.url.path) if request is not None else None,
        },
    )
    # Print to stdout for quick debugging
    try:
        rid = _get_request_id(request)
        print(f"[DEBUG] received_message request_id={rid} chat_id={chat_id} role={role} content_len={len(content)} files_count={len(files)} headers_preview={headers_preview}")
    except Exception:
        pass
    
    # Валидация входных данных
    validate_message_input(content, files)
    
    # owner_id resolved by dependency
    # The dependency returns the Supabase user id or raises 401.
    owner_email = None
    owner_name = None

    # Подготовка окружения
    chat_dir = ensure_chat_directory(chat_id)
    
    # Обработка сообщения пользователя
    api_files, webhook_files = await process_uploaded_files(files, chat_dir, chat_id)
    app_logger.info("files_processed", extra={"api_files_count": len(api_files), "webhook_files_count": len(webhook_files)})
    # Verify chat exists and user has access to it
    try:
        db_chat = db.query(Chat).filter(Chat.id == chat_id).first()
        if not db_chat:
            # Chat must exist before sending messages - it should be created via POST /chats endpoint first
            app_logger.warning("chat_not_found_for_message", extra={"chat_id": chat_id, "owner_id": owner_id})
            raise HTTPException(status_code=404, detail="Chat not found. Create chat first using POST /chats endpoint.")
        
        # Verify chat ownership
        if db_chat.owner_id is None or str(db_chat.owner_id) != str(owner_id):
            app_logger.warning("unauthorized_chat_message_attempt", extra={"chat_id": chat_id, "resolved_owner": owner_id, "chat_owner_in_db": getattr(db_chat, 'owner_id', None)})
            raise HTTPException(status_code=404, detail="Chat not found")
    except HTTPException:
        raise
    except Exception as e: 
        # Log full exception with traceback for diagnostics
        app_logger.exception(f"chat_fetch_failed chat_id={chat_id}")
        # Surface the error message to the client for easier debugging (safe for dev)
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat: {str(e)}")

    # Create message record
    try:
        db_message = Message(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            role=role,
            content=content,
        )
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
    except Exception as e:
        app_logger.exception(f"user_message_persist_failed chat_id={chat_id}")
        raise HTTPException(status_code=500, detail=f"Failed to persist user message: {str(e)}")

    # Update chat title based on the first user message if the title is empty or default
    try:
        if db_chat:
            current_title = getattr(db_chat, 'title', None) or ''
            default_titles = ["Новый чат", ""]
            if current_title.strip() in default_titles:
                # Use the user's message as the chat title (truncate to 60 chars)
                new_title = (content.strip()[:60] + ("..." if len(content.strip()) > 60 else "")) if content else current_title
                db_chat.title = new_title
                db.add(db_chat)
                db.commit()
                db.refresh(db_chat)
                app_logger.info("chat_title_updated", extra={"chat_id": chat_id, "new_title": new_title})
    except Exception:
        app_logger.exception("chat_title_update_failed")

    user_message = MessageResponse(
        id=str(db_message.id),
        chat_id=str(db_message.chat_id),
        role=db_message.role,
        content=db_message.content,
        files=api_files,
        created_at=db_message.created_at
    )

    app_logger.info("user_message_processed", extra={"message_id": user_message.id, "chat_id": chat_id})

    # Генерация ответа ассистента
    app_logger.info("calling_generate_assistant_response", extra={"chat_id": chat_id, "webhook_files_count": len(webhook_files)})
    try:
        assistant_content, assistant_files = await generate_assistant_response(content, webhook_files, chat_id)
        app_logger.info("assistant_response_generated", extra={"files_count": len(assistant_files), "content_len": len(assistant_content or "")})
    except Exception as e:
        app_logger.exception(f"assistant_response_failed chat_id={chat_id}")
        raise HTTPException(status_code=500, detail=f"Assistant generation failed: {str(e)}")
    # Persist assistant message - but first verify chat still exists
    try:
        # Re-check that the chat still exists before saving assistant message
        # (user might have deleted chat while webhook was processing)
        chat_still_exists = db.query(Chat).filter(Chat.id == chat_id).first()
        if not chat_still_exists:
            app_logger.warning("chat_deleted_during_processing", extra={"chat_id": chat_id})
            raise HTTPException(status_code=404, detail="Chat was deleted during processing")
        
        db_assistant_message = Message(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            role="assistant",
            content=assistant_content,
        )
        db.add(db_assistant_message)
        db.commit()
        db.refresh(db_assistant_message)
    except HTTPException:
        raise
    except Exception as e:
        app_logger.exception(f"assistant_message_persist_failed chat_id={chat_id}")
        raise HTTPException(status_code=500, detail=f"Failed to persist assistant message: {str(e)}")

    # Save assistant files metadata in File model
    try:
        # Persist files uploaded by the user (api_files) and link to the user message
        for f in api_files:
            try:
                db_file = FileModel(
                    id=str(uuid.uuid4()),
                    chat_id=chat_id,
                    message_id=str(db_message.id),
                    name=f.get('name'),
                    size=f.get('size'),
                    type=f.get('type'),
                    download_url=f.get('download_url'),
                    owner_id=owner_id
                )
                db.add(db_file)
                try:
                    # flush per-row to avoid executemany batching with RETURNING which
                    # may trigger driver/resultset mismatches for some types
                    db.flush()
                except Exception:
                    app_logger.exception("flush_user_file_failed")
                app_logger.info("user_file_saved", extra={"file_name": f.get('name'), "chat_id": chat_id, "message_id": str(db_message.id), "owner_id": owner_id})
            except Exception:
                app_logger.exception("persist_user_file_failed")

        # Persist assistant files and link them to the assistant message
        for f in assistant_files:
            try:
                db_file = FileModel(
                    id=str(uuid.uuid4()),
                    chat_id=chat_id,
                    message_id=str(db_assistant_message.id),
                    name=f.get('name'),
                    size=f.get('size'),
                    type=f.get('type'),
                    download_url=f.get('download_url'),
                    owner_id=owner_id
                )
                db.add(db_file)
                try:
                    db.flush()
                except Exception:
                    app_logger.exception("flush_assistant_file_failed")
                app_logger.info("assistant_file_saved", extra={"file_name": f.get('name'), "chat_id": chat_id, "message_id": str(db_assistant_message.id), "owner_id": owner_id})
            except Exception:
                app_logger.exception("persist_assistant_file_failed")
        # Try to commit; if DB lacks the new column, add it and retry
        try:
            db.commit()
        except Exception as commit_err:
            try:
                from sqlalchemy.exc import ProgrammingError
                if isinstance(commit_err, ProgrammingError) or 'message_id' in str(commit_err):
                    app_logger.warning("commit_failed_missing_column_message_id, attempting to add column and retry")
                    # rollback session and add column
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    try:
                        db.execute(text('ALTER TABLE files ADD COLUMN IF NOT EXISTS message_id VARCHAR'))
                        db.commit()
                    except Exception:
                        app_logger.exception("failed_to_add_message_id_column")
                        raise
                    # re-add file rows and commit again
                    try:
                        for f in api_files:
                            db_file = FileModel(
                                id=str(uuid.uuid4()),
                                chat_id=chat_id,
                                message_id=str(db_message.id),
                                name=f.get('name'),
                                size=f.get('size'),
                                type=f.get('type'),
                                download_url=f.get('download_url'),
                                owner_id=owner_id
                            )
                            db.add(db_file)
                        for f in assistant_files:
                            db_file = FileModel(
                                id=str(uuid.uuid4()),
                                chat_id=chat_id,
                                message_id=str(db_assistant_message.id),
                                name=f.get('name'),
                                size=f.get('size'),
                                type=f.get('type'),
                                download_url=f.get('download_url'),
                                owner_id=owner_id
                            )
                            db.add(db_file)
                        db.commit()
                    except Exception:
                        app_logger.exception("recommit_files_after_adding_column_failed")
                        raise
                else:
                    app_logger.exception(f"assistant_files_persist_failed chat_id={chat_id}")
                    raise
            except Exception:
                # Re-raise as HTTPException so client gets a 500
                raise HTTPException(status_code=500, detail=f"Failed to persist assistant files: {str(commit_err)}")
    except Exception as e:
        app_logger.exception(f"assistant_files_persist_failed chat_id={chat_id}")
        raise HTTPException(status_code=500, detail=f"Failed to persist assistant files: {str(e)}")

    assistant_message = MessageResponse(
        id=str(db_assistant_message.id),
        chat_id=str(db_assistant_message.chat_id),
        role=db_assistant_message.role,
        content=db_assistant_message.content,
        files=assistant_files,
        created_at=db_assistant_message.created_at
    )

    app_logger.info("assistant_message_generated", extra={"message_id": assistant_message.id, "chat_id": chat_id})

    # Возвращаем оба сообщения
    return ChatExchangeResponse(
        user_message=user_message,
        assistant_message=assistant_message
    )


@router.get("/debug/headers")
async def debug_headers(request: Request):
    """Dev-only: return a redacted preview of incoming headers and token length to help debug header propagation.

    WARNING: keep this endpoint only in local/dev environments. Do NOT enable in production.
    """
    headers_preview = _headers_preview_from_request(request)
    auth = request.headers.get("authorization")
    try:
        token_len = None
        if auth and auth.lower().startswith("bearer "):
            token_len = len(auth.split(" ", 1)[1])
    except Exception:
        token_len = None
    return {
        "headers_preview": headers_preview,
        "authorization_token_len": token_len,
        "request_id": _get_request_id(request),
    }

@router.get("/files/{chat_id}/{file_name}")
async def download_file(chat_id: str, file_name: str, request: Request, db: Session = Depends(get_db), owner_id: str = Depends(get_current_owner)):
    """Скачать файл из Minio по chat_id и file_name (fileId = client-files/{chat_id}/{file_name})"""
    req_id = _get_request_id(request)
    headers_preview = _headers_preview_from_request(request)
    print(f"[DEBUG] file_download_request request_id={req_id} chat_id={chat_id} file_name={file_name} resolved_owner={owner_id} headers_preview={headers_preview}")
    app_logger.info("file_download_request", extra={"chat_id": chat_id, "file_name": file_name, "request_id": req_id, "resolved_owner": owner_id, "headers_preview": headers_preview})
    # Verify ownership: ensure the requesting user owns the chat and that owner is set
    try:
        chat_row = db.query(Chat).filter(Chat.id == chat_id).first()
        # Log DB owner info to diagnose mismatches
        db_owner = getattr(chat_row, 'owner_id', None) if chat_row else None
        app_logger.debug("file_download_chat_owner_check", extra={"chat_id": chat_id, "db_owner": db_owner, "resolved_owner": owner_id})
        if not chat_row or (chat_row.owner_id is None) or (str(chat_row.owner_id) != str(owner_id)):
            # Print to stdout for quick debug
            print(f"[DEBUG] unauthorized_file_download_attempt request_id={req_id} chat_id={chat_id} resolved_owner={owner_id} chat_owner_in_db={db_owner}")
            app_logger.warning("unauthorized_file_download_attempt", extra={"chat_id": chat_id, "resolved_owner": owner_id, "chat_owner_in_db": db_owner})
            raise HTTPException(status_code=404, detail="File not found")
    except HTTPException:
        raise
    except Exception:
        app_logger.exception("file_download_ownership_check_failed")
        raise HTTPException(status_code=404, detail="File not found")

    minio = get_minio_manager_from_env()
    bucket = "client-files"
    # file_name may contain uuid prefix (as stored), use it directly as object key
    object_name = f"{chat_id}/{file_name}"
    try:
        # Try to stat the object first so we can log a clearer error when it doesn't exist
        try:
            stat = minio.client.stat_object(bucket, object_name)
            app_logger.info("minio_object_stat_ok", extra={"object": object_name, "size": getattr(stat, 'size', None), "chat_id": chat_id})
        except Exception as e_stat:
            app_logger.warning("minio_object_not_found_or_stat_failed", extra={"object": object_name, "error": str(e_stat), "chat_id": chat_id})
            # Fallthrough to get_object which will raise; we still give a clear log
        response = minio.client.get_object(bucket, object_name)
        return StreamingResponse(
            response,
            media_type='application/octet-stream',
            headers={
                # Use RFC5987 format to support UTF-8 filenames in Content-Disposition
                'Content-Disposition': f"attachment; filename*=UTF-8''{file_name}"
            }
        )
    except Exception as e:
        app_logger.error(f"Minio file download error: {str(e)}", extra={"object": object_name, "chat_id": chat_id, "request_id": req_id})
        # Return a 404 with Russian message to match existing behavior
        raise HTTPException(status_code=404, detail="Файл не найден в Minio")
