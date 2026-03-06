from typing import Any, Dict, List, Optional
import calendar
import httpx
import json
import math
import re
import logging
import yaml
from datetime import date as _date
from sqlalchemy import text, inspect as sa_inspect
from langchain_core.prompts import PromptTemplate
from core.config import settings
from core.nodes.shared_resources import llm, engine, db, create_sql_chain, strip_think_tags

# Logger
app_logger = logging.getLogger("uvicorn")
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
   - NOTE (целевые модели): If the user explicitly asks for "целевые модели" or phrases like "только целевые модели" / "target models" / "по целевым моделям", you MUST AUTOMATICALLY use the configured pipeline for each article when generating the SQL. In practice this means:
       - (a) select only the configured target model column(s) for each article, AND
       - (b) add a pipeline filter for that article (e.g. `pipeline = 'base'` or `pipeline = 'base+'`).
       - If multiple articles are requested, apply each article's configured pipeline accordingly (per-article pipeline filtering). Do NOT treat "целевые модели" as an "all models" request — pipeline filtering is REQUIRED and must be enforced automatically by the SQL.
   - Example 1: If config says "Торговая ДЗ": "model": "stacking_rfr", "pipeline": "base+", then select 'stacking_rfr' data where `article = 'Торговая ДЗ'` AND `pipeline = 'base+'`.
   - Example 2: If config says "Прочие налоги": "model": "autoarima", "pipeline": "base", then select 'autoarima' data where `article = 'Прочие налоги'` AND `pipeline = 'base'`.
