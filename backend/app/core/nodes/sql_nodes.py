from typing import TypedDict, Any, List, Optional
import re
import json
from datetime import datetime
from langchain.prompts import PromptTemplate
from sqlalchemy import text
from core.templates.agent_templates import template
from core.logging_config import app_logger
from core.nodes.shared_resources import llm, engine, db, create_sql_chain

# Define custom prompt to avoid Markdown
prompt = PromptTemplate.from_template(template)

# Create the SQL generation chain (using shared resources)
sql_chain = create_sql_chain(prompt, k=50)


# Node: Generate Query
def generate_query(state: dict):
    """Generate SQL for the user's question.

    Description for planner/LLM summary:
    - Purpose: analyze the user's natural language `question` (and recent `chat_history`) and generate
      a precise SQL query that will be executed against the agent database.
    - Inputs:
      - state["question"] (string): the user's request in natural language.
      - state["chat_history"] (list[string], optional): recent conversation context to help disambiguate the request.
    - Outputs:
      - returns {"query": <sql_string>} on success.
      - returns {"query": "ERROR", "result": <error message>} on generation failure.
    - Side effects: none (only generates SQL, does not execute it).
    - Notes for plan confirmation: The description should explicitly state that the system will run a SQL generation step which produces a SQL string; the next step could be executing that SQL against the database and returning tabular results.
    """
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


# Node: Execute and Format
def execute_and_format(state: dict):
    """Выполняет SQL-запрос против базы данных и возвращает реальные данные, пригодные для построения графиков и подготовки краткого итогового отчёта.

    Description for planner/LLM summary:
    - Purpose: take a SQL `query` produced by `generate_query` (or NWC nodes), execute it against the
      configured database, and return structured table data and/or a short human-readable message.
    - Inputs:
      - state["query"] (string): SQL statement to execute. Special value: "NO_SQL" means skip execution.
    - Outputs:
      - On success: {"result": <message>, "tables": [ {"headers": [...], "rows": [[...]], "title": ... } ] }
      - If no rows: {"result": "Запрос выполнен успешно, но данных не найдено.", "tables": []}
      - On SQL error: {"result": "Ошибка выполнения запроса: <error>\n\nQuery: `<query>`"}
    - Side effects: reads from the database; no persistent writes.
    - Notes for plan confirmation: Should describe that actual data will be retrieved and that large-result warnings or empty results are possible. For analytical flows, this node is expected to execute queries that retrieve the LAST 12 MONTHS of data (or the window chosen by the planner) and return results formatted for chart generation and concise summarization.
    """
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
