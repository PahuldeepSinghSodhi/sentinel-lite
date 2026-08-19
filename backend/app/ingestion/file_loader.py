"""File loader — reads .txt, .pdf, and .csv files into raw text.

This is the first stage of the ingestion pipeline. Each loader
extracts plain text from its format so downstream stages (chunking,
embedding) always receive a uniform string input.
"""
import pandas as pd
from pathlib import Path
from PyPDF2 import PdfReader


# ── Supported file extensions ─────────────────────────────────────
SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".csv"}


def load_document(filepath: str) -> dict:
    """Load a document and extract its text content.
    
    Args:
        filepath: Path to the document file.
        
    Returns:
        dict with keys:
            - "source": the filename (used as document ID in metadata)
            - "text": the extracted plain text
            - "file_type": the file extension
            
    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file type is not supported.
    """
    path = Path(filepath)
    
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {filepath}")
    
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {extension}. "
            f"Supported types: {SUPPORTED_EXTENSIONS}"
        )
    
    # Dispatch to the appropriate format-specific loader
    if extension == ".txt":
        text = _load_txt(path)
    elif extension == ".pdf":
        text = _load_pdf(path)
    elif extension == ".csv":
        text = _load_csv(path)
    
    return {
        "source": path.name,
        "text": text,
        "file_type": extension,
    }


def _load_txt(path: Path) -> str:
    """Read a plain text file as UTF-8."""
    return path.read_text(encoding="utf-8")


def _load_pdf(path: Path) -> str:
    """Extract text from all pages of a PDF.
    
    Uses PyPDF2 to iterate through pages and concatenate their text.
    Each page's text is separated by a newline for readability.
    """
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:  # skip pages with no extractable text
            pages.append(page_text)
    return "\n".join(pages)


def _load_csv(path: Path) -> str:
    """Convert a CSV file into a natural-language text representation.
    
    Embedding models understand prose better than tabular data. So instead
    of "vendor_name: Apex, hourly_rate: 250", we produce sentences like
    "The approved hourly rate for Apex Consulting Senior Engineer is $250/hour."
    
    This dramatically improves retrieval accuracy for semantic queries
    about rates, vendors, and pricing.
    """
    df = pd.read_csv(path)
    
    lines = [f"Approved Vendor Rate Card from {path.name}"]
    lines.append(f"This document contains approved billing rates for {len(df)} vendor roles.")
    lines.append(f"Data columns: {', '.join(df.columns.tolist())}")
    lines.append("")
    
    # Convert each row to a natural-language sentence
    for idx, row in df.iterrows():
        # Build a human-readable sentence from the row data
        parts = []
        for col, val in row.items():
            # Clean up column names for readability
            col_readable = col.replace("_", " ").title()
            parts.append(f"{col_readable}: {val}")
        
        # Also create a natural-language summary sentence for each row
        row_dict = row.to_dict()
        vendor = row_dict.get("vendor_name", "Unknown Vendor")
        role = row_dict.get("role_level", "Unknown Role")
        rate = row_dict.get("hourly_rate", "N/A")
        category = row_dict.get("service_category", "")
        
        sentence = (
            f"The approved hourly rate for {vendor} {role} "
            f"in {category} is ${rate}/hour."
        )
        lines.append(sentence)
        lines.append(f"  Details - {', '.join(parts)}")
        lines.append("")
    
    return "\n".join(lines)
