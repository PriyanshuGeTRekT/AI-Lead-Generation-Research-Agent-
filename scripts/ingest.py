"""
Standalone ingestion script.
Run once to build the RAG knowledge base from humanmaximizer.com.
Usage: python scripts/ingest.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.scraper import build_corpus
from rag.embeddings import ingest_documents, is_knowledge_base_ready

if __name__ == "__main__":
    if is_knowledge_base_ready():
        print("Knowledge base already exists. Skipping ingestion.")
        print("Delete ./data/chroma_db to force re-ingestion.")
        sys.exit(0)

    print("Building RAG knowledge base from humanmaximizer.com...")
    corpus = build_corpus()

    if not corpus:
        print("ERROR: No content scraped. Check your internet connection.")
        sys.exit(1)

    chunks = ingest_documents(corpus)
    print(f"\nDone! {chunks} chunks stored in ChromaDB.")
    print("You can now run the lead generation pipeline.")
