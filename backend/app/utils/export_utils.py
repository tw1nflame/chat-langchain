import pandas as pd
import uuid
import os
from typing import List, Dict, Any

def ensure_export_directory() -> str:
    """Creates the exports directory if it doesn't exist and returns the path."""
    storage_base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage")
    export_dir = os.path.join(storage_base, "exports")
    os.makedirs(export_dir, exist_ok=True)
    return export_dir

def save_dataframe_to_excel(rows: List[Any], headers: List[str], owner_id: str) -> str:
    """Saves data to an Excel file and returns the filename."""
    export_dir = ensure_export_directory()
    # Embed owner_id in filename for basic access control
    # Sanitize owner_id just in case (though usually it's a UUID)
    safe_owner_id = str(owner_id).replace(os.sep, "_")
    filename = f"export_{safe_owner_id}_{uuid.uuid4()}.xlsx"
    file_path = os.path.join(export_dir, filename)
    
    df = pd.DataFrame(rows, columns=headers)
    df.to_excel(file_path, index=False)
    
    return filename

def get_export_file_path(filename: str) -> str:
    """Returns the full path for an exported file."""
    export_dir = ensure_export_directory()
    return os.path.join(export_dir, filename)
