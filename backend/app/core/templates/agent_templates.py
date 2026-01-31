template = """Given an input question, decide if it requires a database query.
If the question is just a greeting, a general conversational remark, or does not imply data retrieval (e.g. "Hello", "Thanks", "Who are you?"), return exactly: NO_SQL

History:
{history}

Question: {input}

IMPORTANT INSTRUCTIONS:
1. PRIORITIZE the "Question" over "History". The "History" is provided for context only.
2. If the "Question" contains sufficient information to execute the task, DO NOT use "History".
3. **CRITICAL**: If the "Question" is ambiguous, short (e.g. just a name like "Торговая КЗ", "2025"), or seems to be an answer to a clarification, YOU MUST Use "History" to reconstruct the user's intent. 
   - Treat the "Question" as a refinement or parameter update to the previous query in "History".
   - Do NOT return NO_SQL in this case. Generate the SQL.
4. Try to solve the problem using ONLY the "Question" first.

Otherwise, create a syntactically correct {dialect} query to run.
Unless the user specifies a specific number of examples to obtain, query for at most {top_k} results.
Never query for all the columns from a specific table, only ask for the relevant columns given the question.
Pay attention to use only the column names you can see in the schema description. Be careful to not query for columns that do not exist.
Pay attention to which column is in which table. Also, qualify column names with the table name when needed.

If the question is in a different language (e.g., Russian) than the database schema (e.g., English), 
you MUST map the terms in the question to the closest matching column names in the schema.
Do NOT simply transcribe the non-English terms as column names. 
Example: "разница по прогнозу naive" -> "predict_naive_diff" (if available).

IMPORTANT: 
- If calculating a ratio or percentage, return the raw decimal value (e.g. 0.05 for 5%). Do NOT multiply by 100.
- When filtering by 'article', do NOT append "_USD" suffix to the article value, UNLESS the article is "Торговая ДЗ". 
  - "Торговая КЗ" -> 'Торговая КЗ' (no suffix).
  - "Торговая ДЗ" -> 'Торговая ДЗ_USD' (add suffix).
- If the user asks to "compare" (сравнить) values, especially Forecast vs Fact:
  - Case A: Different Dates (e.g. "AutoArima Feb 2025 vs Fact Jan 2025"):
    - You MUST use a SELF-JOIN (or CTE) to align the two values in a SINGLE row. 
    - Do NOT return distinct rows for each month.
    - Calculate deviations: (Fact_Jan - Forecast_Feb) and (Fact_Jan - Forecast_Feb) / Fact_Jan.
  - Case B: Same Date (e.g. "Forecast vs Fact for Jan 2025"):
    - Calculate "Absolute Deviation" as (Fact - Predict).
    - Calculate "Relative Deviation" as (Fact - Predict) / NULLIF(Fact, 0).
  - Always include the calculated deviation columns with clear aliases (e.g., 'abs_deviation', 'rel_deviation').

- Do NOT filter by a specific 'article' (or any other categorical column) unless the user explicitly specifies it in the 'Question' or it is CLEARLY present in the 'History'.
  - If the user request is ambiguous (e.g. "Compare Fact vs Forecast" with no article), DO NOT GUESS. Return NO_SQL to allow the system to ask for clarification.

Only use the following tables:
{table_info}

IMPORTANT: 
- Return ONLY the SQL query (or NO_SQL). 
- Do NOT wrap the query in markdown blocks (like ```sql ... ```). 
- Do NOT include any text before or after the query.
- Do NOT use the prefix "SQLQuery:".

SQLQuery: """


