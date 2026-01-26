from typing import Any, Dict, List, Optional
import httpx
import json
import re
import logging
import yaml
from sqlalchemy import create_engine
from langchain_community.utilities import SQLDatabase
from langchain_openai import ChatOpenAI
from langchain.chains import create_sql_query_chain
from langchain.prompts import PromptTemplate
from core.config import settings

# Logger
app_logger = logging.getLogger("uvicorn")

# Re-initialize DB and LLM (to keep module self-contained and avoid circular imports)
connect_args = {}
if settings.agent_database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.agent_database_url, connect_args=connect_args)
db = SQLDatabase(engine)

llm = ChatOpenAI(
    api_key=settings.deepseek_api_key or "dummy_key",
    base_url=settings.deepseek_base_url,
    model=settings.deepseek_model,
    temperature=0
)

# NWC Prompt Template
nwc_template = """Given an input question about NWC (Net Working Capital), generate a syntactically correct {dialect} query to run.
Unless the user specifies a specific number of examples to obtain, query for at most {top_k} results.

History:
{history}

User Question: {input}

NWC Configuration (Target Models per Article):
{nwc_config}

Instructions:
1. The table `results_data` contains forecast data.
2. The columns in `results_data` usually correspond to different models (e.g., 'auto_arima', 'tft', 'stacking_rfr', etc.) or there is a 'model' column. 
   - IF the table has columns like 'date', 'article', 'model', 'value', THEN filter by `model = '<target_model>'`.
   - IF the table has columns like 'date', 'article', 'auto_arima', 'tft', ... THEN select the column corresponding to the target model.
   - Use the "NWC Configuration" above to find the target model AND pipeline for the requested article.
   - IMPORTANT: You MUST filter by the 'pipeline' specified in the config (e.g. `pipeline = 'base'` or `pipeline = 'base+'`).
   - Example 1: If config says "Торговая ДЗ": "model": "stacking_rfr", "pipeline": "base+", then select 'stacking_rfr' data where `article = 'Торговая ДЗ'` AND `pipeline = 'base+'`.
   - Example 2: If config says "Прочие налоги": "model": "autoarima", "pipeline": "base", then select 'autoarima' data where `article = 'Прочие налоги'` AND `pipeline = 'base'`.
3. Filter by the specific 'article' requested.
   - CRITICAL: You MUST use the EXACT spelling of the article key from the "NWC Configuration" JSON above.
   - DO NOT correct typos. The database expects the exact string from the config (e.g. if config has "Кредиторская задлолженность по ОС", use exactly that).
4. Filter by date/month if requested.
5. If the user asks for "Fact" (Факт), look for a 'fact' column or similar.

SPECIAL INSTRUCTIONS FOR "ALL MODELS" REQUESTS:
If the user specifically asks for "all models", "compare models", "все модели", or similar:
- DO NOT select only the single best model column.
- INSTEAD, select ALL available prediction columns (predict_*) alongside 'date' and 'fact'.
- Example Columns to select: date, fact, predict_stacking_rfr, predict_ml_tabular, predict_naive, predict_autoarima, etc. (Check table schema for actual names).
- If the table has many columns, select the top 5-7 most relevant model columns + fact.
- Do NOT calculate deviations for every single model in the SQL unless specifically asked. Just return the raw values.
- Still filter by `article = 'Target Article'`.
- PIPELINE FILTERING FOR "ALL MODELS":
   - **CRITICAL CHANGE**: If the user asks for "ALL MODELS" (все модели), assume they want data from ALL pipelines unless they specify otherwise.
   - DO NOT filter by pipeline if the request is "all models".
   - Select the 'pipeline' column so we can distinguish rows.
   - Only filter by pipeline if the user explicitly names one (e.g. "all models in base pipeline").
   - If no pipeline is mentioned, return ALL rows matching the article, regardless of pipeline.

SPECIAL INSTRUCTIONS FOR ANALYSIS/COMPARISON (Single Model):
If the user asks to "analyze", "compare", or "check deviation" without exploring specific analysis type (and NOT asking for all models):
1. Retrieval 1 (Graph): Select 'date', 'fact', and the target model column (e.g. 'predict_stacking_rfr').
2. Retrieval 2 (Deviation): We need data for the LATEST available 13 months in the dataset.
   - Do NOT filter using `CURRENT_DATE` or `NOW()`. 
   - Instead, simply `ORDER BY date DESC` and `LIMIT 13`.
   - This ensures we get the most recent 13 months of data/forecasts available, regardless of today's date.
   - Return columns: 'date', 'fact', 'forecast_value' (aliased from target model).
   
   To combine these into one query useful for both chart and summary:
   - Select date, fact, <target_model> as forecast_value
   - ALSO SELECT the following deviation columns (calculate them if they don't exist):
     - 'abs_deviation' = (fact - <target_model>)
     - 'rel_deviation' = (fact - <target_model>) / NULLIF(fact, 0)
   - Order by date DESC
   - Limit to 13 rows.

6. Return ONLY the SQL query.

Only use the following tables:
{table_info}

SQLQuery:"""