3. Filter by the specific 'article' requested.
   - CRITICAL: You MUST use the EXACT spelling of the article key from the "NWC Configuration" JSON above.
   - SPECIAL CASE — "ALL NWC ARTICLES": If the user explicitly asks for "all NWC articles", "все статьи ЧОК", "все статьи чок", "все статьи NWC" or similar phrasing meaning "all articles from the NWC set", you MUST interpret this as selecting ALL article keys listed in the provided NWC Configuration. In that case:
       - Do NOT use a substring or pattern match like `article LIKE '%ЧОК%'`.
       - Use an explicit `article IN (...)` clause containing the canonical article names from the config (apply the "IMPORTANT MAPPING" below when needed, e.g., map "Торговая ДЗ" -> "Торговая ДЗ_USD").
       - If multiple articles are requested together (e.g., "все статьи чок по целевым моделям"), you MUST also apply per-article pipeline filters for target models (see NOTE (целевые модели) above).
       - If the NWC Configuration is missing or empty, explicitly ask for clarification in Russian instead of guessing.
       - EXPLICIT SQL EXAMPLE (for clarity):
         SELECT date, article, fact, <model_column> AS forecast_value, pipeline
         FROM results_data
         WHERE article IN ('Торговая ДЗ_USD', 'Прочая ДЗ', 'Авансы выданные и расходы будущих периодов', ...)
         AND pipeline IN ('base','base+')  -- when "целевые модели" requested or when target pipeline required
         ORDER BY date DESC;
   - IMPORTANT MAPPING: If the user mentions "Торговая ДЗ", the value stored in the database is "Торговая ДЗ_USD" — you MUST use "Торговая ДЗ_USD" in the WHERE clause when filtering for this article. For other articles, use the article name as provided in the config.
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
    """Generate a SQL query for NWC requests using external NWC configuration.

    Description for planner/LLM summary:
    - Purpose: analyze the user's `question` together with the NWC configuration (fetched from external
      service using `auth_token`) and generate a syntactically correct SQL query against the `results_data` table.
    - Inputs:
      - state["question"]: natural language request about NWC forecasts.
      - state["auth_token"]: optional token used to fetch the NWC config.
      - state["chat_history"]: optional recent context to disambiguate the request.
    - Outputs:
      - On success: {"query": <sql_string>, "nwc_info": {...}} where `nwc_info` contains config/article/model/pipeline metadata used to build SQL.
      - On failure: {"query": "ERROR", "result": <error message>}.
    - Side effects: none (only reads external config and synthesizes a query).
    - Notes for plan confirmation: emphasize that this step will only *generate* SQL (not execute it); if executed later it will retrieve real data.
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
    sql_chain = create_sql_chain(prompt, k=1000)
    
    try:
        app_logger.info(f"generate_nwc_query: generating SQL for '{question}'")
        query = strip_think_tags(sql_chain.invoke({
            "question": question, 
            "history": history_str,
            "nwc_config": config_str
        }))
        
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


def nwc_analyze(state: Dict[str, Any]):
    """
    Извлекает факты и прогнозные данные за последний год по целевой модели для указанной статьи и вычисляет абсолютные и относительные отклонения. Если не укзан месяц, то берёт последний доступный месяц, если указан - то данные за год до указанного месяца.

    Behavior:
      - Use LLM to extract: article name (MUST be one of configured articles), optional model, optional date.
      - If model is missing, use the target model from config for the article.
      - If date is missing, fetch the latest forecast date from DB for that article/pipeline/model and use it.
      - For analytical requests, generate SQL that retrieves real historical forecasts and facts for the LAST 12 MONTHS (up to the target date) for the target model/pipeline; this window is preferred for time-series charts and concise summary conclusions.
      - Otherwise, return SQL retrieving the latest 13 rows (<= target_date) ordered by date DESC, including abs/rel deviations.
    """
    question = state.get("question", "")
    auth_token = state.get("auth_token")

    app_logger.info(f"nwc_analyze: processing question='{question[:160]}'")

    config = fetch_nwc_config(auth_token)
    model_article = config.get("model_article", {})
    # Use keys from "Статья" section as the canonical article list; fall back to model_article keys
    statya_keys = list(config.get("Статья", {}).keys())
    valid_articles = statya_keys if statya_keys else list(model_article.keys())

    if not model_article:
        app_logger.warning("nwc_analyze: model_article config is empty or unavailable")
        return {"result": "Не удалось получить конфигурацию NWC. Пожалуйста, попробуйте позже."}

    # Ask LLM to extract article, model (optional) and date (optional) in JSON
    extraction_prompt = f"""
    Extract the target article, optional model, and optional date from the user's request for NWC analysis.

    Valid article names (canonical, nominative case):
    {json.dumps(valid_articles, ensure_ascii=False)}

    IMPORTANT: The user may mention an article in any Russian grammatical case (genitive, dative, accusative, etc.).
    You MUST recognize declined forms and map them to the canonical nominative name from the list above.
    Examples of declined forms → canonical name:
      "торговой КЗ" → "Торговая КЗ"
      "торговой ДЗ" → "Торговая ДЗ"
      "прочей ДЗ" → "Прочая ДЗ"
      "авансов выданных" → "Авансы выданные и расходы будущих периодов"
      "задолженности перед персоналом" → "Задолженность перед персоналом"
      "торговой кредиторской задолженности" → "Торговая КЗ"
      "торговой дебиторской задолженности" → "Торговая ДЗ"
    Do NOT return "MISSING" just because the form is declined — always try to find the best match.
    Return "MISSING" only if you genuinely cannot identify which article is meant.

    User message: "{question}"

    Return ONLY JSON with the following keys:
      - article: the exact canonical article name from the list above, or "MISSING" if no valid article can be identified.
      - model: optional model string (e.g., "stacking_rfr"), or null if not specified.
      - date: optional target date in ISO format (YYYY-MM-DD). If the user mentions only a month/year, return the date as the LAST day of that month (YYYY-MM-DD). Return null if not specified.
      - pipeline: optional pipeline string (e.g., "base" or "base+"), or null if not specified. If provided, it should be used as-is (case-insensitive). If missing, the node will use the pipeline from config or default to "base".

    Examples:
    {{"article":"Торговая ДЗ","model":"stacking_rfr","date":"2025-12-31","pipeline":"base+"}}
    {{"article":"Прочая ДЗ","model":null,"date":null,"pipeline":null}}
    {{"article":"MISSING"}}
    """

    try:
        app_logger.info("nwc_analyze: invoking LLM for parameter extraction")
        resp = llm.invoke(extraction_prompt)
        content = strip_think_tags(resp.content)
        app_logger.info(f"nwc_analyze: LLM raw response: {content}")

        match = re.search(r"```json(.*?)```", content, re.DOTALL | re.IGNORECASE)
        if match:
            content = match.group(1).strip()
        elif content.startswith("``"):
            content = content.strip("`")

        params = json.loads(content)
    except Exception as e:
        app_logger.error(f"nwc_analyze: Failed to extract params via LLM: {e}")
        return {"result": "Не удалось понять запрос. Пожалуйста, укажите статью в виде 'Проанализируй прогноз на <название статьи>'."}

    article = params.get("article") if isinstance(params, dict) else None
    extracted_model = params.get("model") if isinstance(params, dict) else None
    extracted_date = params.get("date") if isinstance(params, dict) else None

    # Validate article
    if not article or article == "MISSING" or article not in model_article:
        sample = ", ".join(valid_articles[:12])
        return {"result": f"Пожалуйста, уточните статью для анализа. Возможные варианты: {sample}..."}

    details = model_article.get(article, {})
    target_model = extracted_model or details.get("model")
    extracted_pipeline = params.get("pipeline") if isinstance(params, dict) else None
    # Priority: extracted_pipeline (from user message) -> pipeline from config -> default 'base'
    pipeline = (extracted_pipeline or details.get("pipeline") or "base").lower()

    model_source = "request" if extracted_model and extracted_model.lower() not in ("target", "целев", "целевые", "по целевым") else "config"

    if not target_model:
        app_logger.warning(f"nwc_analyze: No target model found for article '{article}'")
        target_model = "naive"

    # DB article mapping special case
    db_article = article
    if article == "Торговая ДЗ":
        db_article = "Торговая ДЗ_USD"

    # Build model column name (predict_<model>) and sanitize
    model_col = f"predict_{target_model.lower()}"
    model_col = re.sub(r"[^a-z0-9_]", "_", model_col.lower())

    # Determine target_date: use extracted_date if provided, else fetch latest date from DB for this article/pipeline/model
    target_date = None
    if extracted_date:
        target_date = extracted_date
    else:
        # Try to find latest date where model predictions exist
        try:
            with engine.connect() as conn:
                sql = text(f"SELECT MAX(date) AS max_date FROM results_data WHERE article = :article AND pipeline = :pipeline AND {model_col} IS NOT NULL")
                res = conn.execute(sql, {"article": db_article, "pipeline": pipeline}).fetchone()
                max_date = res[0] if res is not None else None
                if max_date:
                    # Convert to ISO date string
                    if hasattr(max_date, "isoformat"):
                        target_date = max_date.isoformat()
                    else:
                        target_date = str(max_date)
                else:
                    app_logger.warning(f"nwc_analyze: No forecast rows found for article={db_article}, pipeline={pipeline}, model_col={model_col}")
                    return {"result": "В базе нет доступных прогнозов для указанной статьи/модели. Пожалуйста, уточните запрос."}
        except Exception as e:
            app_logger.error(f"nwc_analyze: DB error while fetching latest date: {e}")
            return {"result": "Ошибка при обращении к базе данных при получении даты. Попробуйте позже."}

    # Final SQL: get last 13 rows up to target_date
    query = f"""SELECT
    date,
    article,
    fact,
    {model_col} AS forecast_value,
    pipeline,
    (fact - {model_col}) AS abs_deviation,
    (fact - {model_col}) / NULLIF(fact, 0) AS rel_deviation