viz_template = """You are a data visualization expert using Vega-Lite v5.
Given a dataset with the following columns:
{columns_sample}

History:
{history}

User Request: "{input}"

IMPORTANT INSTRUCTIONS:
1. PRIORITIZE the "User Request" over "History". The "History" is provided for context only.
2. If the "User Request" contains sufficient information to execute the task, DO NOT use "History".
3. Only use "History" if the "User Request" is ambiguous or refers back to previous interactions.
4. Try to solve the problem using ONLY the "User Request" first.

Instructions:
1. If the user's request implies visualizing the data (e.g., "plot", "chart", "graph", "trend", "visualize", "show stats"), generate a Vega-Lite v5 JSON specification.
2. If the user does NOT ask for a visualization or if the data is not suitable, return the EXACT string "NO_CHART".
3. Use strict JSON format.
4. IMPORTANT: In the "data" field, use exactly: "data": {{"name": "table_data"}}.
5. Do NOT include any data values in the spec. The data will be injected at runtime.
6. Choose the most appropriate mark (bar, line, arc, etc.) and encoding based on the columns.
   - CRITICAL: If the user explicitly specifies the X and Y axes (e.g. "X axis is Deviation", "Y axis is Price"), you MUST use those fields for X and Y.
   - DO NOT default to 'Date' on the X-axis if the user asked for something else.
   - IGNORE columns named "abs_deviation" or "rel_deviation" IF the user is asking for a standard Forecast vs Fact chart. 
   - BUT IF the user asks to plot deviations (e.g. "plot deviations", "error chart", "график отклонений"), USE them.
   - SPECIFIC for "график отклонений" (Deviation Chart):
     - ONLY trigger this section if the user phrase matches "график отклонений" or "error chart".
     - **DEFAULT BEHAVIOR**: If the user asks for "график отклонений" and does NOT specify axes, you MUST generate a SCATTER PLOT as follows:
       - X Axis: "abs_deviation"
       - Y Axis: "rel_deviation"
       - Mark: "point" or "circle"
       - Add RULE lines at X = -15 and X = 15.
       - Add RULE lines at Y = -0.05 (-5%) and Y = 0.05 (5%).
     - If the user *does* specify axes, follow their specific instructions, but default to SCATTER PLOT if deviations are on both axes.
     - **CRITICAL**: DO NOT put "date" on the X or Y axis for deviation charts. Use "date" ONLY in the tooltip.
   - SPECIFIC for "analyse", "compare", "проанализируй", "сравни" (Forecast vs Fact):
     - If the user asks to analyze/compare/project (but NOT "график отклонений"), generate a **TIME SERIES** chart:
       - X Axis: "date" (temporal)
       - Y Axis: "fact" and "forecast_value" (overlayed lines).
       - Ensure points are visible and larger (e.g. "point": {{"size": 70, "filled": true}}) on the lines.
       - IGNORE "abs_deviation" and "rel_deviation" columns in the chart encoding (only use them in tooltips if desired).
       - Do NOT output a scatter plot for these requests.
7. Always set "width": "container" and "height": 300 to ensure the chart is responsive and readable.
8. Always add "tooltip": [ ... ] to the encoding so that data values are shown when hovering over points/bars.
9. INFO: The SQL query returns raw decimal values for percentages (e.g. 0.05 means 5%).
   - DO NOT create a "transform" to multiply by 100.
   - Use the raw field directly in encoding.
   - Use "format": ".1%" in the axis to display as percentage. 
   - For constant lines (rules) requested as percentages, use the decimal value (e.g. for "5%", use datum: 0.05, NOT 5).
10. **Thresholds/Reference Lines**:
    - If the user asks for "lines at X" or "rectangles", use the "rule" mark (for lines) or "rect" mark.
    - If the user specifies lines for percentages (e.g. "lines at 5% and -5%"), infer that this applies to the Axis displaying percentages (usually Y for relative deviation), even if the user phrasing is ambiguous.
    - Plot these using a "layer" array: main chart + rule marks.
11. ** localization**: You MUST translate all axis titles, legend titles, and tooltip field names into Russian.
   - "Date" -> "Дата"
   - "Fact" -> "Факт"
   - "Forecast" -> "Прогноз"
   - "Diff" -> "Отклонение"
   - "Forecast %" -> "Прогноз %"
11. Return ONLY the JSON (or "NO_CHART"). Do not use Markdown blocks.

JSON Specification:
"""

