"""
Semantic retrieval from ChromaDB.
Used by agents to ground their responses in real HRMS product knowledge,
preventing hallucinations about what HumanMaximizer actually does.
"""
from typing import List, Optional
from loguru import logger
from rag.embeddings import get_model, get_chroma_client, COLLECTION_NAME, vector_available


def _local_context(query: str = "", max_chars: int = 2200) -> str:
    """Fallback grounding when the vector store is unavailable/empty: return the
    most relevant slices of the local product knowledge (./knowledge)."""
    try:
        from rag.scraper import build_local_corpus
        docs = build_local_corpus()
    except Exception:
        docs = []
    if not docs:
        return "No product context available."
    # Light keyword ranking so the snippet is relevant to the query.
    q_words = {w for w in query.lower().split() if len(w) > 3}
    blocks: list[str] = []
    for d in docs:
        for para in d["content"].split("\n\n"):
            para = para.strip()
            if len(para) < 20:
                continue
            score = sum(1 for w in q_words if w in para.lower())
            blocks.append((score, para))
    blocks.sort(key=lambda b: b[0], reverse=True)
    out, total = [], 0
    for _, para in blocks:
        if total + len(para) > max_chars:
            break
        out.append(para)
        total += len(para)
    return "\n\n".join(out) if out else docs[0]["content"][:max_chars]


def retrieve(query: str, top_k: int = 4) -> str:
    """
    Retrieve the most relevant chunks for a given query.
    Returns a single formatted string for LLM context injection.
    Falls back to local product text when the vector stack is absent.
    """
    if not vector_available():
        return _local_context(query)
    try:
        client = get_chroma_client()
        model = get_model()
        collection = client.get_or_create_collection(COLLECTION_NAME)

        if collection.count() == 0:
            return _local_context(query)

        # Embed the query
        query_embedding = model.encode([query]).tolist()[0]

        # Semantic search
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        docs = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        # Filter out low-relevance results (cosine distance > 0.8 is poor)
        filtered = [
            (doc, meta, dist)
            for doc, meta, dist in zip(docs, metadatas, distances)
            if dist < 0.8
        ]

        if not filtered:
            return _local_context(query)

        # Format for LLM consumption
        context_parts = []
        for doc, meta, dist in filtered:
            source = meta.get("url", "unknown")
            context_parts.append(f"[Source: {source}]\n{doc}")

        return "\n\n---\n\n".join(context_parts)

    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")
        return _local_context(query)


def retrieve_hrms_context(company_description: str) -> str:
    """
    Retrieve HRMS-specific context relevant to a prospect company.
    Used by qualification and sales agents.

    Bug fix: was hardcoded to top_k=3, ignoring settings.rag_top_k (default 4).
    Now reads from config so it can be tuned without a code change.
    """
    from core.config import get_settings
    top_k = get_settings().rag_top_k
    query = f"HRMS features benefits for company: {company_description}"
    return retrieve(query, top_k=top_k)