def fetch_nwc_config(auth_token: str) -> Dict[str, Any]:
    if not auth_token:
        app_logger.warning("fetch_nwc_config: No auth token provided")
        return {}
    
    url = f"{settings.nwc_service_url}/config"
    headers = {"Authorization": f"Bearer {auth_token}"}
    
    try:
        app_logger.info(f"fetch_nwc_config: Requesting {url}")
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            app_logger.info(f"fetch_nwc_config: Response Status: {resp.status_code}")
            
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    app_logger.info("fetch_nwc_config: Response is not JSON, trying YAML")
                    return yaml.safe_load(resp.text)
            else:
                app_logger.error(f"fetch_nwc_config: Error {resp.status_code}: {resp.text}")
                return {}
    except Exception as e:
        app_logger.error(f"fetch_nwc_config: Exception: {e}", exc_info=True)
        return {}

def generate_nwc_query(state: Dict[str, Any]):
    """
    Node to generate SQL for NWC requests using external config.
    """
    question = state.get("question", "")
    auth_token = state.get("auth_token")
    history = state.get("chat_history", [])
    history_str = json.dumps(history[-5:], ensure_ascii=False) if history else "[]"
    
    app_logger.info("generate_nwc_query: fetching config")
    config = fetch_nwc_config(auth_token)
    
    # Extract model_article mapping
    model_article = config.get("model_article", {})
    
    # Format config for prompt
    config_str = json.dumps(model_article, ensure_ascii=False, indent=2)
    
    # Identifing the article and model
    found_article = None
    found_model = None
    found_pipeline = None
    lower_question = question.lower()
    
    for article, details in model_article.items():
        if article.lower() in lower_question:
            found_article = article
            found_model = details.get("model")
            found_pipeline = details.get("pipeline")
            break
            
    # Create prompt
    prompt = PromptTemplate.from_template(nwc_template)
    
    # Create chain
    # We pass nwc_config as a partial variable or input
    # k controls the limit. Increasing to 1000 to return more history.
    sql_chain = create_sql_query_chain(llm, db, prompt=prompt, k=1000)
    
    try:
        app_logger.info(f"generate_nwc_query: generating SQL for '{question}'")
        query = sql_chain.invoke({
            "question": question, 
            "history": history_str,
            "nwc_config": config_str
        })
        
        # Clean up markdown
        match = re.search(r"```sql(.*?)```", query, re.DOTALL | re.IGNORECASE)
        if match:
             cleaned_query = match.group(1)
        else:
             match_generic = re.search(r"```(.*?)```", query, re.DOTALL)
             if match_generic:
                  cleaned_query = match_generic.group(1)
             else:
                  cleaned_query = query

        cleaned_query = cleaned_query.strip()
        if cleaned_query.lower().startswith("sqlquery:"):
            cleaned_query = cleaned_query[9:].strip()
            
        app_logger.info(f"generate_nwc_query: SQL generated: {cleaned_query}")
        
        # Pass context: if specific article found in config (even if we requested 'all models'),
        # we still want to pass the primary config info so formatting knows the 'best' model if needed,
        # but for multi-model queries, the summary should handle it.
        result = {"query": cleaned_query}
        
        # Pass the full config snapshot for the article if possible, 
        # so later nodes know what was used.
        if model_article:
             result["nwc_info"] = {"config": model_article}
        elif found_model:
             result["nwc_info"] = {
                 "article": found_article, 
                 "model": found_model,
                 "pipeline": found_pipeline
             }
        else:
             # Fallback
             result["nwc_info"] = {"config": config.get("config", {})}
             
        return result
        
    except Exception as e:
        app_logger.error(f"generate_nwc_query: Error: {e}")
        return {"query": "ERROR", "result": f"Failed to generate NWC SQL: {str(e)}"}
