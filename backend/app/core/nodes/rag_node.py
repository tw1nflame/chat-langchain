import os
import logging
from typing import Dict, Any, List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from core.vector_store import get_vector_store
from core.config import settings
import docx
from markitdown import MarkItDown

app_logger = logging.getLogger("uvicorn")

def load_docx(file_path: str) -> str:
    """Extract text from a .docx file."""
    md = MarkItDown()
    result = md.convert(file_path)
    return result.text_content

def update_rag_node(state: Dict[str, Any]):
    """
    Node to process attached Word files and update the Qdrant vector store.
    """
    app_logger.info("update_rag_node: processing")

    if not settings.enable_rag_update:
        app_logger.info("update_rag_node: RAG update is disabled via config")
        return {"result": "Обновление базы знаний временно отключено администратором."}
    
    files = state.get("files", [])
    if not files:
        app_logger.warning("update_rag_node: No files found")
        return {"result": "Нет прикрепленных файлов для обновления базы знаний."}
    
    documents = []
    processed_files = []
    errors = []
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        is_separator_regex=False
    )
    
    # Initialize Vector Store
    try:
        vector_store = get_vector_store()
    except Exception as e:
        app_logger.error(f"Failed to initialize vector store: {e}")
        return {"result": f"Ошибка инициализации базы данных: {str(e)}"}
    
    for file_info in files:
        file_path = file_info.get("path")
        file_name = file_info.get("name", "unknown")
        
        if not file_path or not os.path.exists(file_path):
            app_logger.warning(f"File not found: {file_path}")
            continue
            
        # Check extension
        if not file_name.lower().endswith(('.docx', '.doc')):
            app_logger.info(f"Skipping non-word file: {file_name}")
            continue
            
        try:
            app_logger.info(f"Processing file: {file_name}")
            text_content = load_docx(file_path)
            
            if not text_content.strip():
                app_logger.warning(f"File is empty: {file_name}")
                continue
                
            # Create chunks
            chunks = text_splitter.create_documents(
                [text_content], 
                metadatas=[{
                    "source": file_name, 
                    "owner_id": state.get("owner_id", "unknown"),
                    "type": "docx"
                }]
            )
            documents.extend(chunks)
            processed_files.append(file_name)
            
        except Exception as e:
            msg = f"Error processing {file_name}: {e}"
            app_logger.error(msg)
            errors.append(msg)
            
    if not documents:
        if errors:
            return {"result": f"Не удалось обработать файлы. Ошибки: {'; '.join(errors)}"}
        return {"result": "Не найдено валидных Word (.docx) файлов для обработки."}
        
    try:
        app_logger.info(f"Adding {len(documents)} document chunks to Vector Store...")
        vector_store.add_documents(documents)
        app_logger.info("Vector Store updated successfully.")
        
        result_msg = f"База знаний успешно обновлена. Добавлено документов: {len(processed_files)} ({', '.join(processed_files)})."
        if errors:
            result_msg += f"\nОшибки при обработке других файлов: {'; '.join(errors)}"
            
        return {"result": result_msg}
        
    except Exception as e:
        app_logger.error(f"Failed to update vector store: {e}")
        return {"result": f"Ошибка обновления базы знаний: {str(e)}"}


def retrieve_rag_node(state: Dict[str, Any]):
    """
    Node to retrieve context from the Qdrant vector store based on the question.
    """
    app_logger.info("retrieve_rag_node: processing")
    
    question = state.get("question", "")
    if not question:
         return {"rag_context": ""}

    try:
        vector_store = get_vector_store()
        # Search for top k relevant documents
        # We can make k configurable via settings if needed
        docs = vector_store.similarity_search(question, k=5)
        
        if not docs:
            app_logger.info("retrieve_rag_node: No relevant documents found.")
            return {"rag_context": "No relevant documents found in knowledge base."}
            
        # Format retrieval
        context_parts = []
        for i, doc in enumerate(docs):
             source = doc.metadata.get("source", "unknown")
             content = doc.page_content.strip()
             context_parts.append(f"[Document {i+1} (Source: {source})]:\n{content}")
             
        rag_context = "\n\n".join(context_parts)
        app_logger.info(f"retrieve_rag_node: Retrieved {len(docs)} docs. Context length: {len(rag_context)}")
        
        return {"rag_context": rag_context}
        
    except Exception as e:
        app_logger.error(f"retrieve_rag_node: Error during retrieval: {e}")
        return {"rag_context": f"Error retrieving knowledge: {str(e)}"}

