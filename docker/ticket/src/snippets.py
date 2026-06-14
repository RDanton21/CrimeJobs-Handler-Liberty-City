"""
Snippet-Store: Q&A-Textbausteine, die vor dem RAG-Lookup geprueft werden.
JSON-persistiert unter data/snippets.json.

Flow: User-Frage -> Snippet-Embedding-Match > SNIPPET_THRESHOLD -> Canned Answer (0 Claude-Kosten).
Sonst: RAG -> Claude.
"""
import json
import os
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

ROOT = Path(__file__).resolve().parent.parent
SNIPPETS_FILE = ROOT / "data" / "snippets.json"
SNIPPET_THRESHOLD = float(os.getenv("SNIPPET_THRESHOLD", "0.72"))


def _load() -> List[Dict[str, Any]]:
    if not SNIPPETS_FILE.exists():
        return []
    try:
        return json.loads(SNIPPETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: List[Dict[str, Any]]):
    SNIPPETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SNIPPETS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def list_all() -> List[Dict[str, Any]]:
    return _load()


def get(sid: str) -> Optional[Dict[str, Any]]:
    for s in _load():
        if s.get("id") == sid:
            return s
    return None


def create(question: str, answer: str, keywords: str = "") -> Dict[str, Any]:
    items = _load()
    s = {
        "id": uuid.uuid4().hex[:12],
        "question": question.strip(),
        "answer": answer.strip(),
        "keywords": keywords.strip(),
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
        "hits": 0,
    }
    items.insert(0, s)
    _save(items)
    return s


def update(sid: str, question: str, answer: str, keywords: str = "") -> bool:
    items = _load()
    for s in items:
        if s["id"] == sid:
            s["question"] = question.strip()
            s["answer"] = answer.strip()
            s["keywords"] = keywords.strip()
            s["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
            _save(items)
            return True
    return False


def delete(sid: str) -> bool:
    items = _load()
    new = [s for s in items if s["id"] != sid]
    if len(new) == len(items):
        return False
    _save(new)
    return True


def increment_hit(sid: str):
    items = _load()
    for s in items:
        if s["id"] == sid:
            s["hits"] = int(s.get("hits", 0)) + 1
            _save(items)
            return


_KEYWORD_TOKEN_RE = __import__("re").compile(r"[a-z0-9äöüß]+")


def _tokens(text: str) -> set:
    """Worttokens in Kleinschreibung (Trennung an allem ausser Buchstaben/Ziffern/Umlauten)."""
    return set(_KEYWORD_TOKEN_RE.findall((text or "").lower()))


def match(query: str, threshold: float = None) -> Optional[Dict[str, Any]]:
    """
    Findet das beste Snippet:
    1) Exakter Keyword-Treffer (mind. ein Query-Wort kommt in den Keywords vor)
       -> sofort zurueck, kein Semantik-Aufruf noetig.
    2) Sonst Cosine-Similarity ueber Embeddings.

    Returns Snippet-Dict mit Feld 'score' bei Treffer, sonst None.
    """
    items = _load()
    if not items:
        return None

    th = threshold if threshold is not None else SNIPPET_THRESHOLD

    # 1) Keyword-Exakt-Shortcut: kurze Queries wie "wl" oder "bewerbung" treffen
    # semantisch nicht zuverlaessig, aber das Keywords-Feld ist genau dafuer da.
    q_tokens = _tokens(query)
    if q_tokens:
        for s in items:
            kw_tokens = _tokens(s.get("keywords") or "")
            if kw_tokens and (q_tokens & kw_tokens):
                hit = dict(s)
                hit["score"] = 1.0
                hit["match_via"] = "keyword"
                return hit

    # 2) Sentence-Transformer lokal (selbes Model wie Chroma-Default)
    try:
        from sentence_transformers import SentenceTransformer, util
    except ImportError:
        return None

    model_name = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
    if not hasattr(match, "_model") or getattr(match, "_model_name", None) != model_name:
        match._model = SentenceTransformer(model_name)
        match._model_name = model_name

    # Score question + keywords separately, take max per snippet.
    # Keywords-Text im Pool verwaessert sonst die Aehnlichkeit.
    pool = []
    owners = []  # index zurueck auf items
    for i, s in enumerate(items):
        pool.append(s["question"])
        owners.append(i)
        if s.get("keywords"):
            pool.append(s["keywords"])
            owners.append(i)

    q_emb = match._model.encode(query, convert_to_tensor=True)
    p_emb = match._model.encode(pool, convert_to_tensor=True)
    sims = util.cos_sim(q_emb, p_emb)[0]

    # Max-Score pro Snippet
    per_item = [0.0] * len(items)
    for j, sc in enumerate(sims):
        idx = owners[j]
        if float(sc) > per_item[idx]:
            per_item[idx] = float(sc)
    best_idx = max(range(len(items)), key=lambda i: per_item[i])
    best_score = per_item[best_idx]
    if best_score >= th:
        hit = dict(items[best_idx])
        hit["score"] = best_score
        return hit
    return None


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for s in list_all():
            print(f"[{s['id']}] hits={s.get('hits',0)} Q: {s['question'][:70]}")
    elif cmd == "match":
        q = " ".join(sys.argv[2:])
        r = match(q)
        print(f"Match: {r}")
    elif cmd == "seed":
        create("Wie oeffne ich ein Ticket?",
               "Klicke im Support-Channel auf den Button **🎫 Ticket öffnen**. Ein privater Thread wird fuer dich erstellt. Stelle dort deine Frage, und die KI antwortet automatisch.",
               "ticket öffnen eröffnen erstellen start")
        create("Wie schliesse ich mein Ticket?",
               "Tippe einfach `/close` im Ticket-Thread. Der Thread wird archiviert und gesperrt.",
               "ticket schließen close beenden")
        print("Seed done.")
