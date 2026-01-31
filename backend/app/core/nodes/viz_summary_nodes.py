from typing import TypedDict, Any, List, Optional
import json
import re
from datetime import datetime
from langchain.prompts import PromptTemplate
from core.templates.agent_templates import viz_template, summary_template
from core.config import settings
from core.logging_config import app_logger
from core.nodes.shared_resources import llm

viz_prompt = PromptTemplate.from_template(viz_template)
summary_prompt = PromptTemplate.from_template(summary_template)

# Node: Generate Visualization Config
def generate_viz(state: dict):
    """Генерирует спецификацию графиков (временные ряды за последний год) для визуализации трендов и аномалий, пригодную для итогового отчёта.

    Description for planner/LLM summary:
    - Purpose: inspect the first result table (`state["tables"][0]`) and the user's `question`, and produce
      a JSON chart specification (or `NO_CHART` signal) suitable for frontend rendering.
    - Inputs:
      - state["tables"]: list of tables with headers and rows.
      - state["question"]: original user query to infer chart intent.
    - Outputs: {"charts": [ {"title": ..., "spec": <chart-spec-json> } ] } or {"charts": []} when no chart is applicable.
    - Side effects: none.
    - Notes for plan confirmation: Emphasize that this step creates a visualization spec (not the image) and that frontend will render the chart from the spec. For analytical requests, prefer TIME-SERIES charts covering the LAST 12 MONTHS (or the window provided by the planner), highlight trends and anomalies, and ensure the chart is suitable for use in the concise final report.
    """
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


# Node: Generate Summary
def generate_summary(state: dict):
    """Формирует краткий итоговый отчёт с ключевыми выводами (1-2 предложения) на основе данных и графиков.

    Description for planner/LLM summary:
    - Purpose: given the executed SQL, returned tables, charts, and optional RAG/NWC context, produce
      a concise and helpful natural-language summary for the user.
    - Inputs:
      - state["question"]: original user question
      - state["query"]: SQL executed (if any)
      - state["tables"] and state["charts"]: data produced by previous steps
      - state["nwc_info"], state["rag_context"]: optional contextual info
    - Outputs: {"result": <summary string>} — the natural-language answer to present to the user.
    - Side effects: none.
    - Notes for plan confirmation: the summary explicitly refers to what was executed (query/chart generation/training) and any limitations or missing context. For analytical requests, produce a very concise final report (1-2 sentences) that highlights key conclusions and, if appropriate, a short recommendation; avoid long per-article enumerations and instead rely on the accompanying table and charts for details.
    """
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
    rag_info = f"\n\nKnowledge Base Context (IMPORTANT: do NOT invent or assume facts. Use only this content; if it is missing or unclear, explicitly say so and ask for clarification):\n{rag_context}" if rag_context else ""

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
