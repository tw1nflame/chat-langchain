from typing import TypedDict, Any, List, Optional
from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain.chains import create_sql_query_chain
from langchain.prompts import PromptTemplate
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from core.config import settings
from sqlalchemy import create_engine
from core.logging_config import app_logger
from sqlalchemy import text
import re
from datetime import datetime
from core.templates.agent_templates import template, viz_template, summary_template, planner_template
import os
import json
# from utils.export_utils import save_dataframe_to_excel (Removed)

import httpx
from core.nodes.nwc_node import generate_nwc_query
from core.nodes.rag_node import update_rag_node, retrieve_rag_node

# Initialize Database
# Allow agent to query a different database than the main app storage
connect_args = {}
if settings.agent_database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.agent_database_url, connect_args=connect_args)
db = SQLDatabase(engine)

# Initialize LLM
llm = ChatOpenAI(
    api_key=settings.deepseek_api_key or "dummy_key",
    base_url=settings.deepseek_base_url,
    model=settings.deepseek_model,
    temperature=0
)

# Define custom prompt to avoid Markdown

prompt = PromptTemplate.from_template(template)

# Create the SQL generation chain
sql_chain = create_sql_query_chain(llm, db, prompt=prompt, k=50)

# Planner Prompt
planner_prompt = PromptTemplate.from_template(planner_template)

# Visualization Prompt

viz_prompt = PromptTemplate.from_template(viz_template)

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


# Node: Planner
def planner(state: GraphState):
    app_logger.info("Planner: generating plan")
    
    # Include history in context if available (simple concatenation for now)
    history = state.get("chat_history", [])
    context_str = ""
    if history:
        # Keep last 5 messages
        recent = history[-5:]
        context_str = f"\nRecent History: {json.dumps(recent)}\n"
        
    files = state.get("files", [])
    files_context = ""
    if files:
        file_names = [f.get("name") for f in files]
        files_context = f"\nFiles Attached: {json.dumps(file_names)}\n"

    planner_chain = planner_prompt | llm
    try:
        response = planner_chain.invoke({"question": f"{state['question']} {context_str} {files_context}"})
        # Try to parse JSON from the response
        content = response.content.strip()
        
        # Clean up code blocks if present
        match = re.search(r"```json(.*?)```", content, re.DOTALL | re.IGNORECASE)
        if match:
             content = match.group(1).strip()
        elif content.startswith("```"):
             match_generic = re.search(r"```(.*?)```", content, re.DOTALL)
             if match_generic:
                 content = match_generic.group(1).strip()
                 
        plan = json.loads(content)
        app_logger.info(f"Planner plan generated: {plan}")
        return {
            "plan": plan,
            "current_step": 0
        }
    except Exception as e:
        app_logger.error(f"Planner failed: {e}")
        # Fallback plan for errors
        return {
            "plan": [{"action": "GENERATE_SQL"}, {"action": "EXECUTE_SQL"}, {"action": "SUMMARIZE"}],
            "current_step": 0
        }

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

