from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile, Header, Request, Response
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from collections import defaultdict
import uuid
import os
import shutil
import json
from datetime import datetime
from core.database import get_db
from models.chat import Chat, Message, User, File as FileModel, Chart
from schemas.chat import ChatCreate, ChatResponse, MessageResponse, ChatExchangeResponse
from utils.chat_utils import (
    validate_message_input,
    ensure_chat_directory,
    process_uploaded_files,
    generate_assistant_response,
    get_storage_base_path
)
from utils.storage_utils import (
    save_table_parquet,
    load_tables_for_message,
    get_table_as_excel_stream,
    delete_tables_for_message
)
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
        "charts": [{"id": str(c.id), "title": c.title, "spec": c.spec} for c in msg.charts] if hasattr(msg, 'charts') else [],
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
                
                # Load tables from Parquet
                tables_data = load_tables_for_message(str(m.id))
                for table in tables_data:
                    # Attach download URL for Excel using the specific index from file
                    idx = table.get('index', 0)
                    table['download_url'] = f"/api/v1/download/table/{m.id}/{idx}/export.xlsx"
                
                sm['tables'] = tables_data

            except Exception:
                sm['files'] = []
                sm['tables'] = []
            serialized.append(sm)
        try:
            # If there's a pending confirmation in the graph state, surface it on the last assistant message
            try:
                from core.agent_graph import graph
                config = {"configurable": {"thread_id": chat_id}}
                current_state = graph.get_state(config)
                if current_state and getattr(current_state, 'values', None):
                    vals = current_state.values
                    if vals.get('awaiting_confirmation') and vals.get('plan_id'):
                        # Find last assistant message in the serialized list and annotate it
                        for sm in reversed(serialized):
                            if sm.get('role') == 'assistant':
                                sm['awaiting_confirmation'] = True
                                sm['plan_id'] = vals.get('plan_id')
                                sm['confirmation_summary'] = vals.get('confirmation_summary')
                                break
            except Exception:
                app_logger.debug("get_messages_state_annotation_failed", extra={"chat_id": chat_id})

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

        # Cleanup physical files (Parquet tables and chat directory)
        try:
            # 1. Delete Parquet tables associated with messages
            messages = db.query(Message).filter(Message.chat_id == chat_id).all()
            for msg in messages:
                try:
                    delete_tables_for_message(str(msg.id))
                except Exception as e:
                    app_logger.warning(f"Failed to delete tables for message {msg.id}: {e}")

            # 2. Delete the chat directory itself (if it exists)
            chat_dir = ensure_chat_directory(chat_id)
            if os.path.exists(chat_dir):
                shutil.rmtree(chat_dir)
                app_logger.info(f"Deleted chat directory: {chat_dir}")

        except Exception as e:
             app_logger.error(f"Error during physical file cleanup for chat {chat_id}: {e}")

        # Delete associated files from DB (Storage removed)
        try:
            # Remove FileModel rows
            try:
                db.query(FileModel).filter(FileModel.chat_id == chat_id).delete(synchronize_session=False)
            except Exception:
                app_logger.exception("delete_file_rows_failed")
        except Exception:
            app_logger.exception("files_cleanup_failed")

        # Delete associated charts
        try:
            # Find all messages in this chat
            # (Note: Cascade delete on relationship should handle this if configured in DB, but explicit delete is safer for current session)
            # Fetch message IDs first
            msg_ids = db.query(Message.id).filter(Message.chat_id == chat_id).all()
            msg_ids = [m[0] for m in msg_ids]
            
            if msg_ids:
                 db.query(Chart).filter(Chart.message_id.in_(msg_ids)).delete(synchronize_session=False)
                 
        except Exception as e:
            app_logger.error(f"charts_cleanup_failed: {e}")

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
    
    # Log request
    try:
        hdrs = dict(request.headers) if request else {}
    except Exception:
        hdrs = {}
    
    app_logger.info(
        "received_message",
        extra={
            "chat_id": chat_id,
            "role": role,
            "content_length": len(content),
            "files_count": len(files),
        },
    )
    
    # Validate
    validate_message_input(content, files)
    
    # Don't create directory if file processing is stubbed/disabled or no files.
    # Currently process_uploaded_files is a stub returning [], [] so chat_dir is unused for upload.
    # We only create it if we actually have logic to save files there.
    # For now, we removed the eager creation to avoid empty folders.
    
    chat_dir = ensure_chat_directory(chat_id) 
    api_files, webhook_files = await process_uploaded_files(files, chat_dir, chat_id)
    
    # Verify chat logic
    try:
        db_chat = db.query(Chat).filter(Chat.id == chat_id).first()
        if not db_chat:
             raise HTTPException(status_code=404, detail="Chat not found. Create chat first using POST /chats endpoint.")
        if db_chat.owner_id is None or str(db_chat.owner_id) != str(owner_id):
             raise HTTPException(status_code=404, detail="Chat not found")
    except HTTPException:
        raise
    except Exception as e:
        app_logger.exception(f"chat_fetch_failed chat_id={chat_id}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat: {str(e)}")

    # User Message
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
        app_logger.exception("user_message_persist_failed")
        raise HTTPException(status_code=500, detail=f"Failed to persist user message: {str(e)}")
        
    # Title update
    try:
        if db_chat and (not db_chat.title or db_chat.title == "Новый чат" or not db_chat.title.strip()):
            new_title = (content.strip()[:60] + "...") if content and len(content.strip()) > 60 else (content.strip() or "Новый чат")
            db_chat.title = new_title
            db.add(db_chat)
            db.commit()
            db.refresh(db_chat)
    except Exception:
        app_logger.warning("title_update_failed")

    # Generate Assistant Response
    try:
        auth_token = hdrs.get("authorization", "").replace("Bearer ", "")
        # Use api_files as they are the ones uploaded by the user here
        assistant_content, assistant_files, tables, charts, awaiting_confirmation, confirmation_summary, plan_id = await generate_assistant_response(content, api_files, chat_id, owner_id, auth_token=auth_token)
    except Exception as e:
        app_logger.exception("assistant_generation_failed")
        raise HTTPException(status_code=500, detail=f"Assistant generation failed: {str(e)}")
        
    # Assistant Message
    try:
        # Verify chat still exists
        chat_still_exists = db.query(Chat).filter(Chat.id == chat_id).first()
        if not chat_still_exists:
            raise HTTPException(status_code=404, detail="Chat was deleted")

        # Avoid inserting a duplicate assistant message if the last assistant message content
        # for this chat matches the new content (can happen when confirmation summary was generated twice)
        last_asst = db.query(Message).filter(Message.chat_id == chat_id, Message.role == 'assistant').order_by(Message.created_at.desc()).first()
        if last_asst and getattr(last_asst, 'content', None) == assistant_content:
            app_logger.info("assistant_message_persist: duplicate assistant content detected, reusing last message")
            db_assistant_message = last_asst
        else:
            db_assistant_message = Message(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                role="assistant",
                content=assistant_content,
            )
            db.add(db_assistant_message)
            db.commit()
            db.refresh(db_assistant_message)

            # Log when a confirmation message is issued so we can trace plan_id and chat state
            try:
                if awaiting_confirmation:
                    app_logger.info("assistant_message_created_awaiting_confirmation", extra={"chat_id": chat_id, "message_id": str(db_assistant_message.id), "plan_id": plan_id})
            except Exception:
                app_logger.debug("assistant_message_confirm_log_failed", extra={"chat_id": chat_id})

        # Save Tables to Parquet (only if we just created a new assistant message or there are new tables)
        enriched_tables = []
        if tables and isinstance(tables, list):
            try:
                for idx, table_data in enumerate(tables):
                    rows = table_data.get("rows", [])
                    headers = table_data.get("headers", [])
                    if rows:
                        # Only save if the table file does not exist yet for this message/index (best-effort check)
                        try:
                            save_table_parquet(rows, headers, str(db_assistant_message.id), idx)
                            app_logger.info("table_parquet_saved", extra={"msg_id": db_assistant_message.id, "index": idx})
                        except Exception as ex:
                            app_logger.warning(f"table_parquet_save_skipped_or_failed: {ex}")
                        # Enrich for response
                        t_copy = table_data.copy()
                        t_copy['download_url'] = f"/api/v1/download/table/{db_assistant_message.id}/{idx}/export.xlsx"
                        enriched_tables.append(t_copy)
            except Exception as e:
                app_logger.error(f"failed_to_save_parquet_tables: {e}")
                enriched_tables = []
                
    except Exception as e:
        app_logger.exception("assistant_message_persist_failed")
        raise HTTPException(status_code=500, detail=f"Failed to persist assistant message: {str(e)}")
    except HTTPException:
        raise

    # Save Charts
    enriched_charts = []
    try:
        if charts:
            for chart_data in charts:
                chart_model = Chart(
                    id=str(uuid.uuid4()),
                    message_id=str(db_assistant_message.id),
                    owner_id=owner_id,
                    title=chart_data.get("title", "Generated Chart"),
                    spec=chart_data.get("spec", {})
                )
                db.add(chart_model)
                enriched_charts.append({
                    "id": chart_model.id,
                    "title": chart_model.title,
                    "spec": chart_model.spec
                })
            db.commit()
    except Exception as e:
        app_logger.error(f"failed_to_save_charts: {e}")

    # Save Files (User & Assistant)
    try:
        # Helper to save files
        def save_files_to_db(file_list, msg_id):
            if not file_list: return
            for f in file_list:
                db_file = FileModel(
                    id=str(uuid.uuid4()),
                    chat_id=chat_id,
                    message_id=msg_id,
                    name=f.get('name'),
                    size=f.get('size'),
                    type=f.get('type'),
                    download_url=f.get('download_url'),
                    owner_id=owner_id
                )
                db.add(db_file)
        
        save_files_to_db(api_files, str(db_message.id))
        save_files_to_db(assistant_files, str(db_assistant_message.id))
        
        db.commit()
    except Exception as e:
        # Fallback for missing column 'message_id'
        app_logger.error(f"file_save_failed: {e}")
        if 'message_id' in str(e):
             try:
                 db.rollback()
                 db.execute(text('ALTER TABLE files ADD COLUMN IF NOT EXISTS message_id VARCHAR'))
                 db.commit()
                 # Retry save
                 save_files_to_db(api_files, str(db_message.id))
                 save_files_to_db(assistant_files, str(db_assistant_message.id))
                 db.commit()
             except Exception:
                 app_logger.exception("retry_file_save_failed")

    # Construct Response
    user_msg_resp = MessageResponse(
        id=str(db_message.id),
        chat_id=str(db_message.chat_id),
        role=db_message.role,
        content=db_message.content,
        files=api_files,
        created_at=db_message.created_at
    )
    
    asst_msg_resp = MessageResponse(
        id=str(db_assistant_message.id),
        chat_id=str(db_assistant_message.chat_id),
        role=db_assistant_message.role,
        content=db_assistant_message.content,
        files=assistant_files,
        tables=enriched_tables,
        charts=enriched_charts,
        created_at=db_assistant_message.created_at,
        awaiting_confirmation=awaiting_confirmation,
        confirmation_summary=confirmation_summary,
        plan_id=plan_id
    )
    
    return ChatExchangeResponse(
        user_message=user_msg_resp,
        assistant_message=asst_msg_resp
    )