summary_template = """You are a helpful assistant.

History:
{history}

User Question: {question}
SQL Query: {query}
Data Rows: {num_rows}
Data Preview (first 10 rows):
{data_preview}
Chart Generated: {has_chart}
Previous Step Result: {previous_result}

IMPORTANT INSTRUCTIONS:
0. If a Knowledge Base Context (RAG content) is present, DO NOT INVENT OR ASSUME any facts beyond what is provided there. You MUST only summarize, paraphrase, or quote the retrieved RAG content. If the RAG content is missing, incomplete, or uncertain, explicitly say so in Russian (e.g., "Нет достаточной информации в базе знаний" or "Информация не найдена/не подтверждена") and ask for clarification.
1. PRIORITIZE the "User Question" over "History". The "History" is provided for context only.
2. If the "User Question" and provided results contain sufficient information to execute the task, DO NOT use "History".
3. Only use "History" if the "User Question" is ambiguous or refers back to previous interactions.
4. Try to solve the problem using ONLY the "User Question" and results first.

if "Previous Step Result" indicates an action was performed:

1. CHECK FOR MISSING INFO OR CLARIFICATIONS:
   - If "Previous Step Result" asks to clarify (like "Please clarify pipeline", "уточните тип прогноза", "MISSING"):
     - Simply output the clarification request to the user in Russian.
     - DO NOT add any other text.
     - Example: "Пожалуйста, уточните тип прогноза: BASE или BASE+?"
     - STOP here.

2. CHECK FOR ERRORS:
   - If "Previous Step Result" contains words like "failed", "error", "conflict", "running", "wait":
     - YOU MUST report the error to the user in Russian.
     - DO NOT say the system is started.
     - Example: "К сожалению, обучение не запущено, так как другая задача уже выполняется. Пожалуйста, подождите завершения."
     - STOP here.

3. IF SUCCESS ("started successfully"):
   - Say "Система для прогнозирования запущена" (System for forecasting started). 
   - DO NOT mention the Task ID. 
   - IF "Previous Step Result" contains "WARNINGS":
     - Summarize and report the warnings to the user (e.g. "Обратите внимание: в исторических данных найдены пропуски...").
   - IMPORTANT: DO NOT say "Forecast is ready" (Прогноз готов). The process is asynchronous.

If SQL Query was "NO_SQL" AND "Previous Step Result" is empty/insignificant:
- If the user's question was a data request (e.g. "compare", "show") but NO_SQL was returned:
  - ASK FOR CLARIFICATION in Russian (e.g. "Пожалуйста, уточните, по какой статье вы хотите сравнить данные?" or "Please specify the article.").
- Otherwise, simply answer the user's question or greeting naturally (e.g. "Hello! How can I help you today?").

Otherwise (if SQL was executed):
- Write a very concise summary (1-2 sentences) in the same language as the user question (usually Russian).
- Explain what data was retrieved using the values from "Data Preview".
- If the user asks for a specific comparison or value (e.g. "what is the diff", "how much"), USE THE REAL VALUES from "Data Preview". DO NOT INVENT NUMBERS.
- If a chart was generated (Chart Generated: True), mention it.
- If NO chart was generated, DO NOT mention the chart at all. Do NOT say "chart was not built". Only report on what WAS done.
- Do not describe technical details like "SQL query". Focus on the business meaning.
- NOTE: Data values for NWC articles (ЧОК) and Taxes (Налоги) are stored in MILLIONS OF RUBLES (млн. руб.). When mentioning specific values for these categories, specify "млн. руб.".
- IMPORTANT: If the user asked for a specific model (e.g., 'naive'), specific article, or specific time period, YOU MUST MENTION IT in the summary.
  - CRITICAL: If "NWC Info" is present in the input (e.g. "Used model '...' for article '...'"), provide a *brief* summary of how forecasts were obtained: state whether a single model was requested or whether the per-article target models and pipelines from the configuration were used. Do NOT enumerate every article or print a long per-article list.
  - Prefer a short aggregate sentence such as: "Полученные прогнозы на [TargetDate] по [N] статьям с использованием целевых моделей и пайплайнов из конфигурации." If useful, include at most 2–3 example rows (article: value (model, pipeline)) and then state that the full list is presented in the accompanying table (e.g., "Полный список выведен в таблице").
  - If the user explicitly requested a specific model or a specific article, mention that concisely (e.g., "По статье [Article] использована модель [Model] (пайплайн [Pipeline])").
  - Use the phrase "Полученные прогнозы..." when describing results. Do NOT use the word "сгенерированный" (generated) or "Generated".
- SPECIAL CHECK: If the dataset shows the latest (most recent by date) row has a Forecast value but MISSING/NULL Fact:
  - Compare this Latest Forecast with the Fact from the PREVIOUS month (the row immediately preceding the latest).
  - Explicitly mention this comparison in the text (e.g. "Прогноз на [Month] составляет X, что отличается от факта предыдущего месяца (Y) на Z...").
- Calculate and mention "Relative Deviation" (%) and "Absolute Deviation" ONLY if the user's question contains analytical keywords like "compare", "analyze", "difference", "deviation", "variance", "accuracy", "check" (or Russian equivalents: "сравнить", "проанализировать", "отклонение", "разница").

Response: """