# Node: Call NWC Train Service
def call_nwc_train(state: GraphState):
    question = state["question"]
    auth_token = state.get("auth_token")
    files = state.get("files", [])
    
    app_logger.info(f"call_nwc_train: processing. Question: '{question[:50]}...'")
    
    if not auth_token:
        app_logger.warning("call_nwc_train: Missing auth_token")
        return {"result": "Error: Authentication token missing. Cannot call NWC service."}
        
    if not files:
        app_logger.warning("call_nwc_train: No files provided")
        return {"result": "Error: No file provided for training. Please upload an Excel file."}
        
    # Prefer the most recent file
    target_file = files[-1]
    file_path = target_file.get("path")
    app_logger.info(f"call_nwc_train: using file '{target_file.get('name')}' at '{file_path}'")
    
    if not file_path or not os.path.exists(file_path):
         app_logger.error(f"call_nwc_train: File path does not exist: {file_path}")
         return {"result": f"Error: File not found on server ({target_file.get('name')})."}

    # Use LLM to extract parameters from question
    # We need: pipeline (BASE/BASE+), items (all/specific), date
    
    # Include history for context
    history = state.get("chat_history", [])
    # dumps with ensure_ascii=False to keep Russian characters readable
    history_str = json.dumps(history[-5:], ensure_ascii=False) if history else "[]"
    
    app_logger.info(f"call_nwc_train: extracting params. History: {history_str}, Question: {question}")

    extraction_prompt = f"""
    Analyze the user request and conversation history to extract NWC training parameters.
    
    Context (previous messages): {history_str}
    Current Request: "{question}"
    
    Task: Extract 1) Pipeline type, 2) Items to predict, 3) Date.
    
    1. Pipeline:
       - Check Request first for specific pipeline names ('BASE', 'BASE+', 'AUTOARIMA'...).
       - IMPORTANT: "base" (case-insensitive) IS A VALID PIPELINE NAME. If the user types "base", return "BASE".
       - If present in Request, use it.
       - If NOT in Request, return "MISSING" (do not infer from history unless user says "retry", "run it", "same settings" or similar).
       
    2. Items:
       - List of strings representing specific items/articles/categories.
       - CRITICAL: Check Context for items mentioned in previous turns (e.g., "по статье X", "for item Y").
       - Example: If history has "Forecast for Item A" and current request is "base", return ["Item A"].
       - Return ["__all__"] ONLY if "all"/"everything" is explicitly requested or NO specific items exist in Request OR Context.
       
    3. Date:
       - YYYY-MM-DD. Default to {datetime.now().strftime('%Y-%m-01')}.
    
    Return valid JSON ONLY: {{ "pipeline": "...", "items": [...], "date": "..." }}
    """
    
    try:
        app_logger.info("call_nwc_train: invoking LLM for param extraction")
        response = llm.invoke(extraction_prompt)
        content = response.content.strip()
        app_logger.info(f"call_nwc_train: LLM raw response: {content}")
        
        match = re.search(r"```json(.*?)```", content, re.DOTALL | re.IGNORECASE)
        if match:
             content = match.group(1).strip()
        elif content.startswith("```"):
             content = content.strip("`")
             
        params = json.loads(content)
        app_logger.info(f"call_nwc_train: parsed params: {params}")
        
        # Check for missing pipeline
        if params.get("pipeline") == "MISSING":
             app_logger.info("call_nwc_train: pipeline MISSING, aborting train")
             return {"result": "Пожалуйста, уточните тип прогноза: BASE или BASE+?"}

        # Prepare request
        url = f"{settings.nwc_service_url}/train/"
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Fixed strftime directive: %0 is invalid, used hardcoded -01
        default_date = datetime.now().strftime('%Y-%m-01')
        
        data = {
            "pipeline": params.get("pipeline", "BASE"),
            "items": json.dumps(params.get("items", ["__all__"])),
            "date": params.get("date", default_date),
        }
        
        app_logger.info(f"Sending NWC Request: URL={url} Data={data} File={target_file.get('name')}")
        
        # Send Request
        with open(file_path, "rb") as f:
            files_payload = {"data_file": (target_file.get("name"), f, target_file.get("type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))}
            
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, headers=headers, data=data, files=files_payload)
                
            if resp.status_code == 200:
                resp_json = resp.json()
                task_id = resp_json.get("task_id")
                warnings = resp_json.get("warnings")
                
                msg = f"Training/Prediction started successfully via NWC service.\nTask ID: {task_id}\nPipeline: {data['pipeline']}\nDate: {data['date']}"
                
                if warnings:
                    msg += f"\n\nWARNINGS: {json.dumps(warnings, ensure_ascii=False)}"
                    
                app_logger.info(f"call_nwc_train: Success! task_id={task_id}, warnings={warnings}")
                return {"result": msg}
            elif resp.status_code == 409:
                app_logger.warning("call_nwc_train: Conflict (409) - Task already running")
                return {"result": "Training/Prediction failed: A task is already running. Please wait for it to finish."}
            else:
                app_logger.error(f"call_nwc_train: API Error {resp.status_code}: {resp.text}")
                return {"result": f"NWC Service Error ({resp.status_code}): {resp.text}"}
                
    except Exception as e:
        app_logger.exception(f"NWC Train Error")
        return {"result": f"Error calling NWC service: {str(e)}"}


# Node: Action Router
def action_router(state: GraphState):
    return state.get("next_action", "end")

# Node: Next Step
def next_step(state: GraphState):
    return {
        "current_step": state["current_step"] + 1
    }

# Node 1: Generate Query
def generate_query(state: GraphState):
    question = state["question"]
    history = state.get("chat_history", [])
    history_str = json.dumps(history[-5:], ensure_ascii=False) if history else "[]"
    try:
        query = sql_chain.invoke({"question": question, "history": history_str})
        # Clean up markdown if present
        # robust regex extraction for ```sql ... ``` blocks
        match = re.search(r"```sql(.*?)```", query, re.DOTALL | re.IGNORECASE)
        if match:
             cleaned_query = match.group(1)
        else:
             # Check for generic block
             match_generic = re.search(r"```(.*?)```", query, re.DOTALL)
             if match_generic:
                  cleaned_query = match_generic.group(1)
             else:
                  cleaned_query = query

        # Final trimming
        cleaned_query = cleaned_query.strip()
        
        # Clean up common prefixes like "SQLQuery:"
        if cleaned_query.lower().startswith("sqlquery:"):
            cleaned_query = cleaned_query[9:].strip()
        
        return {"query": cleaned_query}
    except Exception as e:
        app_logger.error(f"Error generating SQL: {e}")
        return {"query": "ERROR", "result": f"Failed to generate SQL: {str(e)}"}

# Node 2: Execute and Format
def execute_and_format(state: GraphState):
    query = state.get("query")
    if not query or query == "ERROR":
        return {"result": state.get("result", "Invalid query generation")}
    
    if query == "NO_SQL":
        # Skip execution, clear old tables/charts
        return {"result": "NO_SQL_SKIPPED", "tables": [], "charts": []}

    app_logger.info(f"Executing SQL: {query}")
    try:
        # We use the raw sqlalchemy engine for direct control over results
        with engine.connect() as connection:
            result = connection.execute(text(query))
            rows = result.fetchall()
            keys = list(result.keys())
            
            if not rows:
                return {"result": "Запрос выполнен успешно, но данных не найдено.", "tables": []}
            
            # Prepare rows as list of lists (convert values to strings/native types)
            # Keeping native types for Excel, converting to string for display might be handled by frontend or json encoder
            # For simplicity, let's keep native or reasonable string repr
            data_rows = []
            for row in rows:
                data_rows.append(list(row))
            
            # Construct Table Data (Raw, for API to handle storage)
            # We no longer save to Excel here. API will save to Parquet.
            table_data = {
                "headers": keys,
                "rows": [ [str(cell) for cell in row] for row in data_rows], 
                "title": "Результат запроса"
            }
            
            return {
                "result": "Вот данные по вашему запросу:", # Or we can omit text if we show table
                "tables": [table_data]
            }
            
    except Exception as e:
        app_logger.error(f"Error executing SQL: {e}")
        return {"result": f"Ошибка выполнения запроса: {str(e)}\n\nQuery: `{query}`"}

# Node 3: Generate Visualization Config
def generate_viz(state: GraphState):
    app_logger.info("generate_viz: processing")
    tables = state.get("tables", [])
    if not tables:
        app_logger.info("generate_viz: no tables found, skipping")
        return {"charts": []}
    
    # Use headers and first row sample
    target_table = tables[0]
    headers = target_table["headers"]
    first_row = target_table["rows"][0] if target_table["rows"] else []
    
    # Format schema description
    if not first_row:
         # If no data, cannot infer types well
         columns_sample_str = ", ".join(headers)
    else:
         columns_sample_str = ", ".join([f"{h} (sample: '{v}')" for h, v in zip(headers, first_row)])
    
    question = state["question"]
    app_logger.info(f"generate_viz: derived columns_sample='{columns_sample_str}'")
    
    # Create chain
    viz_chain = viz_prompt | llm
    
    history = state.get("chat_history", [])
    history_str = json.dumps(history[-5:], ensure_ascii=False) if history else "[]"
    
    try:
        app_logger.info("generate_viz: calling LLM for chart config")
        response = viz_chain.invoke({"columns_sample": columns_sample_str, "input": question, "history": history_str})
        viz_json = response.content.strip()
        app_logger.info(f"generate_viz: LLM raw response: {viz_json}")
        
        # Cleanup code blocks
        match = re.search(r"```json(.*?)```", viz_json, re.DOTALL | re.IGNORECASE)
        if match:
             viz_json = match.group(1).strip()
        elif viz_json.startswith("```"): # Generic block
             match_generic = re.search(r"```(.*?)```", viz_json, re.DOTALL)
             if match_generic:
                 viz_json = match_generic.group(1).strip()

        if "NO_CHART" in viz_json:
            app_logger.info("generate_viz: LLM returned NO_CHART")
            return {"charts": []}
        
        parsed_json = json.loads(viz_json)
        app_logger.info("generate_viz: valid JSON parsed")
        # Wrap in a list and object structure
        return {"charts": [{"title": "Generated Chart", "spec": parsed_json}]}
    except Exception as e:
        app_logger.error(f"Viz Error: {e}")
        return {"charts": []}

# Summary Prompt

summary_prompt = PromptTemplate.from_template(summary_template)

# Node 4: Generate Summary
def generate_summary(state: GraphState):
    question = state["question"]
    query = state.get("query", "")
    tables = state.get("tables", [])
    charts = state.get("charts", [])
    
    num_rows = 0
    if tables and "rows" in tables[0]:
        num_rows = len(tables[0]["rows"])
    
    has_chart = "Yes" if charts else "No"
    
    # Prepare Data Preview
    data_preview = ""
    if tables and "rows" in tables[0] and "headers" in tables[0]:
        target_table = tables[0]
        headers = target_table["headers"]
        rows = target_table["rows"]
        
        # Take first 10 rows
        preview_rows = rows[:10]
        
        # Simple markdown table or csv-like format
        data_preview += f"Headers: {', '.join(headers)}\n"
        for i, row in enumerate(preview_rows):
            data_preview += f"Row {i+1}: {', '.join([str(c)[:50] for c in row])}\n"
        
        if len(rows) > 10:
            data_preview += f"... and {len(rows)-10} more rows."
    else:
        data_preview = "No data rows available."
    
    # Simple heuristic to avoid LLM call if error or empty
    if not tables and not charts:
        # If query is NO_SQL or explicitly None (meaning skipped SQL generation by planner), permit LLM summary (greeting)
        is_no_sql = (query == "NO_SQL") or (query is None)

        if is_no_sql:
             # Proceed to LLM generation (pass NO_SQL to prompt to ensure greeting behavior)
             if query is None:
                 query = "NO_SQL"
        else:
             # We had a query, but no tables/charts. Rely on previous result message.
             res = state.get("result")
             # Ensure we don't return None
             return {"result": res if res else "No data found."}
        
    summary_chain = summary_prompt | llm
    
    history = state.get("chat_history", [])
    history_str = json.dumps(history[-5:], ensure_ascii=False) if history else "[]"
    
    nwc_info = state.get("nwc_info", {})
    app_logger.info(f"generate_summary: nwc_info={nwc_info}")
    
    nwc_context = ""
    if nwc_info:
        if "config" in nwc_info:
             # Pass full config context if specific article wasn't identified
             nwc_context = f"\nNWC Configuration (Models/Pipelines): {json.dumps(nwc_info['config'], ensure_ascii=False)}"
        else:
             nwc_context = f"\nNWC Info: Used model '{nwc_info.get('model')}' (Pipeline: '{nwc_info.get('pipeline')}') for article '{nwc_info.get('article')}'."

    rag_context = state.get("rag_context", "")
    rag_info = f"\n\nKnowledge Base Context:\n{rag_context}" if rag_context else ""

    try:
        response = summary_chain.invoke({
            "question": question,
            "query": f"{query}\n{nwc_context}\n{rag_info}",
            "num_rows": num_rows,
            "has_chart": has_chart,
            "previous_result": state.get("result", ""),
            "history": history_str,
            "data_preview": data_preview
        })
        summary = response.content.strip()
        # Clean up code blocks if any
        if summary.startswith("```"):
            summary = summary.strip("`")
        return {"result": summary}
    except Exception as e:
        app_logger.error(f"Summary Error: {e}")
        return {"result": "Data retrieved successfully."}

# Build Graph
builder = StateGraph(GraphState)

# Add nodes
builder.add_node("planner", planner)
builder.add_node("executor", executor)
builder.add_node("next_step", next_step)
builder.add_node("generate_query", generate_query)
builder.add_node("nwc_query_generator", generate_nwc_query)
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
builder.add_edge("execute_format", "next_step")
builder.add_edge("generate_viz", "next_step")
builder.add_edge("call_nwc_train", "next_step")
builder.add_edge("update_rag", "next_step")
builder.add_edge("retrieve_rag", "next_step")
# Special case: The user flow suggests Summary is the end. 
# However, if planner puts SUMMARIZE in the middle (unlikely), we'd loop.
# But for now, let's treat SUMMARIZE as a terminal node as per user request (generate_summary -> END)
# Actually, the user's diagram had: generate_summary -> END.
# Let's enforce that SUMMARIZE terminates the graph regardless of plan length to match previous behavior,
# OR we can strictly follow the plan. 
# User asked: "generate_summary -> END"
builder.add_edge("generate_summary", END)

builder.add_edge("next_step", "executor")

# Initialize Memory Checkpointer
memory = MemorySaver()

# Compile with checkpointer
graph = builder.compile(checkpointer=memory)

def run_agent(query: str, owner_id: str, auth_token: str = None, files: List[dict] = None, thread_id: str = None):
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
            # Do NOT reset files or history here if we want persistence, 
            # but we need to feed new data. 
            # If files are provided, we update them.
            # If not provided, we rely on state (if checkedpointer handles merging, which TypedDict overwrite does not do for missing keys in input)
            # Actually, Graph execution with checkpointer:
            # The state retrieved from storage is merged with the input.
            # State keys NOT in input are PRESERVED.
        }
        
        if files:
            inputs["files"] = files
            
        # Manually append to history in inputs? 
        # Or rely on a reducer? TypedDict replaces.
        # So we need to read state? No, invoke receives inputs.
        # We can implement a "reducer" in GraphState, but TypedDict doesn't support it easily without Annotated.
        # Hack: We can't append to history easily without reading first or using Annotated.
        # Let's use Annotated for chat_history in a future refactor.
        # For now, to support history:
        # We will just rely on the fact that we can't easily append without Annotated.
        # However, to solve the immediate request ("keep file"), suppressing "files": [] is enough.
        
        # Config for thread
        config = {"configurable": {"thread_id": thread_id}} if thread_id else {"configurable": {"thread_id": owner_id}} # Fallback to owner_id if no thread
        
        # But wait, if I want to append to history, I can't do it blindly.
        # I will update the graph state definition to use Annotated for correct appending? 
        # Or just read the current state?
        if thread_id:
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
