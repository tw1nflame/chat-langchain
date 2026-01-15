import os
import pandas as pd
import glob
from typing import List, Dict, Any, Optional
import logging

app_logger = logging.getLogger(__name__)

def get_storage_path() -> str:
    """Returns the base path for storage."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage")

def get_tables_dir() -> str:
    """Returns the directory where parquet tables are stored."""
    path = os.path.join(get_storage_path(), "tables")
    os.makedirs(path, exist_ok=True)
    return path

def save_table_parquet(data_rows: List[List[Any]], headers: List[str], message_id: str, table_index: int) -> str:
    """
    Saves a table to a Parquet file.
    Returns the full file path.
    """
    try:
        df = pd.DataFrame(data_rows, columns=headers)
        # Ensure all columns are strings to avoid parquet type issues with mixed types
        df = df.astype(str)
        
        tables_dir = get_tables_dir()
        filename = f"{message_id}_{table_index}.parquet"
        file_path = os.path.join(tables_dir, filename)
        
        df.to_parquet(file_path, index=False)
        return file_path
    except Exception as e:
        app_logger.error(f"Failed to save parquet table: {e}")
        raise

def load_tables_for_message(message_id: str) -> List[Dict[str, Any]]:
    """
    Loads all tables associated with a message_id from Parquet files.
    Returns a list of dictionaries with 'headers' and 'rows'.
    """
    tables_dir = get_tables_dir()
    pattern = os.path.join(tables_dir, f"{message_id}_*.parquet")
    files = glob.glob(pattern)
    
    # Sort files numerically by the index in the filename
    # Filename format: {message_id}_{index}.parquet
    def extract_index(path):
        try:
            filename = os.path.basename(path)
            # Remove extension
            name_no_ext = os.path.splitext(filename)[0]
            # Split by last underscore (handling message_id effectively)
            parts = name_no_ext.rsplit('_', 1)
            if len(parts) == 2:
                return int(parts[1])
            return -1
        except ValueError:
            return -1

    files = sorted(files, key=extract_index)
    
    tables = []
    for i, file_path in enumerate(files):
        try:
            # We trust the file index is correct, but we return them in sorted order.
            # The download logic relies on the index encoded in filename, 
            # OR we can assume the output index i matches if we sorted correctly.
            
            # Using the actual index from filename for the 'index' field is safer
            real_index = extract_index(file_path)
            
            df = pd.read_parquet(file_path)
            table_data = {
                "headers": df.columns.tolist(),
                "rows": df.values.tolist(),
                "title": f"Table {real_index + 1}",
                "index": real_index 
            }
            tables.append(table_data)
        except Exception as e:
            app_logger.error(f"Failed to load parquet file {file_path}: {e}")
            
    return tables

def get_table_as_excel_stream(message_id: str, table_index: int):
    """
    Loads a specific parquet table and converts it to an bytes stream (Excel format)
    Returns: BytesIO object or None if not found
    """
    import io
    tables_dir = get_tables_dir()
    # Flexible matching for index, though we save as {message_id}_{index}.parquet
    # We might need to match exactly how we listed them.
    # We used glob sorted above.
    
    # Try direct match first
    filename = f"{message_id}_{table_index}.parquet"
    file_path = os.path.join(tables_dir, filename)
    
    if not os.path.exists(file_path):
        # Fallback: try finding by sorted index if naming schema changed
        pattern = os.path.join(tables_dir, f"{message_id}_*.parquet")
        files = sorted(glob.glob(pattern))
        if 0 <= table_index < len(files):
            file_path = files[table_index]
        else:
            return None
            
    try:
        df = pd.read_parquet(file_path)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sheet1')
        output.seek(0)
        return output
    except Exception as e:
        app_logger.error(f"Failed to convert parquet to excel: {e}")
        return None

def delete_tables_for_message(message_id: str):
    """Deletes all parquet files for a message."""
    tables_dir = get_tables_dir()
    pattern = os.path.join(tables_dir, f"{message_id}_*.parquet")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError as e:
            app_logger.error(f"Error checking/deleting file {f}: {e}")
