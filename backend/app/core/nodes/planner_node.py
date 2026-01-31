from typing import TypedDict, Any, List, Optional
import json
import re
from datetime import datetime
from langchain.prompts import PromptTemplate
from core.templates.agent_templates import planner_template
from core.config import settings
from core.logging_config import app_logger
import os
import httpx
from core.nodes.shared_resources import llm
from core.nodes.nwc_train_node import call_nwc_train

planner_prompt = PromptTemplate.from_template(planner_template)

# Node: Planner
def planner(state: dict):
    """Plan a sequence of high-level actions to satisfy the user's question.

    Description for planner/LLM summary:
    - Purpose: analyze the user's `question`, `files`, and `chat_history` and return an ordered `plan` (list of
      action dicts) describing which nodes to run and in which order.
    - Outputs: {"plan": [...], "current_step": 0}
      - Each plan step is a dict with at least the key `action` (e.g., "GENERATE_SQL", "EXECUTE_SQL", "SUMMARIZE").
    - Side effects: none (planner only suggests actions; it does not perform them).
    - Notes for plan confirmation: The planner's output will be used to generate a human-readable description of the intended actions
      by collecting docstrings from each referenced node and asking the LLM to summarize "what will happen" before execution.
    """
    app_logger.info("Planner: generating plan")
    try:
        app_logger.debug("planner_called", extra={
            "question": state.get("question", "" )[:200],
            "history_len": len(state.get("chat_history", [])),
            "files_count": len(state.get("files", []) or []),
        })
    except Exception:
        app_logger.debug("planner_called_snapshot_failed")

    # If a plan already exists in state (persisted by controller), skip re-planning.
    if state.get("plan"):
        existing = state.get("plan")
        app_logger.info("Planner: existing plan found in state, skipping re-planning", extra={"plan_len": len(existing), "current_step": state.get("current_step", 0)})
        return {"plan": state.get("plan"), "current_step": state.get("current_step", 0)}

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


# Call NWC Train moved to core.nodes.nwc_train_node
# See: core/nodes/nwc_train_node.py
