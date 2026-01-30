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
