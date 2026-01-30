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


# Call NWC Train moved to core.nodes.nwc_train_node
# See: core/nodes/nwc_train_node.py
