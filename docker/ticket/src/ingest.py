"""
KB-Ingest: Laedt Dokumente aus kb/ und indexiert sie in ChromaDB.

Support: .md .txt .pdf .docx .html
Chunk-Strategie: ~600 Tokens mit 80 Token Overlap.

Usage:
  python src/ingest.py            # Alle Dokumente in kb/ indexieren
  python src/ingest.py --reset    # Index vorher loeschen
  python src/ingest.py --stats    # Statistik ausgeben
"""
import os
import sys
import argparse
import hashlib
from pathlib import Path

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "kb"
CHROMA_DIR = ROOT / "data" / "chroma"
COLLECTION = "kb_main"

load_dotenv(ROOT / ".env")
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")


def read_md_txt(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def read_pdf(p: Path) -> str:
    from pypdf import PdfReader
    r = PdfReader(str(p))
    return "\n\n".join((page.extract_text() or "") for page in r.pages)


def read_docx(p: Path) -> str:
    from docx import Document
    d = Document(str(p))
    return "\n".join(para.text for para in d.paragraphs if para.text.strip())


def read_html(p: Path) -> str:
    import re
    html = p.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


LOADERS = {
    ".md": read_md_txt,
    ".txt": read_md_txt,
    ".pdf": read_pdf,
    ".docx": read_docx,
    ".html": read_html,
    ".htm": read_html,
}


import re


def _split_long(block: str, target_chars: int, overlap_chars: int):
    """Char-basiert weiter splitten wenn Block zu gross."""
    if len(block) <= target_chars:
        return [block] if block.strip() else []
    out = []
    i = 0
    n = len(block)
    while i < n:
        end = min(i + target_chars, n)
        if end < n:
            for sep in ["\n\n", ". ", "! ", "? ", "\n"]:
                j = block.rfind(sep, i, end)
                if j > i + target_chars // 2:
                    end = j + len(sep)
                    break
        out.append(block[i:end].strip())
        if end >= n:
            break
        i = max(i + 1, end - overlap_chars)
    return [c for c in out if c]


def chunk_text(text: str, target_chars: int = 2400, overlap_chars: int = 320):
    """Separator-aware Chunking.
    Erkennt KB-Separator-Linien (>= 5x '-' oder '=') als harte Block-Grenzen.
    Jeder Block wird ein Chunk; zu grosse Bloecke werden char-basiert weiter gesplittet.
    Ohne Separatoren: Fallback auf reines Char-Chunking.
    """
    text = text.strip()
    if not text:
        return []

    sep_pattern = re.compile(r"\n\s*[-=]{5,}\s*\n")
    if sep_pattern.search(text):
        blocks = [b.strip() for b in sep_pattern.split(text) if b.strip()]
        chunks = []
        for b in blocks:
            chunks.extend(_split_long(b, target_chars, overlap_chars))
        return chunks

    return _split_long(text, target_chars, overlap_chars)


def file_hash(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()[:12]


def get_client():
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR),
                                       settings=Settings(anonymized_telemetry=False))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    col = client.get_or_create_collection(name=COLLECTION, embedding_function=ef,
                                          metadata={"hnsw:space": "cosine"})
    return client, col


def ingest_all(reset: bool = False):
    client, col = get_client()
    if reset:
        print(f"[reset] Lösche Collection {COLLECTION}")
        client.delete_collection(COLLECTION)
        _, col = get_client()

    KB_DIR.mkdir(parents=True, exist_ok=True)
    files = [p for p in KB_DIR.rglob("*") if p.is_file() and p.suffix.lower() in LOADERS]
    if not files:
        print(f"[!] Keine Dokumente in {KB_DIR}. Lege Dateien (.md/.txt/.pdf/.docx/.html) ab.")
        return

    total_chunks = 0
    for f in files:
        try:
            text = LOADERS[f.suffix.lower()](f)
        except Exception as e:
            print(f"[skip] {f.name}: {e}")
            continue

        chunks = chunk_text(text)
        if not chunks:
            print(f"[skip] {f.name}: kein Text")
            continue

        fh = file_hash(f)
        ids, docs, metas = [], [], []
        for i, ch in enumerate(chunks):
            ids.append(f"{fh}_{i:04d}")
            docs.append(ch)
            metas.append({"source": f.name, "path": str(f.relative_to(ROOT)),
                          "chunk": i, "hash": fh})

        # Upsert idempotent
        col.upsert(ids=ids, documents=docs, metadatas=metas)
        total_chunks += len(chunks)
        print(f"[ok] {f.name}: {len(chunks)} Chunks")

    print(f"\n[OK] Index fertig: {len(files)} Dateien, {total_chunks} Chunks gesamt.")


def stats():
    _, col = get_client()
    n = col.count()
    print(f"Collection '{COLLECTION}': {n} Chunks")
    sample = col.peek(5)
    for i, (d, m) in enumerate(zip(sample.get("documents", []), sample.get("metadatas", []))):
        print(f"  [{i}] {m.get('source')} chunk={m.get('chunk')}")
        print(f"      {d[:120]}...")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="Index vor Ingest loeschen")
    ap.add_argument("--stats", action="store_true", help="Nur Statistik zeigen")
    args = ap.parse_args()
    if args.stats:
        stats()
    else:
        ingest_all(reset=args.reset)


if __name__ == "__main__":
    main()
