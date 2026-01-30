from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain.chains import create_sql_query_chain
from sqlalchemy import create_engine
from core.config import settings

# Initialize Database engine and SQLDatabase
connect_args = {}
if settings.agent_database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.agent_database_url, connect_args=connect_args)
db = SQLDatabase(engine)

# Initialize shared LLM client
llm = ChatOpenAI(
    api_key=settings.deepseek_api_key or "dummy_key",
    base_url=settings.deepseek_base_url,
    model=settings.deepseek_model,
    temperature=0
)

# Helper factory for SQL chains
def create_sql_chain(prompt, k: int = 50):
    """Create a SQL query chain using the shared llm and db."""
    return create_sql_query_chain(llm, db, prompt=prompt, k=k)
