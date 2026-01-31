from typing import TypedDict, Any, List, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from core.logging_config import app_logger
import json
from core.nodes.nwc_node import generate_nwc_query, nwc_analyze, nwc_show_forecast
from core.nodes.rag_node import update_rag_node, retrieve_rag_node
from core.nodes.sql_nodes import generate_query, execute_and_format
from core.nodes.planner_node import planner
from core.nodes.nwc_train_node import call_nwc_train
from core.nodes.viz_summary_nodes import generate_viz, generate_summary

# Define State
class GraphState(TypedDict):
    question: str
    
    # Planner state
    plan: Optional[List[dict]] 
    current_step: int
    next_action: Optional[str]

    # Execution state
    query: Optional[str]
    result: Optional[str] # Formatting result or error message
    tables: Optional[List[dict]] # List of table data
    charts: Optional[List[dict]] # List of chart specs
    owner_id: str # User ID for secure export naming

    # Pause/confirmation state
    awaiting_confirmation: Optional[bool]
    confirmation_summary: Optional[str]
    pause_after_planner: Optional[bool]
    plan_id: Optional[str]
    resuming: Optional[bool]
    confirmed_by: Optional[str]
    # Indicate that a confirm action is currently being processed (prevents concurrent cancel)
    confirm_in_progress: Optional[bool]
    # Indicate this is a temporary/stateless session (skip confirmation when True)
    temporary_session: Optional[bool]
    
    # Extended context
    auth_token: Optional[str]
    files: Optional[List[dict]] # List of uploaded files info
    chat_history: Optional[List[str]] # Simple history of questions
    nwc_info: Optional[dict] # Info about NWC article and model used
    rag_context: Optional[str] # Retrieved content from RAG


# Node: Executor
def executor(state: GraphState):
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    
    if current_step >= len(plan):
        app_logger.info("Executor: Plan finished")
        return {"next_action": "end"}
        
    step = plan[current_step]
    action = step.get("action")
    
    app_logger.info(f"Executor step {current_step}: {action}")
    return {"next_action": action}

# Node: Action Router
def action_router(state: GraphState):
    return state.get("next_action", "end")

# Node: Next Step
def next_step(state: GraphState):
    return {
        "current_step": state["current_step"] + 1
    }


# Build Graph
builder = StateGraph(GraphState)

# Add nodes
builder.add_node("planner", planner)
builder.add_node("confirm_plan", __import__("core.nodes.confirm_node", fromlist=["confirm_plan"]).confirm_plan)
builder.add_node("executor", executor)
builder.add_node("next_step", next_step)
builder.add_node("generate_query", generate_query)
builder.add_node("nwc_query_generator", generate_nwc_query)
builder.add_node("nwc_analyze", nwc_analyze)
builder.add_node("nwc_show_forecast", nwc_show_forecast)
builder.add_node("execute_format", execute_and_format)
builder.add_node("generate_viz", generate_viz)
builder.add_node("call_nwc_train", call_nwc_train)
builder.add_node("generate_summary", generate_summary)
builder.add_node("update_rag", update_rag_node)
builder.add_node("retrieve_rag", retrieve_rag_node)

# Define flow
builder.set_entry_point("planner")

# After planning, request confirmation (confirm_plan). confirm_plan will typically pause the flow by
# returning awaiting_confirmation=True unless the session is temporary/stateless.
builder.add_edge("planner", "confirm_plan")

# confirm_plan decides if we should proceed or wait for user confirmation.
# Use conditional edges so confirm_node can control whether to go to executor.
builder.add_conditional_edges(
    "confirm_plan",
    lambda state: state.get("next_action", "WAIT"),
    {
        "CONFIRMED": "executor",
        "WAIT": END,
        "end": END
    }
)

builder.add_conditional_edges(
    "executor",
    action_router,
    {
        "GENERATE_SQL": "generate_query",
        "GENERATE_NWC_SQL": "nwc_query_generator",
        "NWC_ANALYZE": "nwc_analyze",
        "NWC_SHOW_FORECAST": "nwc_show_forecast",
        "EXECUTE_SQL": "execute_format",
        "GENERATE_VIZ": "generate_viz",
        "TRAIN_MODEL": "call_nwc_train",
        "UPDATE_RAG": "update_rag",
        "RETRIEVE_RAG": "retrieve_rag",
        "SUMMARIZE": "generate_summary",
        "end": END
    }
)

