"""
RAG Pipeline: Chunking → Embeddings → ChromaDB vector store.
Uses HuggingFace sentence-transformers (open source, no API key needed).
"""
import os
from typing import List, Dict
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma_db")
COLLECTION_NAME = "hrms_knowledge"
EMBED_MODEL = "all-MiniLM-L6-v2"  # Fast, lightweight, 384-dim embeddings

# Singleton model (avoid reloading)
_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"[Embeddings] Loading model: {EMBED_MODEL}")
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def get_chroma_client() -> chromadb.Client:
    return chromadb.PersistentClient(
        path=CHROMA_PATH,
        settings=Settings(anonymized_telemetry=False)
    )


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Split text into overlapping chunks for better RAG retrieval.
    Overlap ensures context isn't lost at chunk boundaries.
    """
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks


def ingest_documents(documents: List[Dict]) -> int:
    """
    Ingest scraped documents into ChromaDB.
    Returns number of chunks stored.
    """
    client = get_chroma_client()
    model = get_model()

    # Get or create collection
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    all_chunks = []
    all_embeddings = []
    all_ids = []
    all_metadatas = []

    for doc_idx, doc in enumerate(documents):
        chunks = chunk_text(doc["content"])
        print(f"[Embeddings] {doc['url']} → {len(chunks)} chunks")

        for chunk_idx, chunk in enumerate(chunks):
            chunk_id = f"doc_{doc_idx}_chunk_{chunk_idx}"
            all_chunks.append(chunk)
            all_ids.append(chunk_id)
            all_metadatas.append({
                "url": doc["url"],
                "title": doc.get("title", ""),
                "chunk_idx": chunk_idx,
            })

    # Batch embed
    print(f"[Embeddings] Embedding {len(all_chunks)} chunks...")
    embeddings = model.encode(all_chunks, show_progress_bar=True).tolist()

    # Store in ChromaDB
    collection.upsert(
        ids=all_ids,
        documents=all_chunks,
        embeddings=embeddings,
        metadatas=all_metadatas,
    )

    print(f"[Embeddings] Stored {len(all_chunks)} chunks in ChromaDB.")
    return len(all_chunks)


def is_knowledge_base_ready() -> bool:
    """Check if the vector DB already has data (avoid re-scraping)."""
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection(COLLECTION_NAME)
        return collection.count() > 0
    except Exception:
        return False
