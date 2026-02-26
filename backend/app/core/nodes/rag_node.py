import os
import logging
import re
from typing import Dict, Any, List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from core.vector_store import get_vector_store
from core.config import settings
from markitdown import MarkItDown
import pymupdf4llm 


app_logger = logging.getLogger("uvicorn")

def load_file_content(file_path: str) -> str:
    """Умная загрузка: DOCX через MarkItDown, PDF через PyMuPDF4LLM."""
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.pdf':
        try:
            # pymupdf4llm конвертирует PDF сразу в Markdown, 
            # пытаясь сохранить таблицы и распознать колонки.
            # write_images=False, чтобы не сохранять картинки на диск
            md_text = pymupdf4llm.to_markdown(file_path, write_images=False) 
            return md_text
        except Exception as e:
            app_logger.error(f"PyMuPDF failed on {file_path}: {e}")
            # Fallback (запасной вариант)
            md = MarkItDown()
            return md.convert(file_path).text_content
            
    else:
        # Для DOCX MarkItDown работает нормально
        md = MarkItDown()
        result = md.convert(file_path)
        return result.text_content

def clean_text(text: str) -> str:
    """Очистка текста."""
    # 1. Убираем странные маркеры списков
    text = text.replace("* + -", "- ")
    
    # 2. Убираем колонтитулы (Эвристика для вашего отчета)
    # Удаляем строки типа "40 ♀ГОРНО-МЕТАЛЛУРГИЧЕСКАЯ..."
    # Регулярка ищет: Новая строка + Цифры + Пробел + Спецсимвол + ГОРНО...
    text = re.sub(r'\n\d+\s+♀?ГОРНО-МЕТАЛЛУРГИЧЕСКАЯ.*?\n', '\n', text)
    
    # 3. Убираем "женский символ" (артефакт кодировки)
    text = text.replace("♀", "")
    
    # 4. Схлопываем пробелы
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text

def split_markdown_with_tables(text: str, chunk_size: int, chunk_overlap: int):
    """
    Разделяет текст на чанки, сохраняя Markdown-таблицы целыми.
    """
    # 1. Инициализируем стандартный сплиттер для ОБЫЧНОГО текста
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n## ", "\n### ", "\n\n", "\n", ". "],
        keep_separator=True
    )

    lines = text.split('\n')
    final_chunks = []
    
    current_buffer = []
    is_inside_table = False
    
    # Регулярка для определения строки таблицы Markdown (начинается и заканчивается |)
    table_line_pattern = re.compile(r'^\s*\|.*\|\s*$')

    for line in lines:
        # Проверяем, похожа ли строка на часть таблицы
        if table_line_pattern.match(line):
            if not is_inside_table:
                # НАЧАЛО ТАБЛИЦЫ
                # 1. Сбрасываем накопившийся обычный текст в чанки
                if current_buffer:
                    text_block = "\n".join(current_buffer)
                    final_chunks.extend(text_splitter.split_text(text_block))
                    current_buffer = []
                is_inside_table = True
            
            # Добавляем строку таблицы в буфер
            current_buffer.append(line)
        else:
            if is_inside_table:
                # КОНЕЦ ТАБЛИЦЫ
                # 1. Сохраняем всю таблицу как ОДИН чанк
                table_block = "\n".join(current_buffer)
                final_chunks.append(table_block)
                current_buffer = []
                is_inside_table = False
            
            # Добавляем обычную строку в буфер
            current_buffer.append(line)

    # Обработка остатка после цикла
    if current_buffer:
        block = "\n".join(current_buffer)
        if is_inside_table:
            # Если файл закончился таблицей
            final_chunks.append(block)
        else:
            # Если файл закончился текстом
            final_chunks.extend(text_splitter.split_text(block))

    return final_chunks

def update_rag_node(state: Dict[str, Any]):
    app_logger.info("update_rag_node: processing")

    if not settings.enable_rag_update:
        return {"result": "RAG update disabled."}
    
    files = state.get("files", [])
    if not files:
        return {"result": "No files."}
    
    documents = []
    processed_files = []
    errors = []
    
    try:
        vector_store = get_vector_store()
    except Exception as e:
        return {"result": f"DB Error: {str(e)}"}
    
    for file_info in files:
        file_path = file_info.get("path")
        file_name = file_info.get("name", "unknown")
        
        if not file_path or not os.path.exists(file_path):
            continue
            
        ext = os.path.splitext(file_name)[1].lower()
        if ext not in ['.docx', '.doc', '.pdf']:
            continue
            
        try:
            app_logger.info(f"Processing file: {file_name}")
            raw_text = load_file_content(file_path)
            
            # ОЧИСТКА
            text_content = clean_text(raw_text)
            
            if not text_content.strip():
                continue
                
            # --- ИЗМЕНЕНИЕ: ИСПОЛЬЗУЕМ НОВУЮ ЛОГИКУ ЧАНКИНГА ---
            # chunk_size можно увеличить, так как таблицы бывают широкими
            text_chunks = split_markdown_with_tables(
                text_content, 
                chunk_size=1200, 
                chunk_overlap=150
            )
            
            # Превращаем строки обратно в объекты Document
            file_docs = []
            for chunk in text_chunks:
                # Можно добавить проверку: если чанк слишком маленький (например, заголовок таблицы без данных), пропускаем
                if len(chunk.strip()) < 10: 
                    continue
                    
                file_docs.append(Document(
                    page_content=chunk,
                    metadata={
                        "source": file_name, 
                        "owner_id": state.get("owner_id", "unknown"),
                        "type": ext.lstrip('.')
                    }
                ))
            
            for i, doc in enumerate(file_docs):
                # Логируем первые 50 символов чанка, чтобы не засорять лог
                app_logger.info(f"CHUNK {i} \n{doc.page_content}")
                
            documents.extend(file_docs)
            processed_files.append(file_name)
            
        except Exception as e:
            app_logger.error(f"Error {file_name}: {e}")
            errors.append(str(e))
            
    if not documents:
        return {"result": "No valid documents."}
        
    try:
        app_logger.info(f"Adding {len(documents)} chunks to Vector Store...")
        vector_store.add_documents(documents)
        return {"result": f"Added {len(processed_files)} files ({len(documents)} chunks)."}
        
    except Exception as e:
        return {"result": f"Vector Store Error: {str(e)}"}


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
        
        filter_condition = None
        # Custom logic for Nornickel
        if "норникель" in question.lower():
            try:
                from qdrant_client.http import models as rest
                filter_condition = rest.Filter(
                    must=[
                        rest.FieldCondition(
                            key="metadata.source",
                            match=rest.MatchValue(value="ifrs_rus_rub_consolidation_reporting_simplified2.pdf")
                        )
                    ]
                )
                app_logger.info("retrieve_rag_node: Applied Nornickel filter")
            except Exception as ex:
                 app_logger.warning(f"retrieve_rag_node: Could not create filter: {ex}")

        # Search for top k relevant documents
        # We can make k configurable via settings if needed
        docs = vector_store.similarity_search(question, k=15, filter=filter_condition)

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

