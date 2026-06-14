"""
RAG-Core: Retrieval aus ChromaDB + Claude-API-Call mit Quellen-Zitaten.
"""
import os
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv
from anthropic import Anthropic

from ingest import get_client
import snippets as snippet_store
import features as feature_flags

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "800"))
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.35"))
TOP_K = int(os.getenv("TOP_K", "5"))

SYSTEM_PROMPT = """Du bist ein hilfsbereiter Support-Assistent in einem Discord-Server.

Beantworte Nutzerfragen AUSSCHLIESSLICH auf Basis der bereitgestellten Kontext-Dokumente.
- Wenn die Antwort im Kontext steht: Formuliere klar, praegnant und freundlich.
- Wenn die Antwort NICHT im Kontext steht: Sage ehrlich "Dazu habe ich keine Informationen in der Wissensbasis" und empfiehl, einen Mod zu kontaktieren.
- Erfinde keine Fakten. Keine Halluzinationen.
- Nenne KEINE Quellen, Dateinamen oder Confidence-Werte in der Antwort.
- Antwort auf Deutsch wenn Frage auf Deutsch, sonst Sprache der Frage.
- Halte dich kurz (max. 5-8 Sätze), es sei denn die Frage braucht mehr Details.
- Verwende Discord-Markdown (Fett **text**, Listen mit -, Code mit ```).
"""


def retrieve(query: str, k: int = TOP_K) -> Dict[str, Any]:
    """Holt Top-K relevante Chunks. Returns dict mit docs, metadatas, distances."""
    _, col = get_client()
    if col.count() == 0:
        return {"docs": [], "metas": [], "distances": [], "confidence": 0.0}

    res = col.query(query_texts=[query], n_results=min(k, col.count()))
    docs = res["documents"][0] if res["documents"] else []
    metas = res["metadatas"][0] if res["metadatas"] else []
    dists = res["distances"][0] if res.get("distances") else []

    # Cosine-Distance -> Similarity (1 - dist). Confidence = best match.
    confidence = (1.0 - min(dists)) if dists else 0.0
    return {
        "docs": docs,
        "metas": metas,
        "distances": dists,
        "confidence": confidence,
    }


def build_context(docs: List[str], metas: List[Dict]) -> str:
    """Packt Chunks in lesbaren Kontext-Block mit Quellen-Labels."""
    parts = []
    for i, (d, m) in enumerate(zip(docs, metas), 1):
        src = m.get("source", "unknown")
        parts.append(f"[Quelle {i}: {src}]\n{d.strip()}")
    return "\n\n---\n\n".join(parts)


def answer(query: str) -> Dict[str, Any]:
    """Haupt-Eintritt: Frage -> Snippet-Match ODER RAG-Antwort."""
    flags = feature_flags.get()

    # 1. Snippet-Check (schneller + 0 Kosten bei Treffer)
    if flags.get("snippets_enabled", True):
        try:
            snip = snippet_store.match(query)
        except Exception:
            snip = None
        if snip:
            try:
                snippet_store.increment_hit(snip["id"])
            except Exception:
                pass
            return {
                "answer": snip["answer"],
                "sources": [f"Snippet: {snip['question'][:40]}"],
                "confidence": float(snip.get("score", 1.0)),
                "needs_human": False,
                "snippet_hit": True,
                "snippet_id": snip["id"],
            }

    # 2. RAG (ChromaDB + Claude)
    if not flags.get("rag_enabled", True):
        return {
            "answer": "Die automatische Antwort-Funktion ist momentan deaktiviert. Ein Mod wird sich gleich darum kümmern.",
            "sources": [],
            "confidence": 0.0,
            "needs_human": True,
        }

    retr = retrieve(query)
    if not retr["docs"]:
        return {
            "answer": "Die Wissensbasis ist leer. Bitte ein Admin soll zuerst Dokumente indexieren (`python src/ingest.py`).",
            "sources": [],
            "confidence": 0.0,
            "needs_human": True,
        }

    if retr["confidence"] < CONFIDENCE_THRESHOLD:
        return {
            "answer": "Zu dieser Frage finde ich keine passenden Informationen in der Wissensbasis. Ein Mod wird gleich schauen.",
            "sources": list({m.get("source", "?") for m in retr["metas"]}),
            "confidence": retr["confidence"],
            "needs_human": True,
        }

    context = build_context(retr["docs"], retr["metas"])
    user_msg = f"""Kontext aus Wissensbasis:

{context}

---

Nutzer-Frage: {query}

Antworte auf Basis des Kontexts. Falls Kontext nicht ausreicht: sag das ehrlich."""

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    answer_text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    sources = list({m.get("source", "?") for m in retr["metas"]})
    return {
        "answer": answer_text,
        "sources": sources,
        "confidence": retr["confidence"],
        "needs_human": False,
        "usage": {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        },
    }


if __name__ == "__main__":
    # CLI-Test
    import sys
    q = " ".join(sys.argv[1:]) or input("Frage: ")
    r = answer(q)
    print(f"\nConfidence: {r['confidence']:.2%}")
    print(f"Sources: {', '.join(r['sources']) or '-'}")
    print(f"Needs human: {r['needs_human']}")
    print(f"\nAntwort:\n{r['answer']}")
    if "usage" in r:
        print(f"\nTokens in/out: {r['usage']['input_tokens']}/{r['usage']['output_tokens']}")