FROM results_data
WHERE article = '{db_article}'
  AND pipeline = '{pipeline}'
  AND date <= '{target_date}'
ORDER BY date DESC
LIMIT 13;"""

    app_logger.info(f"nwc_analyze: Generated query for article '{article}', model='{target_model}', pipeline='{pipeline}', date='{target_date}'")

    return {
        "query": query,
        "nwc_info": {"article": article, "model": target_model, "pipeline": pipeline, "target_date": target_date, "model_source": model_source}
    }


def generate_nwc_viz(state: Dict[str, Any]) -> Dict[str, Any]:
    """Генерирует спецификацию Vega-Lite для анализа прогноза NWC по шаблону (без вызова LLM).

    Description for planner/LLM summary:
    - Purpose: use the `nwc_info` metadata (article, model, pipeline, target_date) stored by `nwc_analyze`
      to build a pre-defined Vega-Lite v5 chart spec — a two-line time-series chart overlaying
      `fact` and `forecast_value`, with deviation info in tooltips. No LLM call is made.
    - Inputs:
      - state["nwc_info"]: dict with at least {"article", "model", "pipeline"} keys.
      - state["tables"]: used only to verify data is available before building the spec.
    - Outputs: {"charts": [ {"title": ..., "spec": <vega-lite-spec>} ]} or {"charts": []} if no data.
    - Side effects: none.
    - Notes for plan confirmation: this step creates a chart specification using a fixed template
      (no AI generation). The frontend will render the chart from the spec.
    """
    app_logger.info("generate_nwc_viz: building chart spec from template")
    tables = state.get("tables", [])
    if not tables or not tables[0].get("rows"):
        app_logger.info("generate_nwc_viz: no data, skipping chart")
        return {"charts": []}

    nwc_info = state.get("nwc_info") or {}
    article = nwc_info.get("article", "")
    model = nwc_info.get("model", "")
    pipeline = nwc_info.get("pipeline", "")
    target_date = nwc_info.get("target_date", "")

    # Build a readable title
    title_parts = [f"Анализ прогноза: {article}" if article else "Анализ прогноза NWC"]
    if model:
        title_parts.append(f"модель {model}")
    if pipeline:
        title_parts.append(f"пайплайн {pipeline}")
    chart_title = ", ".join(title_parts)

    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": chart_title,
        "width": "container",
        "height": 300,
        "data": {"name": "table_data"},
        "layer": [
            {
                "mark": {"type": "line", "point": {"size": 70, "filled": True}},
                "encoding": {
                    "x": {
                        "field": "date",
                        "type": "temporal",
                        "title": "Дата",
                        "axis": {"format": "%Y-%m"}
                    },
                    "y": {
                        "field": "fact",
                        "type": "quantitative",
                        "title": "Значение (млн. руб.)"
                    },
                    "color": {
                        "datum": "Факт",
                        "type": "nominal",
                        "scale": {"domain": ["Факт", "Прогноз"], "range": ["#1f77b4", "#ff7f0e"]},
                        "legend": {"title": "Показатель"}
                    },
                    "tooltip": [
                        {"field": "date", "type": "temporal", "title": "Дата", "format": "%Y-%m-%d"},
                        {"field": "fact", "type": "quantitative", "title": "Факт", "format": ".2f"},
                        {"field": "forecast_value", "type": "quantitative", "title": "Прогноз", "format": ".2f"},
                        {"field": "abs_deviation", "type": "quantitative", "title": "Абс. отклонение", "format": ".2f"},
                        {"field": "rel_deviation", "type": "quantitative", "title": "Отн. отклонение", "format": ".1%"}
                    ]
                }
            },
            {
                "mark": {"type": "line", "point": {"size": 70, "filled": True}, "strokeDash": [6, 3]},
                "encoding": {
                    "x": {
                        "field": "date",
                        "type": "temporal"
                    },
                    "y": {
                        "field": "forecast_value",
                        "type": "quantitative"
                    },
                    "color": {
                        "datum": "Прогноз",
                        "type": "nominal",
                        "scale": {"domain": ["Факт", "Прогноз"], "range": ["#1f77b4", "#ff7f0e"]},
                        "legend": {"title": "Показатель"}
                    },
                    "tooltip": [
                        {"field": "date", "type": "temporal", "title": "Дата", "format": "%Y-%m-%d"},
                        {"field": "fact", "type": "quantitative", "title": "Факт", "format": ".2f"},
                        {"field": "forecast_value", "type": "quantitative", "title": "Прогноз", "format": ".2f"},
                        {"field": "abs_deviation", "type": "quantitative", "title": "Абс. отклонение", "format": ".2f"},
                        {"field": "rel_deviation", "type": "quantitative", "title": "Отн. отклонение", "format": ".1%"}
                    ]
                }
            }
        ],
        "resolve": {"scale": {"y": "shared"}}
    }

    app_logger.info(f"generate_nwc_viz: chart spec built for article='{article}', model='{model}', pipeline='{pipeline}'")
    return {"charts": [{"title": chart_title, "spec": spec}]}


def nwc_show_forecast(state: Dict[str, Any]):
    """
    Формирует SQL-запрос для извлечения реальных прогнозов для целевого периода по целевым моделям для выбранных статей (не выполняет SQL).

    Behavior:
      - Use LLM to extract: list of articles (array) or 'ALL', optional model (applies to all), optional pipeline, optional date.
      - If model is provided in prompt: use it for ALL articles; pipeline defaults to 'base' if not provided.
      - If model is NOT provided: use per-article target model and pipeline from config (this selection will be reflected in the confirmation and query construction).
      - If date not provided: find the latest available date across the selected article/model/pipeline combinations and use it.
      - Generated SQL will cover the target month AND the preceding 12 months (13 points total) to support trend analysis and charts.
      - Return SQL selecting rows for the selected articles on the chosen date, with a CASE for forecast_value when different models are used.
      - Do NOT generate visualizations.
    """
    question = state.get("question", "")
    auth_token = state.get("auth_token")

    app_logger.info(f"nwc_show_forecast: processing question='{question[:160]}'")

    config = fetch_nwc_config(auth_token)
    model_article = config.get("model_article", {})
    default_articles = config.get("default_articles") or list(model_article.keys())

    if not model_article:
        app_logger.warning("nwc_show_forecast: model_article config is empty or unavailable")
        return {"result": "Не удалось получить конфигурацию NWC. Пожалуйста, попробуйте позже."}

    extraction_prompt = f"""
    Extract the list of articles (or 'ALL'), optional model, optional pipeline, and optional date from the user's request for showing forecasts.

    Valid article names (must match one of these exactly): {json.dumps(default_articles, ensure_ascii=False)}

    User message: "{question}"

    Return ONLY JSON with keys:
      - articles: array of article names (from list above) OR the string "ALL" if the user requests all articles.
      - model: optional model string to use for ALL articles (e.g., "autoarima"), or null if not specified.
      - pipeline: optional pipeline string (e.g., "base", "base+"), or null if not specified.
      - date: optional target date in ISO (YYYY-MM-DD), or null if not specified.

    Examples:
    {{"articles":["Торговая ДЗ","Торговая КЗ"],"model":null,"pipeline":null,"date":"2025-12-31"}}
    {{"articles":"ALL","model":null,"pipeline":null,"date":null}}
    {{"articles":["Прочая ДЗ"],"model":"autoarima","pipeline":"base","date":null}}
    """

    try:
        app_logger.info("nwc_show_forecast: invoking LLM for parameter extraction")
        resp = llm.invoke(extraction_prompt)
        content = strip_think_tags(resp.content)
        app_logger.info(f"nwc_show_forecast: LLM raw response: {content}")

        match = re.search(r"```json(.*?)```", content, re.DOTALL | re.IGNORECASE)
        if match:
            content = match.group(1).strip()
        elif content.startswith("``"):
            content = content.strip("`")

        params = json.loads(content)
    except Exception as e:
        app_logger.error(f"nwc_show_forecast: Failed to extract params via LLM: {e}")
        return {"result": "Не удалось понять запрос. Пожалуйста, укажите статью(и) в виде 'Выведи прогноз по всем статьям на декабрь 2025' или перечислите статьи."}

    # Parse params
    articles_param = params.get("articles") if isinstance(params, dict) else None
    extracted_model = params.get("model") if isinstance(params, dict) else None
    extracted_pipeline = params.get("pipeline") if isinstance(params, dict) else None
    extracted_date = params.get("date") if isinstance(params, dict) else None

    # Resolve articles list
    if isinstance(articles_param, str) and articles_param.upper() == "ALL":
        articles = list(model_article.keys())
    elif isinstance(articles_param, list):
        articles = articles_param
    else:
        # try to detect single article name in the user question (fallback)
        lower_q = question.lower()
        articles = []
        for art in sorted(model_article.keys(), key=lambda x: -len(x)):
            if art.lower() in lower_q:
                articles.append(art)
        if not articles:
            sample = ", ".join(default_articles[:12])
            return {"result": f"Пожалуйста, уточните, по каким статьям вы хотите вывести прогноз. Возможные варианты: {sample}..."}

    # Validate articles
    invalid = [a for a in articles if a not in model_article]
    if invalid:
        return {"result": f"Найдены неизвестные статьи: {', '.join(invalid)}. Пожалуйста, используйте названия из конфигурации."}

    # Determine per-article model and pipeline
    model_map = {}
    pipeline_map = {}

    # Build allowed models set from config
    allowed_models = set()
    models_cfg = config.get("models_to_use") or {}
    for m in models_cfg.keys():
        allowed_models.add(m.lower())
    for details in model_article.values():
        if details.get("model"):
            allowed_models.add(details.get("model").lower())

    # Detect if user asked 'по целевым моделям' or similar
    use_target_models = False
    if extracted_model:
        em_lower = extracted_model.lower()
        if any(sub in em_lower for sub in ["целев", "по целев", "target"]):
            use_target_models = True
            extracted_model = None
        elif em_lower not in allowed_models:
            # unknown model specified
            sample = ", ".join(sorted(list(allowed_models))[:10])
            return {"result": f"Неизвестная модель '{extracted_model}'. Возможные модели: {sample}..."}

    if extracted_model:
        # apply single model for all; pipeline defaults to 'base' if not provided
        for a in articles:
            model_map[a] = extracted_model
            pipeline_map[a] = (extracted_pipeline or "base").lower()
        model_source = "request"
    else:
        # use per-article target models from config
        for a in articles:
            details = model_article.get(a, {})
            model_map[a] = details.get("model") or None
            pipeline_map[a] = (details.get("pipeline") or "base").lower()
        model_source = "config"

    # If user explicitly requested target models, ensure we mark it as 'config'
    if use_target_models:
        model_source = "config"


    # Map DB article (special case)
    db_articles = {}
    for a in articles:
        db_articles[a] = "Торговая ДЗ_USD" if a == "Торговая ДЗ" else a

    # Determine target_date: use extracted_date if provided, else fetch MAX(date) across selected combos
    target_date = None
    if extracted_date:
        target_date = extracted_date
    else:
        # Build query to get max date across article/pipeline/model combinations
        conds = []
        params_sql = {}
        for idx, a in enumerate(articles):
            model_name = model_map.get(a)
            art_param = f"a{idx}"
            pipe_param = f"p{idx}"
            if model_name:
                model_col = f"predict_{model_name.lower()}"
                model_col = re.sub(r"[^a-z0-9_]", "_", model_col.lower())
                conds.append(f"(article = :{art_param} AND pipeline = :{pipe_param} AND {model_col} IS NOT NULL)")
            else:
                # No specific model for this article - allow any non-null forecast row for this article/pipeline
                conds.append(f"(article = :{art_param} AND pipeline = :{pipe_param})")
            params_sql[art_param] = db_articles[a]
            params_sql[pipe_param] = pipeline_map[a]

        sql = text(f"SELECT MAX(date) AS max_date FROM results_data WHERE {' OR '.join(conds)}")
        try:
            with engine.connect() as conn:
                res = conn.execute(sql, params_sql).fetchone()
                max_date = res[0] if res is not None else None
                if max_date:
                    target_date = max_date.isoformat() if hasattr(max_date, "isoformat") else str(max_date)
                else:
                    return {"result": "В базе нет доступных прогнозов для запрошенных статей/моделей. Пожалуйста, уточните запрос."}
        except Exception as e:
            app_logger.error(f"nwc_show_forecast: DB error while fetching latest date: {e}")
            return {"result": "Ошибка при обращении к базе данных при получении даты. Попробуйте позже."}

    # Build CASE for forecast_value and model name
    case_lines = []
    model_case_lines = []
    for a in articles:
        db_a = db_articles[a]
        model_name = model_map.get(a)
        if not model_name:
            # No model specified for this article -> return NULL so downstream can handle missing forecasts
            case_lines.append(f"WHEN article = '{db_a}' THEN NULL")
            model_case_lines.append(f"WHEN article = '{db_a}' THEN NULL")
        else:
            model_col = f"predict_{model_name.lower()}"
            model_col = re.sub(r"[^a-z0-9_]", "_", model_col.lower())
            case_lines.append(f"WHEN article = '{db_a}' THEN {model_col}")
            # model column should contain the model name as string
            model_case_lines.append(f"WHEN article = '{db_a}' THEN '{model_name}'")

    case_expr = "\n    ".join(case_lines)
    model_case_expr = "\n    ".join(model_case_lines)

    # Build where clause for pipelines per article
    pipeline_conds = []
    for a in articles:
        db_a = db_articles[a]
        p = pipeline_map[a]
        pipeline_conds.append(f"(article = '{db_a}' AND pipeline = '{p}')")

    articles_in = ', '.join([f"'{db_articles[a]}'" for a in articles])
    where_clause = f"article IN ({articles_in}) AND ( {' OR '.join(pipeline_conds)} ) AND date = '{target_date}'"

    query = f"""SELECT
    date,
    article,
    fact,
    CASE
    {case_expr}
    END AS forecast_value,
    CASE
    {model_case_expr}
    END AS model,
    pipeline
