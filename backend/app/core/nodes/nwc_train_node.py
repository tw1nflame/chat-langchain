import json
import re
import os
import httpx
from datetime import datetime
from core.config import settings
from core.logging_config import app_logger
from core.nodes.shared_resources import llm

# Node: Call NWC Train Service
def call_nwc_train(state: dict):
    """Upload training data and request forecast training/prediction from the external NWC service.

    Description for planner/LLM summary:
    - Purpose: using an uploaded file and extracted parameters (pipeline, items, date), call the external NWC
      training API to start a training/prediction task.
    - Inputs:
      - state["files"]: list of uploaded files (expects an Excel file).
      - state["auth_token"]: bearer token to call NWC service.
      - state["question"] and state["chat_history"]: used to extract pipeline/items/date via LLM.
    - Outputs: {"result": <message>} — success or error text including task_id or API error details.
    - Side effects: uploads file to an external service to start a long-running task. May return 409 if a task is already running.
    - Notes for plan confirmation: Make it clear that this step will use the uploaded file and will start a remote job (asynchronous). The UI should present task id and possible warnings to the user.
    """
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
       - Check the Current Request for specific items involved (e.g. "Торговая КЗ", "Прочая ДЗ").
       - Example: If history has "Forecast for Item A" and current request is "base", return ["Item A"].
       - Example: If request is "base for Торговая КЗ", return ["Торговая КЗ"].
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