# After each action, go to next_step (except Summary which ends the flow)
builder.add_edge("generate_query", "next_step")
builder.add_edge("nwc_query_generator", "next_step")
builder.add_edge("nwc_analyze", "next_step")
builder.add_edge("nwc_show_forecast", "next_step")
builder.add_edge("execute_format", "next_step")
builder.add_edge("generate_viz", "next_step")
builder.add_edge("call_nwc_train", "next_step")
builder.add_edge("update_rag", "next_step")
builder.add_edge("retrieve_rag", "next_step")
builder.add_edge("generate_summary", END)

builder.add_edge("next_step", "executor")

# Initialize Memory Checkpointer
memory = MemorySaver()

# Compile with checkpointer
graph = builder.compile(checkpointer=memory)

def run_agent(query: str, owner_id: str, auth_token: str = None, files: List[dict] = None, thread_id: str = None, history: List[str] = None):
    """
    Executes the Planner -> Executor pipeline.
    Returns a dict with 'content' and 'tables'
    """
    app_logger.info(f"run_agent (Planner mode): query='{query}' owner_id='{owner_id}' thread_id='{thread_id}'")
    # Debug: snapshot of incoming run_agent parameters (no tokens)
    try:
        app_logger.debug("run_agent_snapshot", extra={
            "thread_id": thread_id,
            "owner_id": owner_id,
            "history_provided": history is not None,
            "temporary_session_flag": False,
        })
    except Exception:
        app_logger.debug("run_agent_snapshot_failed")

    try:
        # Prepare inputs
        inputs = {
            "question": query,
            "owner_id": owner_id,
            "auth_token": auth_token,
            # Reset temporary execution state
            "current_step": 0,
            "plan": [],
            "query": None,
            "result": None,
            "tables": [],
            "charts": []
        }
        
        if files:
            inputs["files"] = files
            
        # Config for thread
        config = {"configurable": {"thread_id": thread_id}} if thread_id else {"configurable": {"thread_id": owner_id}} 
        
        # Handle History
        # If explicit history provided (Stateless/Temporary mode), use it + query
        if history is not None:
             inputs["chat_history"] = history + [query]
             # Indicate this is a temporary/stateless session: skip confirmation
             inputs["temporary_session"] = True
        # Otherwise, rely on MemorySaver state if thread_id exists
        elif thread_id:
             current_state = graph.get_state(config)
             if current_state and current_state.values:
                  current_history = current_state.values.get("chat_history", [])
                  new_history = current_history + [query]
                  inputs["chat_history"] = new_history
             else:
                  inputs["chat_history"] = [query]
        else:
             inputs["chat_history"] = [query]

        # If this is a temporary/stateless session, run full graph immediately
        if inputs.get("temporary_session"):
            app_logger.debug("temporary_session_full_graph_invoke", extra={"thread_id": thread_id})
            final_state = graph.invoke(inputs, config=config)
            app_logger.debug("temporary_session_full_graph_result", extra={"thread_id": thread_id, "final_state_keys": list(final_state.keys())})
            return {
                "content": final_state.get("result", ""),
                "tables": final_state.get("tables", []),
                "charts": final_state.get("charts", []),
                "awaiting_confirmation": final_state.get("awaiting_confirmation", False),
                "confirmation_summary": final_state.get("confirmation_summary")
            }

        # Persistent session: run planner only and pause for confirmation before executing the plan
        try:
            app_logger.debug("run_agent_calling_planner", extra={"thread_id": thread_id})
            planner_result = planner(inputs.copy())
            plan = planner_result.get("plan", [])
            app_logger.debug("planner_direct_result", extra={"thread_id": thread_id, "plan_len": len(plan), "plan_preview": str(plan)[:400]})
        except Exception as e:
            app_logger.error(f"Planner direct call failed: {e}")
            # Fallback to running full graph
            app_logger.debug("run_agent_falling_back_to_full_graph", extra={"thread_id": thread_id})
            final_state = graph.invoke(inputs, config=config)
            app_logger.debug("run_agent_full_graph_result", extra={"thread_id": thread_id, "final_state_keys": list(final_state.keys())})
            return {
                "content": final_state.get("result", ""),
                "tables": final_state.get("tables", []),
                "charts": final_state.get("charts", []),
                "awaiting_confirmation": final_state.get("awaiting_confirmation", False),
                "confirmation_summary": final_state.get("confirmation_summary")
            }

        # If no plan or trivial plan, just execute
        if not plan:
            final_state = graph.invoke(inputs, config=config)
            return {
                "content": final_state.get("result", ""),
                "tables": final_state.get("tables", []),
                "charts": final_state.get("charts", []),
                "awaiting_confirmation": final_state.get("awaiting_confirmation", False),
                "confirmation_summary": final_state.get("confirmation_summary")
            }

        # Generate a unique plan_id and confirmation summary using confirm_node logic (LLM)
        import uuid as _uuid
        plan_id = str(_uuid.uuid4())
        # Generate confirmation summary using confirm_node (direct call to avoid invoking the whole graph)
        from core.nodes.confirm_node import confirm_plan as confirm_fn
        confirm_out = confirm_fn({**inputs, "plan": plan, "plan_id": plan_id})
        app_logger.debug("confirm_fn_output", extra={"thread_id": thread_id, "plan_id": plan_id, "confirm_out_keys": list(confirm_out.keys()), "confirm_out_preview": str(confirm_out)[:500]})

        # If confirm_node decided that confirmation is not needed, just run full graph
        if confirm_out.get("plan_confirmed"):
            app_logger.info("confirm_item_says_plan_confirmed_running_full_graph", extra={"thread_id": thread_id, "plan_id": plan_id})
            inputs["plan"] = plan
            final_state = graph.invoke(inputs, config=config)
            app_logger.debug("graph_full_run_after_plan_confirmed", extra={"thread_id": thread_id, "final_state_keys": list(final_state.keys())})
            return {
                "content": final_state.get("result", ""),
                "tables": final_state.get("tables", []),
                "charts": final_state.get("charts", []),
                "awaiting_confirmation": final_state.get("awaiting_confirmation", False),
                "confirmation_summary": final_state.get("confirmation_summary")
            }

        # Persist the plan + confirmation summary into the graph checkpointer and pause execution
        confirmation_summary = confirm_out.get("confirmation_summary")
        inputs["plan"] = plan
        inputs["current_step"] = 0
        inputs["awaiting_confirmation"] = True
        inputs["confirmation_summary"] = confirmation_summary
        inputs["pause_after_planner"] = True
        inputs["plan_id"] = plan_id

        # Log what we are persisting to the checkpointer
        app_logger.debug("persisting_paused_plan", extra={"thread_id": thread_id, "plan_id": plan_id, "awaiting_confirmation": True, "plan_len": len(plan)})
        # Emit INFO so this is visible with default logging
        try:
            app_logger.info("persisting_paused_plan_info", extra={"thread_id": thread_id, "plan_id": plan_id, "plan_len": len(plan)})
        except Exception:
            app_logger.debug("persisting_paused_plan_info_failed", extra={"thread_id": thread_id})
        # Invoke graph to persist state; confirm_node will see pause_after_planner and end execution
        final_state = graph.invoke(inputs, config=config)
        app_logger.debug("persisted_paused_plan_result", extra={"thread_id": thread_id, "final_state_keys": list(final_state.keys())})
        try:
            app_logger.info("persisted_paused_plan", extra={"thread_id": thread_id, "plan_id": plan_id, "final_state_keys": list(final_state.keys())})
        except Exception:
            app_logger.debug("persisted_paused_plan_info_failed", extra={"thread_id": thread_id})
        # Return pending confirmation to caller (without executing plan)
        return {
            "content": confirmation_summary or "Пожалуйста, подтвердите план",
            "tables": [],
            "charts": [],
            "awaiting_confirmation": True,
            "confirmation_summary": confirmation_summary,
            "plan_id": plan_id
        }
    except Exception as e:
        app_logger.error(f"run_agent exception: {e}", exc_info=True)
        return {
            "content": f"System Error: {str(e)}",
            "tables": [],
            "charts": []
        }
