from fastapi import APIRouter, Depends, HTTPException, Request
from core.agent_graph import graph
from .deps import get_current_owner
from core.database import get_db
from models.chat import Chat
from core.logging_config import app_logger
from typing import Optional
import uuid
import json
router = APIRouter()

@router.post('/chats/{chat_id}/confirm_plan')

async def confirm_plan(chat_id: str, confirm: bool = True, plan_id: Optional[str] = None, request: Request = None, owner_id: str = Depends(get_current_owner)):
    """Confirm or cancel a pending plan created by the planner for a given chat/thread.

    Behavior:
    - validate ownership of chat
    - check that the graph has a saved state with awaiting_confirmation=True
    - on confirm=True: resume execution by invoking the graph with awaiting_confirmation=False
    - on confirm=False: cancel the plan by clearing it
    """
    try:
        # Entry debug
        try:
            app_logger.debug("confirm_plan_called", extra={"chat_id": chat_id, "provided_plan_id": plan_id, "owner_id": owner_id})
        except Exception:
            app_logger.debug("confirm_plan_called_failed_to_serialize_args")

        # validate chat ownership
        db = next(get_db())
        chat_row = db.query(Chat).filter(Chat.id == chat_id).first()
        if not chat_row or chat_row.owner_id is None or str(chat_row.owner_id) != str(owner_id):
            app_logger.warning("confirm_plan_unauthorized", extra={"chat_id": chat_id, "owner_id": owner_id})
            raise HTTPException(status_code=404, detail="Chat not found")

        config = {"configurable": {"thread_id": chat_id}}
        current_state = graph.get_state(config)
        if not current_state or not getattr(current_state, 'values', None):
            raise HTTPException(status_code=400, detail="No running plan found for this thread")

        values = current_state.values
        expected_plan_id = values.get('plan_id')

        # Emit a debug snapshot to help diagnose plan_id race/mismatch issues
        try:
            # Build a sanitized snapshot (avoid logging auth_token and large objects)
            safe_vals = {k: (None if k == 'auth_token' else v) for k, v in values.items()}
            safe_vals_str = json.dumps(safe_vals, default=str)
            app_logger.debug(f"confirm_plan_debug_snapshot chat_id={chat_id} provided_plan_id={plan_id} expected_plan_id={expected_plan_id} awaiting_confirmation={values.get('awaiting_confirmation')} state_keys={list(values.keys())}")
            # Also emit an INFO-level snapshot (human-friendly short form)
            app_logger.info(f"confirm_plan_state_snapshot chat_id={chat_id} provided_plan_id={plan_id} expected_plan_id={expected_plan_id} awaiting_confirmation={values.get('awaiting_confirmation')} safe_vals_len={len(safe_vals_str)}")
        except Exception:
            app_logger.debug("confirm_plan_debug_snapshot_failed", extra={"chat_id": chat_id})

        # If an expected plan exists but awaiting flag is not set, log informationally (race indicator)
        if expected_plan_id and not values.get('awaiting_confirmation'):
            app_logger.info("confirm_plan_expected_but_not_awaiting", extra={"chat_id": chat_id, "expected_plan_id": expected_plan_id})

        # If caller provided a plan_id, validate it against the saved plan_id regardless of awaiting flag
        if plan_id:
            if not expected_plan_id or plan_id != expected_plan_id:
                # Fallback: if graph state indicates a pending confirmation (older state without plan_id), accept and continue
                fallback_pending = (values.get('awaiting_confirmation') or values.get('pause_after_planner') or values.get('result') == 'PENDING_CONFIRMATION')
                if fallback_pending:
                    app_logger.info(f"confirm_plan_fallback_accept chat_id={chat_id} provided_plan_id={plan_id} — state missing plan_id but pending flag present")
                else:
                    try:
                        safe_vals = {k: (None if k == 'auth_token' else v) for k, v in values.items()}
                        safe_dump = json.dumps(safe_vals, default=str)[:2000]
                    except Exception:
                        safe_dump = "<failed_to_serialize_state>"
                    app_logger.warning(f"confirm_plan_plan_id_mismatch chat_id={chat_id} provided_plan_id={plan_id} expected_plan_id={expected_plan_id}")
                    app_logger.info(f"confirm_plan_mismatch_detail chat_id={chat_id} state_snapshot={safe_dump}")
                    raise HTTPException(status_code=400, detail="Invalid or missing plan_id for confirmation. The plan may have changed or already been confirmed.")
        else:
            # Backwards compatibility: require awaiting_confirmation flag when no plan_id is supplied
            if not values.get('awaiting_confirmation'):
                raise HTTPException(status_code=400, detail="No confirmation is pending for this thread")

        if not confirm:
            # If another confirm is in progress, do not allow cancel
            if values.get('confirm_in_progress'):
                app_logger.warning(f"confirm_plan_cancel_denied_in_progress chat_id={chat_id}")
                raise HTTPException(status_code=409, detail="Cannot cancel: confirmation is in progress")

            # Cancel the plan (clear paused state and plan)
            final = graph.invoke({"plan": [], "current_step": 0, "awaiting_confirmation": False, "pause_after_planner": False, "plan_id": None, "result": "Plan cancelled by user."}, config=config)
            return {"detail": "Plan cancelled.", "result": final.get("result", "")}

        # Confirm: protect against concurrent cancels by marking confirm_in_progress True first
        try:
            graph.invoke({"confirm_in_progress": True}, config=config)
            app_logger.info(f"confirm_plan_marked_in_progress chat_id={chat_id} plan_id={plan_id}")
        except Exception as e:
            app_logger.error(f"confirm_plan: failed to mark in-progress: {e}")

        # Atomically clear pause and plan_id and set resuming=True so confirm_node will skip confirmation and allow normal execution
        final = graph.invoke({"awaiting_confirmation": False, "pause_after_planner": False, "resuming": True, "plan_id": None, "confirmed_by": owner_id, "confirm_in_progress": False}, config=config)

        # Persist final assistant message (update previous assistant confirmation message if present)
        try:
            from models.chat import Message, Chart
            from utils.storage_utils import save_table_parquet

            confirmation_summary = values.get('confirmation_summary')
            if confirmation_summary:
                # Find all assistant messages in this chat that contain the confirmation summary (to guard against duplicates)
                matching_msgs = db.query(Message).filter(Message.chat_id == chat_id, Message.role == 'assistant', Message.content.ilike(f"%{confirmation_summary.strip()}%"))
                updated_msg_ids = []
                tables = final.get('tables', []) or []
                charts = final.get('charts', []) or []

                for msg in matching_msgs:
                    try:
                        msg.content = final.get('result', msg.content)
                        db.add(msg)
                        db.commit()
                        db.refresh(msg)
                        updated_msg_ids.append(str(msg.id))

                        # Save tables for this message
                        for idx, table in enumerate(tables):
                            try:
                                save_table_parquet(table.get('rows', []), table.get('headers', []), str(msg.id), idx)
                            except Exception as e:
                                app_logger.error(f"confirm_plan: failed to save table {idx} for message {msg.id}: {e}")

                        # Save charts for this message
                        for chart in charts:
                            try:
                                chart_model = Chart(id=str(uuid.uuid4()), message_id=str(msg.id), owner_id=owner_id, title=chart.get('title', 'Generated Chart'), spec=chart.get('spec', {}))
                                db.add(chart_model)
                            except Exception as e:
                                app_logger.error(f"confirm_plan: failed to save chart for message {msg.id}: {e}")
                        db.commit()
                    except Exception as e:
                        app_logger.error(f"confirm_plan: failed to update message {msg.id}: {e}")

                app_logger.info("confirm_plan: updated_messages", extra={"chat_id": chat_id, "updated_msg_ids": updated_msg_ids})

        except Exception as e:
            app_logger.exception(f"confirm_plan_postupdate_failed: {e}")

        return {"content": final.get("result", ""), "tables": final.get("tables", []), "charts": final.get("charts", [])}

    except HTTPException:
        raise
    except Exception as e:
        app_logger.exception("confirm_plan_failed")
        raise HTTPException(status_code=500, detail=f"Confirm plan failed: {str(e)}")
