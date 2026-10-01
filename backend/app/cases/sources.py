"""Build case-specific retrieval indexes while retaining inspectable locations."""
import json
from pathlib import Path

import pandas as pd
from PyPDF2 import PdfReader

from app.cases import store
from app.embeddings.model import get_embedding_model
from app.ingestion.chunker import chunk_text
from app.vectorstore.faiss_store import FAISSStore


def _chunks(text: str, base: dict):
    for chunk in chunk_text(text, chunk_size=400, chunk_overlap=50):
        yield {**base, "text": chunk["text"]}


def sections(case_id: str):
    case = store.get_case(case_id)
    for kind, info in case["files"].items():
        path = store.file_path(case_id, kind)
        name = info["filename"]
        if info["extension"] == ".pdf":
            reader = PdfReader(str(path))
            for page_number, page in enumerate(reader.pages, 1):
                text = (page.extract_text() or "").strip()
                if text:
                    yield from _chunks(text, {"kind": kind, "source": name,
                                               "page": page_number, "location": f"page {page_number}"})
        elif info["extension"] == ".txt":
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            start = None
            for index in range(len(lines) + 1):
                line = lines[index] if index < len(lines) else ""
                if line.strip() and start is None:
                    start = index
                if not line.strip() and start is not None:
                    first, last = start + 1, index
                    block = "\n".join(lines[start:index])
                    yield from _chunks(block, {"kind": kind, "source": name,
                                                "line_start": first, "line_end": last,
                                                "location": f"lines {first}-{last}"})
                    start = None
        else:
            frame = pd.read_csv(path)
            for index, row in frame.iterrows():
                row_number = int(index) + 2  # header is physical CSV line 1
                values = {column: _plain(value) for column, value in row.items()}
                text = "; ".join(f"{key}: {value}" for key, value in values.items())
                yield {"kind": kind, "source": name, "text": text,
                       "row_number": row_number, "columns": list(frame.columns),
                       "location": f"CSV row {row_number}"}


def _plain(value):
    if pd.isna(value):
        return ""
    if hasattr(value, "item"):
        return value.item()
    return value


def index_path(case_id: str) -> Path:
    return store.root() / case_id / "index"


def build_index(case_id: str) -> FAISSStore:
    from app.cases import clauses

    passages = list(sections(case_id))
    if not passages:
        raise ValueError("Uploaded files contain no searchable text")
    for index, passage in enumerate(passages):
        passage["chunk_index"] = index
    contract_passages = clauses.contract_passages(case_id)
    embeddings = get_embedding_model().embed(
        [item["text"] for item in passages + contract_passages]
    )
    main_vectors = embeddings[:len(passages)]
    vectorstore = FAISSStore(dimension=main_vectors.shape[1])
    vectorstore.add(main_vectors, passages)
    vectorstore.save(str(index_path(case_id)))
    if contract_passages:
        clauses.save_index(case_id, contract_passages, embeddings[len(passages):])
    return vectorstore


def load_index(case_id: str) -> FAISSStore:
    return FAISSStore.load(str(index_path(case_id)))


def excerpt(case_id: str, kind: str, *, page: int | None = None,
            row: int | None = None, line_start: int | None = None,
            line_end: int | None = None) -> dict:
    path = store.file_path(case_id, kind)
    info = store.get_case(case_id)["files"][kind]
    values = None
    if path.suffix == ".pdf":
        reader = PdfReader(str(path))
        if page is None or not 1 <= page <= len(reader.pages):
            raise ValueError("Choose a valid PDF page")
        text = (reader.pages[page - 1].extract_text() or "").strip()
        location = f"page {page}"
    elif path.suffix == ".txt":
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        if line_start is None or line_end is None or not 1 <= line_start <= line_end <= len(lines):
            raise ValueError("Choose a valid line range")
        text = "\n".join(f"{i + 1}: {lines[i]}" for i in range(line_start - 1, line_end))
        location = f"lines {line_start}-{line_end}"
    else:
        frame = pd.read_csv(path)
        if row is None or not 2 <= row <= len(frame) + 1:
            raise ValueError("Choose a valid CSV row")
        values = {column: _plain(value) for column, value in frame.iloc[row - 2].items()}
        text = json.dumps(values, ensure_ascii=False, indent=2)
        location = f"CSV row {row}"
    return {"kind": kind, "source": info["filename"], "location": location,
            "text": text, "values": values}