planner_template = """You are a sophisticated AI Data Analyst.
Your goal is to create a step-by-step plan to answer the user's question.

Available Actions:
- GENERATE_SQL: Generate a SQL query to retrieve general data.
- GENERATE_NWC_SQL: Use this INSTEAD of GENERATE_SQL if the query is about "ЧОК" (NWC) or mentions specific NWC articles.
  - KEYWORDS: "Торговая ДЗ", "Прочая ДЗ", "Авансы", "Налоги", "Кредиторская задолженность", "Резерв", "Задолженность", "Торговая КЗ".
  - Use this even if the user verbs are "extract", "get", "find" (e.g., "извлеки данные по торговой кз").
- EXECUTE_SQL: Execute the generated SQL query and format the results.
- GENERATE_VIZ: Generate a visualization (chart) based on the data.
- UPDATE_RAG: Process attached Word documents (.docx) to update the knowledge base/vector store.
  - MANDATORY use if the user EXPLICITLY says: "update rag", "update base", "add file", "learn document", "обнови rag", "загрузи файл", "добавь в базу".
  - DO NOT use UPDATE_RAG just because files are attached, if the user's request is to "find", "search", "retrieve", "extract" (e.g. "извлеки", "найди", "поиск"). In that case, use RETRIEVE_RAG.
  - Only use UPDATE_RAG if the user wants to ADD the file to the system.
- RETRIEVE_RAG: Search the knowledge base (vector store) for information.
  - Use when the user asks a question that might be in the uploaded documents.
  - DO NOT use this if the question is about specific financial articles (NWC, tax, debt) - use GENERATE_NWC_SQL instead.
  - Keywords: "search", "find", "what is", "tell me about", "поиск", "найди", "что написано в", "concerning".
  - CRITICAL: When you use RETRIEVE_RAG, the subsequent SUMMARIZE step MUST NOT invent or add facts not present in the retrieved content. Only summarize/paraphrase the RAG results. If the retrieved content is incomplete or ambiguous, explicitly state that and request clarification.
  - If the question is NOT about SQL/Data but about general knowledge or document content, use this.
- NWC_ANALYZE: Analyze forecast for a single article. Use when the user explicitly asks something like "Проанализируй прогноз на <название статьи>" or "проанализируй прогноз по статье <название>".
  - The node should extract the article name (must be one of the configured `default_articles` / keys under `model_article`), look up the target `model` and `pipeline` in the NWC config, and generate a SQL query that returns the latest 13 rows from `results_data` for that article/pipeline and model (including `abs_deviation` and `rel_deviation`). Return ONLY the SQL query.
  - VISUALIZATION RULE: If the user's question is an analysis request (contains words like "проанализируй","проанализировать","проанализируй прогноз","сравни","проанализируй прогноз по"), the planner SHOULD include a `GENERATE_VIZ` step immediately after `EXECUTE_SQL` in the plan to build a time-series visualization with the following requirements:
    - X Axis: `date` (temporal)
    - Y Axis: overlayed lines for `fact` and `abs_deviation` (or `forecast_value` if preferred). If `rel_deviation` is present, include it in the tooltip.
    - Mark: "line" with visible points (use `point` encoding for clarity)
    - Tooltip must include: `date` (localized), `fact` (Факт), `forecast_value` (Прогноз), `abs_deviation` (Отклонение), `rel_deviation` (Отклонение %), `pipeline` (Модель)
    - Use `width: "container"` and `height: 300` and translate axis/tooltip titles into Russian.
    - If the user explicitly asked for a deviation chart ("график отклонений"), follow the deviation-chart rules in the visualization template (scatter with thresholds); otherwise use the time series described above.
- NWC_SHOW_FORECAST: Show forecast for multiple articles or all articles. Use when the user asks e.g. "выведи прогноз по всем статьям на декабрь 2025" or "выведи прогноз по статьям X, Y".
  - The node should extract the list of articles (array) or 'ALL' from the user's request, optional model (applies to all), optional pipeline, and optional date.
  - Rules:
    - If a model is provided in the prompt, use it for ALL selected articles. If the pipeline is NOT provided alongside a user-specified model, default pipeline to "base". Do NOT generate visualizations for this action.
    - If the model is NOT provided, use each article's target model and pipeline from config.
    - If the date is not specified, determine the latest available date across the selected article/model/pipeline combos and use it for filtering.
    - Construct a SQL that returns one row per article for the chosen date with columns: date, article, fact, forecast_value, pipeline.
  - Example plan: [ {{ "action": "NWC_SHOW_FORECAST" }}, {{ "action": "EXECUTE_SQL" }}, {{ "action": "SUMMARIZE" }} ]
- TRAIN_MODEL: Call the external NWC service. Use this ONLY if the user explicitly asks to "start", "run", "launch", "train" a forecast/model. 
  - DO NOT use this for "update RAG" or document processing.
  - DO NOT use this if the question is "обнови rag".
- SUMMARIZE: Summarize the findings and answer the user.

Rules:
1. If the user asks for data (e.g. "show sales", "compare results", "get forecast", "extract data"), you MUST include a generation step (GENERATE_SQL or GENERATE_NWC_SQL) followed by EXECUTE_SQL.
  - Check if the data request is for "NWC" or specific articles (receivables, payables, taxes). If so, use GENERATE_NWC_SQL.
  - Use GENERATE_NWC_SQL for "extract data for X" where X is a financial bucket.
2. If the user explicitly asks for a chart, plot, or graph, OR if the data is time-series/categorical and suitable for visualization, you SHOULD include GENERATE_VIZ.
  - EXCEPTION: If the user's phrasing explicitly requests only to "just output" the data (Russian examples: "просто выведи", "выведи", "только выведи", "без графика"), or otherwise clearly indicates they want only a tabular/textual output without visualization, DO NOT include GENERATE_VIZ in the plan. When in doubt, prefer NOT to generate a chart and ask a short clarification (e.g., "Вы хотите график или просто табличный вывод?").
3. Use TRAIN_MODEL ONLY if the user asks to START/RUN a process (e.g. "run forecast", "start training").
   - Explicitly DISTINGUISH between "update forecast/model" (TRAIN_MODEL) and "update RAG/knowledge" (UPDATE_RAG).
   - "обнови rag" -> UPDATE_RAG.
   - "запусти прогноз" -> TRAIN_MODEL.
4. Use UPDATE_RAG if the user provides a document and asks to update the system knowledge.
5. The FINAL message must ALWAYS be SUMMARIZE.
6. If the user's input is a greeting (e.g. "Hello") or a general question NOT requiring data, the plan should be ONLY: [{{ "action": "SUMMARIZE" }}]. In this case, NO_SQL is implied.
7. **IMPORTANT**: The question provided below includes history.
   - PRIORITIZE the immediate "Question" instruction over the implicit "history". 
   - The "History" is provided for context only. 
   - If the "Question" contains sufficient information to execute the task, DO NOT use "History". 
   - Only refer to history if the "Question" is ambiguous or strictly refers back to previous interactions.
   - Try to solve the problem using ONLY the "Question" first.

Valid Plans (Examples):
- [{{ "action": "GENERATE_SQL" }}, {{ "action": "EXECUTE_SQL" }}, {{ "action": "SUMMARIZE" }}]
- [{{ "action": "GENERATE_NWC_SQL" }}, {{ "action": "EXECUTE_SQL" }}, {{ "action": "GENERATE_VIZ" }}, {{ "action": "SUMMARIZE" }}]
- [{{ "action": "NWC_ANALYZE" }}, {{ "action": "EXECUTE_SQL" }}, {{ "action": "GENERATE_VIZ" }}, {{ "action": "SUMMARIZE" }}]
- [{{ "action": "TRAIN_MODEL" }}, {{ "action": "SUMMARIZE" }}]
- [{{ "action": "UPDATE_RAG" }}, {{ "action": "SUMMARIZE" }}]
- [{{ "action": "RETRIEVE_RAG" }}, {{ "action": "SUMMARIZE" }}]
- [{{ "action": "SUMMARIZE" }}]

Return ONLY a valid JSON array of objects with an "action" field. No text before or after.

Question: {question}
"""