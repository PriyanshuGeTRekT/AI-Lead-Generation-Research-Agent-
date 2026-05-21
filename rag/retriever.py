"""
Semantic retrieval from ChromaDB.
Used by agents to ground their responses in real HRMS product knowledge,
preventing hallucinations about what HumanMaximizer actually does.
"""
from typing import List, Optional
from loguru import logger
from rag.embeddings import get_model, get_chroma_client, COLLECTION_NAME


def retrieve(query: str, top_k: int = 4) -> str:
    """
    Retrieve the most relevant chunks for a given query.
    Returns a single formatted string for LLM context injection.
    """
    try:
        client = get_chroma_client()
        model = get_model()
        collection = client.get_or_create_collection(COLLECTION_NAME)

        if collection.count() == 0:
            return "No knowledge base found. Please run the ingestion script first."

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
            return "No relevant context found in knowledge base."

        # Format for LLM consumption
        context_parts = []
        for doc, meta, dist in filtered:
            source = meta.get("url", "unknown")
            context_parts.append(f"[Source: {source}]\n{doc}")

        return "\n\n---\n\n".join(context_parts)

    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")
        return "No product context available."


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
