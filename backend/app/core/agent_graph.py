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

builder.add_edge("planner", "executor")

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

        final_state = graph.invoke(inputs, config=config)
        return {
            "content": final_state.get("result", ""),
            "tables": final_state.get("tables", []),
            "charts": final_state.get("charts", [])
        }
    except Exception as e:
        app_logger.error(f"run_agent exception: {e}", exc_info=True)
        return {
            "content": f"System Error: {str(e)}",
            "tables": [],
            "charts": []
        }
