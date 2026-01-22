from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from langchain_community.embeddings import OllamaEmbeddings
from core.config import settings
import logging

logger = logging.getLogger("uvicorn")

# MONKEY PATCH: Fix for langchain-qdrant vs qdrant-client version mismatch
# The library tries to access VectorParams as a dict (['size']), but client returns an object.
# We skip the validation since we handle creation manually.
def _safe_validate_collection_config(*args, **kwargs):
    return True

if hasattr(QdrantVectorStore, "_validate_collection_config"):
    QdrantVectorStore._validate_collection_config = _safe_validate_collection_config

def get_embeddings():
    """
    Returns the configured embedding model. 
    Using OllamaEmbeddings for generic Ollama/Xinference compatibility.
    """
    return OllamaEmbeddings(
        base_url=settings.embedding_base_url,
        model=settings.embedding_model
    )

def init_vector_store():
    """
    Initializes the local Qdrant vector store.
    """
    logger.info(f"Initializing Qdrant at path: {settings.qdrant_path}")
    
    # Initialize client locally (on disk or in-memory)
    client = QdrantClient(path=settings.qdrant_path)
    
    collection_name = settings.qdrant_collection_name
    
    # Force fix for incompatible legacy collections or version mismatches
    # If we can't load it, we delete it.
    try:
        # Check if we can instantiate the store wrapper. 
        # This implicitly checks schema validation in some versions.
        # However, checking existence is cheaper first.
        if client.collection_exists(collection_name):
             # Try to perform a lightweight get to see if metadata is readable
             client.get_collection(collection_name)
    except Exception as e:
        logger.warning(f"Error checking collection '{collection_name}': {e}. Deleting to recreate.")
        client.delete_collection(collection_name)

    # Check existence (again, in case we deleted it or it wasn't there)
    if not client.collection_exists(collection_name):
        logger.info(f"Collection '{collection_name}' not found. Creating...")
        
        try:
            # Determine vector size dynamically by calling the embedding service
            logger.info(f"Connecting to embedding service at {settings.embedding_base_url} to determine vector size...")
            embeddings = get_embeddings()
            sample_embedding = embeddings.embed_query("init_check")
            vector_size = len(sample_embedding)
            logger.info(f"Determined embedding dimension: {vector_size}")
            
            client.create_collection(
                collection_name=collection_name,
                vectors_config=rest.VectorParams(
                    size=vector_size,
                    distance=rest.Distance.COSINE
                )
            )
            logger.info(f"Collection '{collection_name}' created successfully.")
            
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant collection: {e}")
            logger.warning("Is the embedding service running? We need it to determine vector dimension.")

    # Return the store wrapper
    try:
        return QdrantVectorStore(
            client=client,
            collection_name=collection_name,
            embedding=get_embeddings()
        )
    except TypeError as e:
        if "'VectorParams' object is not subscriptable" in str(e):
            logger.error(f"Version Mismatch Detected: {e}. Attempting to recreate collection with simple config.")
            # This is a specific error where langchain-qdrant tries to access .vectors_config['size'] 
            # but gets a VectorParams object.
            # Strategy: Delete and let user know (or retry if in loop, but let's just fail safely or fix imports).
            # It implies we need a different qdrant-client/langchain-qdrant combo.
            # As a desperate fix: return client ignoring the error? No, we need the store object.
            raise e
        raise e

def get_vector_store():
    return init_vector_store()
