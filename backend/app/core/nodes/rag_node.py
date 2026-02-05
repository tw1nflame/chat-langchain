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
    """Process attached Word files and update the knowledge vector store (Qdrant).

    Description for planner/LLM summary:
    - Purpose: read attached Word (.docx/.doc) files from `state["files"]`, extract text, chunk it,
      and upload document vectors into the project's vector store for future retrieval.
    - Inputs:
      - state["files"]: list of file metadata (must include `path`, `name`).
      - state["owner_id"]: used for metadata tagging of inserted documents.
    - Outputs:
      - {"result": <message>} describing how many documents were added and any processing errors.
    - Side effects: writes new embeddings/documents into the vector store (persistent external effect).
    - Notes for plan confirmation: explicitly warn user that files will be uploaded and used to update the knowledge base; this is a persistent action and may be irreversible.
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
        chunk_size=500,
        chunk_overlap=100,
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
            for i, doc in enumerate(chunks):
                app_logger.info(f"CHUNK {i}:\n{doc.page_content}\n---")
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
    """Retrieve relevant knowledge base context for the user's question from the vector store.

    Description for planner/LLM summary:
    - Purpose: given `state["question"]`, perform a similarity search in the vector store and return
      a concatenated context string (top-k documents) suitable to include in downstream LLM prompts.
    - Inputs:
      - state["question"]: natural language query to search the KB for.
    - Outputs:
      - {"rag_context": <string>} containing formatted snippets from the most relevant documents or
        an explanatory message when nothing is found.
    - Side effects: none (read-only retrieval).
    - Notes for plan confirmation: the summary should state that this step will fetch contextual documents to reduce hallucinations and inform the final answer.
    """
    app_logger.info("retrieve_rag_node: processing")
    
    question = state.get("question", "")
    if not question:
         return {"rag_context": ""}

    try:
        vector_store = get_vector_store()
        # Search for top k relevant documents
        # We can make k configurable via settings if needed
        docs = vector_store.similarity_search(question, k=15)

        for i, doc in enumerate(docs):
            app_logger.info(f"CHUNK {i}:\n{doc.page_content}\n---")
        
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

