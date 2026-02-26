# AI Agent Instructions for Chat-LangChain Project

## Architecture Overview

This is a chat application featuring a **LangGraph-powered AI agent** that performs SQL analysis, forecasting, and RAG-based document retrieval. The system uses a **split-database architecture** with separate databases for application data and authentication.

### Technology Stack
- **Backend**: FastAPI + LangChain/LangGraph + SQLAlchemy + Qdrant (vector DB)
- **Frontend**: Next.js (React) + Supabase Auth
- **LLM**: DeepSeek API (configurable via `.env`)
- **Embeddings**: Ollama/Xinference (local embeddings service)
- **External**: NWC forecasting service (separate microservice)

### Key Components
- **Agent Graph** ([agent_graph.py](backend/app/core/agent_graph.py)): LangGraph state machine orchestrating multi-step workflows (planning → execution → visualization → summarization)
- **Node System** ([core/nodes/](backend/app/core/nodes/)): Modular action nodes including SQL generation, NWC analysis, RAG updates, model training triggers
- **Chat API** ([api/chat.py](backend/app/api/chat.py)): REST endpoints for chat CRUD, message streaming, file uploads, plan confirmation
- **Vector Store** ([vector_store.py](backend/app/core/vector_store.py)): Qdrant-based RAG with local persistence

## Critical Patterns

### 1. Split-Database Architecture
The system supports **two separate databases**:
- **Application DB** (`DATABASE_URL`): Stores chats, messages, files, charts
- **Auth DB** (`SUPABASE_URL`): Provider-managed Supabase auth (read-only from app perspective)
- **Agent Query DB** (`AGENT_DATABASE_URL`): Business data for SQL queries (may differ from app DB)

