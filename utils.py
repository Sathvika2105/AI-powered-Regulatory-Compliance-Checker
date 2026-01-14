# utils.py
import os
import json
import hashlib
from pathlib import Path
from datetime import datetime

# Optional imports (wrapped so code will still run if they are missing)
try:
    from PyPDF2 import PdfReader
except Exception:
    PdfReader = None

# FAISS/embeddings optional (only used if you enable vector features)
try:
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_community.vectorstores import FAISS
    from langchain.schema import Document
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    FAISS_AVAILABLE = True
except Exception:
    FAISS_AVAILABLE = False

# reportlab for PDFs
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# -----------------------------
# Config paths
# -----------------------------
DATA_DIR = Path(".")
CONTRACTS_DIR = DATA_DIR / "Contracts_ZIP_File"
UPDATES_DIR = DATA_DIR / "updates"
ARCHIVE_DIR = DATA_DIR / "archive"
APPLIED_DIR = DATA_DIR / "applied"
REG_UPDATES_DIR = DATA_DIR / "reg_updates"
METADATA_DB = DATA_DIR / "metadata_db.json"
FAISS_INDEX_DIR = DATA_DIR / "faiss_index"

# -----------------------------
# Helpers / IO
# -----------------------------
def ensure_dirs():
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    APPLIED_DIR.mkdir(parents=True, exist_ok=True)
    REG_UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)

def load_metadata_db(path: Path = METADATA_DB):
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_metadata_db(db: dict, path: Path = METADATA_DB):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

# -----------------------------
# File listing and reading
# -----------------------------
def find_files(folder: Path, extensions=None):
    if extensions is None:
        extensions = [".pdf", ".txt"]
    folder = Path(folder)
    files = [p for p in folder.rglob("*") if p.suffix.lower() in extensions]
    return files

def read_text_from_file(file_path: Path):
    file_path = Path(file_path)
    if not file_path.exists():
        return ""
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        if PdfReader is None:
            # fallback: return empty or instruct user to install PyPDF2
            return ""
        try:
            reader = PdfReader(str(file_path))
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text
        except Exception:
            return ""
    elif suffix == ".txt":
        try:
            return file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    else:
        # unsupported: return empty
        return ""

# -----------------------------
# Hashing & registration
# -----------------------------
def compute_file_hash(file_path: Path):
    if not file_path.exists():
        return None
    text = read_text_from_file(file_path)
    if not text:
        return None
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def register_contract_entry(db: dict, file_path: str, extracted_date: str = None, file_hash: str = None, status: str = "Active"):
    """
    Register a new contract entry in metadata DB.
    db: metadata dict (mutated and returned)
    file_path: full path string or relative
    """
    p = str(file_path)
    cid = Path(p).stem
    db[cid] = {
        "file_path": p,
        "date": extracted_date,
        "hash": file_hash,
        "status": status,
        "version": 1,
        "snapshot_text": read_text_from_file(Path(p))[:4000] if Path(p).exists() else "",
        "archived_paths": []
    }
    return db

# -----------------------------
# Clause change detection
# -----------------------------
def detect_clause_changes(old_text: str, new_text: str):
    old_lines = set([l.strip() for l in (old_text or "").splitlines() if l.strip()])
    new_lines = set([l.strip() for l in (new_text or "").splitlines() if l.strip()])
    added = sorted(list(new_lines - old_lines))
    removed = sorted(list(old_lines - new_lines))
    return {"added": added, "removed": removed}

