template = """Given an input question, decide if it requires a database query.
If the question is just a greeting, a general conversational remark, or does not imply data retrieval (e.g. "Hello", "Thanks", "Who are you?"), return exactly: NO_SQL

Otherwise, create a syntactically correct {dialect} query to run.
Unless the user specifies a specific number of examples to obtain, query for at most {top_k} results.
Never query for all the columns from a specific table, only ask for the relevant columns given the question.
Pay attention to use only the column names you can see in the schema description. Be careful to not query for columns that do not exist.
Pay attention to which column is in which table. Also, qualify column names with the table name when needed.

If the question is in a different language (e.g., Russian) than the database schema (e.g., English), 
you MUST map the terms in the question to the closest matching column names in the schema.
Do NOT simply transcribe the non-English terms as column names. 
Example: "разница по прогнозу naive" -> "predict_naive_diff" (if available).

IMPORTANT: If calculating a ratio or percentage, return the raw decimal value (e.g. 0.05 for 5%). 
Do NOT multiply by 100 in the SQL query (e.g., do NOT use `* 100`).

Only use the following tables:
{table_info}

Question: {input}

IMPORTANT: 
- Return ONLY the SQL query (or NO_SQL). 
- Do NOT wrap the query in markdown blocks (like ```sql ... ```). 
- Do NOT include any text before or after the query.
- Do NOT use the prefix "SQLQuery:".

SQLQuery: """


viz_template = """You are a data visualization expert using Vega-Lite v5.
Given a dataset with the following columns:
{columns_sample}

And the user request: "{input}"

Instructions:
1. If the user's request implies visualizing the data (e.g., "plot", "chart", "graph", "trend", "visualize", "show stats"), generate a Vega-Lite v5 JSON specification.
2. If the user does NOT ask for a visualization or if the data is not suitable, return the EXACT string "NO_CHART".
3. Use strict JSON format.
4. IMPORTANT: In the "data" field, use exactly: "data": {{"name": "table_data"}}.
5. Do NOT include any data values in the spec. The data will be injected at runtime.
6. Choose the most appropriate mark (bar, line, arc, etc.) and encoding based on the columns.
7. Always set "width": "container" and "height": 300 to ensure the chart is responsive and readable.
8. Always add "tooltip": [ ... ] to the encoding so that data values are shown when hovering over points/bars.
9. INFO: The SQL query returns raw decimal values for percentages (e.g. 0.05 means 5%).
   - DO NOT create a "transform" to multiply by 100.
   - Use the raw field directly in encoding.
   - Use "format": ".1%" in the axis to display as percentage. 
   - For constant lines (rules) requested as percentages, use the decimal value (e.g. for "5%", use datum: 0.05, NOT 5).
10. Return ONLY the JSON (or "NO_CHART"). Do not use Markdown blocks.

JSON Specification:
"""

summary_template = """You are a helpful assistant.
User Question: {question}
SQL Query: {query}
Data Rows: {num_rows}
Chart Generated: {has_chart}

If SQL Query was "NO_SQL", simply answer the user's question or greeting naturally (e.g. "Hello! How can I help you today?").

Otherwise, write a very concise summary (1-2 sentences) in the same language as the user question (usually Russian).
Explain what data was retrieved.
If a chart was generated (Chart Generated: True), mention it.
If NO chart was generated, DO NOT mention the chart at all. Do NOT say "chart was not built". Only report on what WAS done.
Do not describe technical details like "SQL query". Focus on the business meaning.
IMPORTANT: If the user asked for a specific model (e.g., 'naive'), specific article, or specific time period, YOU MUST MENTION IT in the summary.
Example (chart built): "I retrieved sales data for 2024 and plotted the trend."
Example (no chart): "I retrieved sales data for 2024."
Response: """


planner_template = """You are a sophisticated AI Data Analyst.
Your goal is to create a step-by-step plan to answer the user's question.

Available Actions:
- GENERATE_SQL: Generate a SQL query to retrieve data.
- EXECUTE_SQL: Execute the generated SQL query and format the results.
- GENERATE_VIZ: Generate a visualization (chart) based on the data.
- SUMMARIZE: Summarize the findings and answer the user.

Rules:
1. If the user asks for data (e.g. "show sales", "how many users"), you MUST include GENERATE_SQL and EXECUTE_SQL.
2. If the user explicitly asks for a chart, plot, or graph, OR if the data is time-series/categorical and suitable for visualization, you SHOULD include GENERATE_VIZ.
3. The FINAL message must ALWAYS be SUMMARIZE.
4. If the user's input is a greeting (e.g. "Hello") or a general question NOT requiring data, the plan should be ONLY: [{{ "action": "SUMMARIZE" }}]. In this case, NO_SQL is implied.

Valid Plans (Examples):
- [{{ "action": "GENERATE_SQL" }}, {{ "action": "EXECUTE_SQL" }}, {{ "action": "SUMMARIZE" }}]
- [{{ "action": "GENERATE_SQL" }}, {{ "action": "EXECUTE_SQL" }}, {{ "action": "GENERATE_VIZ" }}, {{ "action": "SUMMARIZE" }}]
- [{{ "action": "SUMMARIZE" }}]

Return ONLY a valid JSON array of objects with an "action" field. No text before or after.

Question: {question}
"""