**⚠️ Critical**: The `User` model ([models/chat.py](backend/app/models/chat.py#L27-L39)) maps `auth.users` as **read-only**. An ORM listener prevents writes. Never attempt INSERT/UPDATE/DELETE on User objects.

### 2. Human-in-the-Loop Confirmation
The agent implements a **pause-resume workflow** ([nodes/confirm_node.py](backend/app/core/nodes/confirm_node.py)):
1. Planner generates multi-step plan
2. System pauses and returns `awaiting_confirmation: true` with human-readable summary
3. User approves/cancels via `/api/v1/confirm/{plan_id}` endpoint
4. On approval, agent resumes from saved checkpoint (using LangGraph's MemorySaver)

**Key state fields**: `awaiting_confirmation`, `plan_id`, `resuming`, `confirmed_by`, `temporary_session` (skip confirmation for ephemeral sessions)

### 3. NWC (Net Working Capital) Domain Logic
The system specializes in **financial forecasting** for specific articles (receivables, payables, etc.):
- **NWC-specific nodes**: `nwc_query_generator`, `nwc_analyze`, `nwc_show_forecast`, `call_nwc_train`
- **Article-aware routing**: Use `GENERATE_NWC_SQL` instead of `GENERATE_SQL` for NWC queries (see [planner templates](backend/app/core/templates/agent_templates.py))
- **External service**: POST to `NWC_SERVICE_URL` for model training ([nwc_train_node.py](backend/app/core/nodes/nwc_train_node.py))

**⚠️ Data units**: NWC and Tax values are in **millions of rubles (млн. руб.)** — mention units in summaries.

### 4. Parquet-Based Table Storage
Large result tables are **not stored in the database**. Instead:
- Tables are saved as `.parquet` files in `backend/storage/{owner_id}/{message_id}/` ([storage_utils.py](backend/app/utils/storage_utils.py))
- Frontend downloads via `/api/v1/message/{message_id}/table/{table_index}/download` (returns Excel)
- On message deletion, parquet files are cleaned up via `delete_tables_for_message()`

### 5. Authentication Flow
- Frontend uses **Supabase client-side auth** ([supabaseClient.jsx](frontend/src/lib/supabaseClient.jsx))
- Backend validates **JWT bearer tokens** by calling `{SUPABASE_URL}/auth/v1/user` ([deps.py](backend/app/api/deps.py#L7-L56))
- Every API request must include `Authorization: Bearer <token>` header
- Owner ID (Supabase user UUID) is extracted from token and used for multi-tenancy

**⚠️ Development**: If `SUPABASE_URL` is unset, auth is **disabled** and requests will fail with 401.

## Development Workflows

### Local Setup
1. **Backend**:
   ```bash
   cd backend
   # Configure .env (see backend/.env for template)
   pip install -r requirements.txt
   cd app
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
2. **Frontend**:
   ```bash
   cd frontend
   pnpm install
   pnpm dev  # Runs on port 5173 (Vite) or 3000 (Next.js)
   ```
3. **Vector Store**: Ensure Ollama/Xinference is running at `EMBEDDING_BASE_URL` (default: `http://localhost:11434`)
4. **Database**: Run Postgres locally or use SQLite (default). Set `DATABASE_URL` in `.env`.

### Docker Deployment
- **Backend Dockerfile** ([backend/Dockerfile](backend/Dockerfile)): Python 3.11-slim, installs deps, runs uvicorn on port 8000
- **Storage volume**: Mount `/code/storage` to persist file uploads and parquet tables
- **Working directory**: `/code/app` (important for relative imports)

### Environment Variables (Critical)
See [config.py](backend/app/core/config.py) for all settings. Key vars:
- `DATABASE_URL`, `AGENT_DATABASE_URL` (split DB support)
- `SUPABASE_URL`, `SUPABASE_ANON_KEY` (auth)
- `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` (LLM)
- `NWC_SERVICE_URL` (external forecasting service)
- `QDRANT_PATH`, `QDRANT_COLLECTION_NAME` (vector DB)
- `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL` (RAG embeddings)
- `CORS_ORIGINS` (comma-separated list)
- `CREATE_TABLES_ON_STARTUP` (auto-migrate DB on start)

## Code Conventions

### 1. Logging
- Use structured logging via `app_logger` ([logging_config.py](backend/app/core/logging_config.py))
- **Redact auth tokens**: Always use `<REDACTED>` for `Authorization`, `Cookie`, and `apikey` headers
- Include `request_id` for request correlation (see [chat.py#L98-L111](backend/app/api/chat.py#L98-L111))
- **Russian language**: Many log messages and comments are in Russian (project convention)

### 2. Error Handling
- Use `HTTPException` for HTTP errors (FastAPI standard)
- Rollback DB transactions in exception handlers ([database.py#L17-L21](backend/app/core/database.py#L17-L21))
- Log exceptions with `app_logger.exception()` for full stack traces

### 3. Graph Node Patterns
Each node in [core/nodes/](backend/app/core/nodes/) should:
- Accept `GraphState` dict as input
- Return dict with partial state updates (LangGraph merges automatically)
- Include docstring describing purpose, inputs, outputs, and side effects (used for plan confirmation summaries)
- Log entry/exit with `app_logger.info()`

Example node structure:
```python
def my_node(state: GraphState):
    """Brief description of what this node does."""
    app_logger.info("my_node: starting")
    # ... logic ...
    return {"result": "output", "next_action": "next_node_name"}
```

### 4. Model Serialization
Use custom `_serialize_chat()` and `_serialize_message()` helpers (see [chat.py#L43-L68](backend/app/api/chat.py#L43-L68)) to safely handle nullable fields and UUID conversion.

## Integration Points

### DeepSeek LLM
- Configured via `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`
- Shared LLM instance in [shared_resources.py](backend/app/core/nodes/shared_resources.py) (uses LangChain's ChatOpenAI with custom base URL)
- Used in planner, SQL generation, summarization, and visualization nodes

### NWC Training Service
- External HTTP service at `NWC_SERVICE_URL`
- POST to `/train` endpoint with JSON body: `{"model": "...", "article": "...", "params": {...}}`
- Returns task_id for async job tracking (see [nwc_train_node.py](backend/app/core/nodes/nwc_train_node.py))

### Qdrant Vector Store
- Local disk-based persistence at `QDRANT_PATH` (default: `./qdrant_data`)
- **Monkey patch** in [vector_store.py#L12-L16](backend/app/core/vector_store.py#L12-L16) fixes langchain-qdrant version mismatch (skip collection validation)
- Collection auto-created on startup with dynamic vector dimension from embeddings service

## Debugging Tips

1. **Auth issues**: Check stdout for `[DEBUG] incoming_request` logs showing `supabase_url_configured` and redacted headers
2. **Plan not executing**: Verify `awaiting_confirmation=false` and `resuming=true` in state after confirmation
3. **Vector store init fails**: Ensure embedding service is running; check `EMBEDDING_BASE_URL` connectivity
4. **Parquet file missing**: Check `backend/storage/{owner_id}/` directory exists and has write permissions
5. **LangGraph loops**: Enable debug logging to trace `next_action` routing in [agent_graph.py](backend/app/core/agent_graph.py)

## Quick Reference

- **Add new node**: Create in `core/nodes/`, add to `builder.add_node()` in [agent_graph.py](backend/app/core/agent_graph.py#L83-L100), document in planner templates
- **Add API endpoint**: Create router in `api/`, include in [main.py](backend/app/main.py#L39-L40)
- **Modify DB schema**: Edit models in [models/chat.py](backend/app/models/chat.py), restart with `CREATE_TABLES_ON_STARTUP=true`
- **Update frontend API client**: Edit [frontend/src/api/](frontend/src/api/) – uses fetch with Supabase session tokens
- **Change LLM provider**: Update `shared_resources.py` LLM initialization (currently hardcoded to OpenAI-compatible API)