# -----------------------------
# PDF/Text saving utilities
# -----------------------------
def save_text_as_pdf_or_txt(text: str, out_path: Path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if REPORTLAB_AVAILABLE and out_path.suffix.lower() == ".pdf":
        try:
            c = canvas.Canvas(str(out_path), pagesize=A4)
            width, height = A4
            margin = 50
            y = height - margin
            c.setFont("Helvetica", 10)
            for line in (text or "").splitlines():
                # basic wrap
                chunks = [line[i:i+100] for i in range(0, max(1, len(line)), 100)]
                for chunk in chunks:
                    if y < margin + 20:
                        c.showPage()
                        y = height - margin
                        c.setFont("Helvetica", 10)
                    c.drawString(margin, y, chunk)
                    y -= 12
            c.save()
            return str(out_path)
        except Exception:
            # fallback to txt
            pass

    # fallback to txt
    txt_path = out_path.with_suffix(".txt")
    txt_path.write_text(text or "", encoding="utf-8")
    return str(txt_path)

def generate_updates_pdf(changes: dict, out_path: Path, contract_id: str, filename: str):
    """
    Summarize changes in a PDF (or TXT if reportlab not available).
    changes: dict with 'added' and 'removed' lists
    """
    lines = []
    lines.append(f"Contract Update Report: {contract_id}")
    lines.append(f"Source File: {filename}")
    lines.append(f"Generated: {datetime.utcnow().isoformat()} UTC")
    lines.append("")
    lines.append("ADDED CLAUSES:")
    if changes.get("added"):
        for a in changes.get("added"):
            lines.append(f"+ {a}")
    else:
        lines.append(" (none)")

    lines.append("")
    lines.append("REMOVED CLAUSES:")
    if changes.get("removed"):
        for r in changes.get("removed"):
            lines.append(f"- {r}")
    else:
        lines.append(" (none)")

    text = "\n".join(lines)
    # ensure filename extension .pdf for PDF output (but function will fallback)
    if out_path.suffix == "":
        out_path = out_path.with_suffix(".pdf")
    return save_text_as_pdf_or_txt(text, out_path)

# -----------------------------
# Documents -> chunks -> faiss (optional)
# -----------------------------
def load_documents(file_paths):
    docs = []
    for p in file_paths:
        t = read_text_from_file(Path(p)) or ""
        if t.strip():
            docs.append({"text": t, "source": str(p)})
    return docs

def split_documents(docs):
    if not FAISS_AVAILABLE:
        # fallback: return each document as one chunk
        chunks = []
        for d in docs:
            chunks.append({"text": d.get("text", ""), "source": d.get("source")})
        return chunks
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = []
    for d in docs:
        for chunk in splitter.split_text(d["text"]):
            chunks.append({"text": chunk, "source": d["source"]})
    return chunks

def build_or_load_faiss(chunks, index_path: Path, rebuild=False):
    if not FAISS_AVAILABLE:
        raise RuntimeError("FAISS/embeddings not available. Install langchain-community and sentence-transformers for vector features.")
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    docs = []
    for ch in chunks:
        docs.append(Document(page_content=ch.get("text", ""), metadata={"source": ch.get("source")}))
    if rebuild or not (index_path.exists() and any(index_path.iterdir())):
        vs = FAISS.from_documents(docs, embeddings)
        vs.save_local(str(index_path))
        return vs
    else:
        return FAISS.load_local(str(index_path), embeddings, allow_dangerous_deserialization=True)

# -----------------------------
# Apply amendment: create new version / archive old
# -----------------------------
def apply_amendment_file(contract_path: str, amendment_text: str, metadata: dict):
    """
    Append amendment_text to the contract and create a new version file under same directory.
    Returns new file path string and updates metadata in memory (does not save).
    """
    p = Path(contract_path)
    if not p.exists():
        raise FileNotFoundError(f"{contract_path} not found")

    # read current text (try pdf -> text)
    cur_text = read_text_from_file(p) or ""
    new_text = cur_text + "\n\n=== AMENDMENT ===\n" + amendment_text + "\n"

    # new version name
    contract_id = p.stem
    version = metadata.get(contract_id, {}).get("version", 1) + 1
    new_name = f"{contract_id}_v{version}{p.suffix}"
    new_path = p.parent / new_name

    # write new content as plain text (if original is PDF we will save a TXT; but also create a PDF summary)
    # For simplicity: save new_text to TXT with new version name, and also create a PDF copy for easy viewing.
    try:
        new_path.write_text(new_text, encoding="utf-8")
    except Exception:
        # fallback: write to .txt
        new_path = new_path.with_suffix(".txt")
        new_path.write_text(new_text, encoding="utf-8")

    # create a PDF summary of new text for quick viewing
    pdf_summary_path = new_path.with_suffix(".pdf")
    save_text_as_pdf_or_txt(new_text, pdf_summary_path)

    # archive old file
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    archive_name = f"{p.name}.bak_{ts}"
    archive_path = ARCHIVE_DIR / archive_name
    try:
        p.replace(archive_path)
    except Exception:
        # if replace fails, try copy
        try:
            import shutil
            shutil.copy2(str(p), str(archive_path))
        except Exception:
            pass

    # update metadata record
    contract_id = Path(new_path).stem
    # metadata is expected to be mutated by caller; return info to update metadata
    return {"new_file": str(new_path), "pdf_summary": str(pdf_summary_path), "archived": str(archive_path), "version": version}
