from typing import TypedDict, Any, List, Optional
from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain.chains import create_sql_query_chain
from langchain.prompts import PromptTemplate
from langgraph.graph import StateGraph, END
from core.config import settings
from sqlalchemy import create_engine
from core.logging_config import app_logger
from sqlalchemy import text
import re
from core.templates.agent_templates import template, viz_template, summary_template
import json
# from utils.export_utils import save_dataframe_to_excel (Removed)

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

# Visualization Prompt

viz_prompt = PromptTemplate.from_template(viz_template)

# Define State
class GraphState(TypedDict):
    question: str
    query: str
    result: str # Formatting result or error message
    tables: Optional[List[dict]] = None # List of table data
    charts: Optional[List[dict]] = None # List of chart specs
    owner_id: str # User ID for secure export naming

# Node 1: Generate Query
def generate_query(state: GraphState):
    question = state["question"]
    try:
        query = sql_chain.invoke({"question": question})
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
    
    try:
        app_logger.info("generate_viz: calling LLM for chart config")
        response = viz_chain.invoke({"columns_sample": columns_sample_str, "input": question})
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
    
    # Simple heuristic to avoid LLM call if error or empty
    if not tables and not charts:
        # If NO_SQL, proceed to generate greeting. Otherwise return error/empty result.
        if query == "NO_SQL":
             pass 
        else:
            return {"result": state.get("result", "No data found.")}
        
    summary_chain = summary_prompt | llm
    try:
        response = summary_chain.invoke({
            "question": question,
            "query": query,
            "num_rows": num_rows,
            "has_chart": has_chart
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
builder.add_node("generate_query", generate_query)
builder.add_node("execute_format", execute_and_format)
builder.add_node("generate_viz", generate_viz)
builder.add_node("generate_summary", generate_summary)

builder.set_entry_point("generate_query")
builder.add_edge("generate_query", "execute_format")
builder.add_edge("execute_format", "generate_viz")
builder.add_edge("generate_viz", "generate_summary")
builder.add_edge("generate_summary", END)

graph = builder.compile()

def run_agent(query: str, owner_id: str):
    """
    Executes the pure SQL generation -> Execution pipeline.
    Returns a dict with 'content' and 'tables'
    """
    app_logger.info(f"run_agent (SQL mode): query='{query}' owner_id='{owner_id}'")
    try:
        final_state = graph.invoke({"question": query, "owner_id": owner_id})
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