FROM results_data
WHERE {where_clause}
ORDER BY article;"""

    app_logger.info(f"nwc_show_forecast: Generated query for articles={articles}, date={target_date}")

    return {"query": query, "nwc_info": {"articles": articles, "models": model_map, "pipelines": pipeline_map, "target_date": target_date, "model_source": model_source}}


# ---------------------------------------------------------------------------
# Helper: subtract N calendar months from a date
# ---------------------------------------------------------------------------
def _subtract_months(d: _date, months: int) -> _date:
    """Return d minus `months` calendar months, clamped to end-of-month if needed."""
    total_months = d.month - 1 - months
    year = d.year + total_months // 12
    month = total_months % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


def article_model_selection(state: Dict[str, Any]) -> Dict[str, Any]:
    """Сравнить все доступные модели (оба пайплайна: base и base+) для указанной статьи NWC по метрике mean(abs(rel_deviation)) за заданный период.

    Description for planner/LLM summary:
    - Purpose: for the given NWC article, query ALL predict_* columns in `results_data` across
      both 'base' and 'base+' pipelines. Only rows where `fact IS NOT NULL` are included.
      Computes mean(abs((fact - predict_X) / fact)) per (model, pipeline), sorts ascending,
      and reports the best model alongside the currently configured target model.
    - Inputs:
      - state["question"]: user request specifying the article and optional analysis period
        (e.g. "за последний год", "за 6 месяцев", "за 2 года"). Default period: 12 months.
      - state["auth_token"]: token to fetch NWC configuration (current target model per article).
    - Outputs:
      - {"tables": [<ranking table>], "result": <text summary>, "nwc_info": {...}} — no EXECUTE_SQL needed.
    - Side effects: issues direct SQL queries to the agent DB (read-only).
    - Notes for plan confirmation: the agent will scan ALL models in both pipelines for the requested
      article over the specified period and rank them by average absolute relative deviation.
      The currently configured target model and the best-performing model will be highlighted.
    """
    question = state.get("question", "")
    auth_token = state.get("auth_token")

    app_logger.info(f"article_model_selection: processing question='{question[:160]}'")

    # --- 1. Fetch NWC config ------------------------------------------------
    config = fetch_nwc_config(auth_token)
    model_article = config.get("model_article", {})
    statya_keys = list(config.get("Статья", {}).keys())
    valid_articles = statya_keys if statya_keys else list(model_article.keys())

    if not model_article:
        return {"result": "Не удалось получить конфигурацию NWC. Пожалуйста, попробуйте позже."}

    # --- 2. Extract article + period via LLM --------------------------------
    extraction_prompt = f"""