@router.get("/download/table/{message_id}/{table_index}/export.xlsx")
async def download_table_excel(message_id: str, table_index: int, owner_id: str = Depends(get_current_owner)):
    """Downloads a parquet table converted to Excel."""
    try:
        # Verify ownership
        db = next(get_db())
        msg = db.query(Message).filter(Message.id == message_id).first()
        if not msg:
             raise HTTPException(status_code=404, detail="Message not found")
        
        chat = db.query(Chat).filter(Chat.id == msg.chat_id).first()
        if not chat or str(chat.owner_id) != str(owner_id):
             raise HTTPException(status_code=403, detail="Access denied")
        
        output_stream = get_table_as_excel_stream(message_id, table_index)
        if not output_stream:
            raise HTTPException(status_code=404, detail="Table file not found")
            
        filename = f"export_{message_id}_{table_index}.xlsx"
        
        return StreamingResponse(
            output_stream,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        app_logger.error(f"Excel download error: {e}")
        raise HTTPException(status_code=500, detail="Download failed")


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
    """Скачивание файлов отключено (хранилище удалено)"""
    raise HTTPException(status_code=404, detail="Файловое хранилище отключено")

@router.post("/temporary/chat", response_model=ChatExchangeResponse)
async def temporary_chat_message(
    role: str = Form(...),
    content: str = Form(default=""),
    previous_messages: str = Form(default="[]"),
    files: List[UploadFile] = File(default=[]),
    request: Request = None,
    owner_id: str = Depends(get_current_owner),
):
    """
    Stateless/Temporary chat endpoint.
    Do NOT save chat or messages to DB.
    Files are saved temporarily and then deleted (TODO: implement cleanup cron).
    Note: Download links for tables/files may not be persistent or work if DB check is required.
    """
    # Log request
    try:
        hdrs = dict(request.headers) if request else {}
    except Exception:
        hdrs = {}
    
    app_logger.info(
        "received_temp_message",
        extra={
            "role": role,
            "content_length": len(content),
            "files_count": len(files),
        },
    )
    
    # Validate
    validate_message_input(content, files)
    
    # 1. Setup temporary environment
    temp_chat_id = str(uuid.uuid4())
    chat_dir = ensure_chat_directory(temp_chat_id) 
    
    try:
        # 2. Process Files
        api_files, webhook_files = await process_uploaded_files(files, chat_dir, temp_chat_id)
        
        # 3. Parse History
        try:
            history_data = json.loads(previous_messages)
            history_list = []
            if isinstance(history_data, list):
                for m in history_data:
                    if isinstance(m, str):
                        history_list.append(m)
                    elif isinstance(m, dict):
                        # Format: "Role: Content"
                        r = m.get("role", "unknown")
                        c = m.get("content", "")
                        history_list.append(f"{r}: {c}")
        except Exception:
            app_logger.warning("failed_to_parse_history_defaulting_to_empty")
            history_list = []

        # 4. Generate Response
        auth_token = hdrs.get("authorization", "").replace("Bearer ", "")
        
        # Determine effective owner_id for this session
        # We use the authenticated user's ID
        
        assistant_content, assistant_files, tables, charts, awaiting_confirmation, confirmation_summary, plan_id = await generate_assistant_response(
            content, 
            api_files, 
            temp_chat_id, 
            owner_id, 
            auth_token=auth_token, 
            history=history_list
        )
        
        # Assistant Message ID (Random, not in DB)
        asst_msg_id = str(uuid.uuid4())
        user_msg_id = str(uuid.uuid4())

        # 5. Handle Tables (No DB persistence support, so no download URL for now)
        enriched_tables = []
        if tables:
            for idx, table_data in enumerate(tables):
                # We return the data directly. Download links are omitted as they require DB message lookup.
                t_copy = table_data.copy()
                t_copy['download_url'] = None 
                enriched_tables.append(t_copy)

        enriched_charts = []
        if charts:
             for chart_data in charts:
                 enriched_charts.append({
                    "id": str(uuid.uuid4()),
                    "title": chart_data.get("title", "Chart"),
                    "spec": chart_data.get("spec", {})
                })

        # 6. Response Construction
        user_msg_resp = MessageResponse(
            id=user_msg_id,
            chat_id=temp_chat_id,
            role=role,
            content=content,
            files=api_files,
            created_at=datetime.utcnow()
        )
        
        asst_msg_resp = MessageResponse(
            id=asst_msg_id,
            chat_id=temp_chat_id,
            role="assistant",
            content=assistant_content,
            files=assistant_files,
            tables=enriched_tables,
            charts=enriched_charts,
            created_at=datetime.utcnow(),
            awaiting_confirmation=awaiting_confirmation,
            confirmation_summary=confirmation_summary,
            plan_id=plan_id
        )
        
        return ChatExchangeResponse(
            user_message=user_msg_resp,
            assistant_message=asst_msg_resp
        )
        
    except Exception as e:
        app_logger.exception("temporary_chat_failed")
        raise HTTPException(status_code=500, detail=f"Temporary chat failed: {str(e)}")