Extract the NWC article name and the analysis period (in months) from the user's request.

Valid article names (canonical nominative forms):
{json.dumps(valid_articles, ensure_ascii=False)}

The user may mention the article in any grammatical case. Map declined forms to the canonical name.
Examples: "торговой ДЗ" → "Торговая ДЗ", "торговой КЗ" → "Торговая КЗ".
Return "MISSING" only if the article genuinely cannot be identified.

For the period:
- "за последний год" / "за год" → 12
- "за N месяцев" → N
- "за N года" / "за N лет" → N * 12
- not specified → 12 (default)

User message: "{question}"

Return ONLY JSON:
  - "article": canonical name from the list above, or "MISSING"
  - "months": integer number of months (default 12)

Example: {{"article": "Торговая ДЗ", "months": 12}}
"""

    try:
        app_logger.info("article_model_selection: invoking LLM for parameter extraction")
        resp = llm.invoke(extraction_prompt)
        content = strip_think_tags(resp.content)
        app_logger.info(f"article_model_selection: LLM raw response: {content}")
        m = re.search(r"```json(.*?)```", content, re.DOTALL | re.IGNORECASE)
        if m:
            content = m.group(1).strip()
        elif content.startswith("``"):
            content = content.strip("`")
        params = json.loads(content)
    except Exception as e:
        app_logger.error(f"article_model_selection: LLM extraction failed: {e}")
        return {"result": "Не удалось распознать статью. Укажите, например: 'Сравни модели по Торговой ДЗ'."}

    article = params.get("article") if isinstance(params, dict) else None
    analysis_months = int(params.get("months") or 12)
    if analysis_months <= 0:
        analysis_months = 12

    if not article or article == "MISSING" or article not in model_article:
        sample = ", ".join(valid_articles[:12])
        return {"result": f"Пожалуйста, уточните статью для сравнения моделей. Возможные варианты: {sample}..."}

    # DB article name mapping
    db_article = "Торговая ДЗ_USD" if article == "Торговая ДЗ" else article

    # --- 3. Get all predict_* column names from DB schema -------------------
    try:
        inspector = sa_inspect(engine)
        columns_info = inspector.get_columns("results_data")
        all_col_names = [c["name"] for c in columns_info]
        app_logger.info(f"article_model_selection: schema columns ({len(all_col_names)}): {all_col_names}")
    except Exception as e:
        app_logger.error(f"article_model_selection: schema inspection failed: {e}", exc_info=True)
        return {"result": "Не удалось получить схему таблицы results_data. Попробуйте позже."}

    predict_cols = [(c, c[len("predict_"):]) for c in all_col_names if c.startswith("predict_")]
    app_logger.info(f"article_model_selection: predict_cols found ({len(predict_cols)}): {[c for c,_ in predict_cols]}")
    if not predict_cols:
        return {"result": "В таблице results_data не найдено столбцов с прогнозами (predict_*)."}

    # --- 4. Find reference date (latest date with fact for this article) ----
    # Must filter by the same pipelines used in the UNION query, otherwise ref_date may come
    # from a different pipeline where fact is populated further into the future.
    app_logger.info(f"article_model_selection: querying ref_date for db_article='{db_article}'")
    try:
        with engine.connect() as conn:
            res = conn.execute(
                text(
                    "SELECT MAX(date) FROM results_data "
                    "WHERE article = :article "
                    "AND fact IS NOT NULL AND fact::text != 'NaN' "
                    "AND pipeline IN ('base', 'base+')"
                ),
                {"article": db_article}
            ).fetchone()
            ref_date_raw = res[0] if res else None
        app_logger.info(f"article_model_selection: ref_date_raw={ref_date_raw!r} (type={type(ref_date_raw).__name__})")
    except Exception as e:
        app_logger.error(f"article_model_selection: DB error fetching ref date: {e}", exc_info=True)
        return {"result": "Ошибка при обращении к базе данных. Попробуйте позже."}

    if not ref_date_raw:
        return {"result": f"В базе нет фактических данных для статьи '{article}'."}

    # Normalize to datetime.date
    if hasattr(ref_date_raw, "date"):
        ref_date: _date = ref_date_raw.date()
    elif isinstance(ref_date_raw, _date):
        ref_date = ref_date_raw
    else:
        ref_date = _date.fromisoformat(str(ref_date_raw)[:10])

    start_date = _subtract_months(ref_date, analysis_months)
    ref_date_str = ref_date.isoformat()
    start_date_str = start_date.isoformat()

    app_logger.info(
        f"article_model_selection: article='{article}', period={analysis_months}m, "
        f"ref_date={ref_date_str} (last date with fact), start_date={start_date_str}, predict_cols={len(predict_cols)}"
    )

    # --- 5. Build a UNION ALL query for all (model, pipeline) combos --------
    pipelines = ["base", "base+"]
    union_parts = []
    for col, model_name in predict_cols:
        # Sanitize model name for SQL literal (col name already came from inspector, safe)
        safe_model_name = model_name.replace("'", "''")
        safe_article = db_article.replace("'", "''")
        for pl in pipelines:
            safe_pl = pl.replace("'", "''")
            union_parts.append(
                f"SELECT '{safe_pl}' AS pipeline, '{safe_model_name}' AS model,\n"
                f"       AVG(ABS((fact - {col}) / NULLIF(ABS(fact), 0))) AS mean_abs_rel_dev,\n"
                f"       COUNT(DISTINCT date) AS n_months\n"
                f"FROM results_data\n"
                f"WHERE article = '{safe_article}' AND pipeline = '{safe_pl}'\n"
                f"  AND fact IS NOT NULL AND fact::text != 'NaN'\n"
                f"  AND {col} IS NOT NULL AND {col}::text != 'NaN'\n"
                f"  AND fact != 0\n"
                f"  AND date > '{start_date_str}' AND date <= '{ref_date_str}'"
            )

    full_query = "\nUNION ALL\n".join(union_parts)
    app_logger.info(f"article_model_selection: built UNION ALL query with {len(union_parts)} parts, total len={len(full_query)}")
    app_logger.debug(f"article_model_selection: first UNION part:\n{union_parts[0] if union_parts else 'EMPTY'}")

    try:
        with engine.connect() as conn:
            rows_raw = conn.execute(text(full_query)).fetchall()
        app_logger.info(f"article_model_selection: query returned {len(rows_raw)} raw rows")
    except Exception as e:
        # Log full traceback and a snippet of the failing query
        query_snippet = full_query[:2000] + ('...' if len(full_query) > 2000 else '')
        app_logger.error(
            f"article_model_selection: DB error computing metrics: {e}\nQuery snippet:\n{query_snippet}",
            exc_info=True
        )
        return {"result": f"Ошибка при вычислении метрик: {e}"}

    # Filter out rows with no data, zero months, or non-finite values (NaN/Inf from division edge-cases)
    results = []
    for r in rows_raw:
        if r[2] is None or int(r[3]) <= 0:
            continue
        val = float(r[2])
        if not math.isfinite(val):
            app_logger.debug(f"article_model_selection: skipping non-finite value model={r[1]} pipeline={r[0]} val={val}")
            continue
        results.append({"pipeline": r[0], "model": r[1], "mean_abs_rel_dev": val, "n_months": int(r[3])})

    app_logger.info(f"article_model_selection: after filtering — {len(results)} valid combos remain")
    if not results:
        return {"result": f"Нет данных с фактом для статьи '{article}' за указанный период ({analysis_months} мес.)."}

    # Sort ascending by mean absolute relative deviation
    results.sort(key=lambda x: x["mean_abs_rel_dev"])

    # --- 6. Get configured target model -------------------------------------
    target_config = model_article.get(article, {})
    target_model = target_config.get("model")
    target_pipeline = (target_config.get("pipeline") or "base").lower()

    # --- 7. Build output table ----------------------------------------------
    headers = ["pipeline", "model", "mean_abs_rel_deviation", "n_months_with_fact"]
    table_rows = [
        [r["pipeline"], r["model"], round(r["mean_abs_rel_dev"], 6), r["n_months"]]
        for r in results
    ]

    best = results[0]
    worst = results[-1]

    # Check if target model is in results
    target_entry = next(
        (r for r in results if r["model"] == target_model and r["pipeline"] == target_pipeline),
        None
    )
    target_rank = results.index(target_entry) + 1 if target_entry else None

    # --- 8. Build result text for SUMMARIZE ---------------------------------
    period_label = f"{analysis_months} мес." if analysis_months != 12 else "последний год (12 мес.)"
    summary_lines = [
        f"Сравнение моделей по статье '{article}' за {period_label} (до {ref_date_str}).",
        f"Всего протестировано комбинаций: {len(results)} (модели × пайплайны base/base+).",
        f"",
        f"Текущая целевая модель: {target_model} / пайплайн '{target_pipeline}'"
        + (f" — занимает место #{target_rank} из {len(results)} (MAPE={target_entry['mean_abs_rel_dev']:.4f})" if target_entry else " — нет данных за период"),
        f"",
        f"Лучшая модель: {best['model']} / пайплайн '{best['pipeline']}' (MAPE={best['mean_abs_rel_dev']:.4f}, факт за {best['n_months']} мес.)",
        f"Худшая модель: {worst['model']} / пайплайн '{worst['pipeline']}' (MAPE={worst['mean_abs_rel_dev']:.4f})",
    ]

    if target_entry and target_rank and target_rank > 1:
        better = results[:target_rank - 1]
        better_str = "; ".join(f"{r['model']} ({r['pipeline']})" for r in better[:3])
        if target_rank - 1 > 3:
            better_str += f" и ещё {target_rank - 4}"
        summary_lines.append(f"")
        summary_lines.append(f"Модели лучше целевой: {better_str}.")
    elif target_entry and target_rank == 1:
        summary_lines.append(f"Целевая модель является наилучшей за данный период.")

    result_text = "\n".join(summary_lines)

    app_logger.info(
        f"article_model_selection: done. best={best['model']}/{best['pipeline']}, "
        f"target={target_model}/{target_pipeline} rank={target_rank}/{len(results)}"
    )

    return {
        "tables": [{
            "title": f"Сравнение моделей: {article} ({period_label})",
            "headers": headers,
            "rows": table_rows,
        }],
        "result": result_text,
        "nwc_info": {
            "article": article,
            "target_model": target_model,
            "target_pipeline": target_pipeline,
            "analysis_months": analysis_months,
            "ref_date": ref_date_str,
        },
    }
