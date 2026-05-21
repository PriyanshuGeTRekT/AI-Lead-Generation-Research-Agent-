"""
pgvector Vector Store
----------------------
Production-grade drop-in replacement for ChromaDB using PostgreSQL + pgvector.

Why switch from ChromaDB to pgvector at scale:
  - One fewer service: vectors live in the same DB as lead records
  - Full ACID transactions: embedding writes and lead writes are atomic
  - Standard tooling: pg_dump, pgBadger, Datadog postgres integration all work
  - HNSW index: approximate nearest neighbor search comparable to ChromaDB
  - Native joins: SELECT leads JOIN embeddings WHERE similarity > threshold

Activation: set USE_PGVECTOR=true in .env (ChromaDB remains default)

Schema (auto-created on first use):
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE IF NOT EXISTS lead_embeddings (
        id TEXT PRIMARY KEY,
        document TEXT NOT NULL,
        embedding vector(384),
        metadata JSONB DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS lead_embeddings_hnsw
        ON lead_embeddings USING hnsw (embedding vector_cosine_ops);

Embedding dimension 384 matches all-MiniLM-L6-v2 output.
"""
import json
import uuid
from typing import List, Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    raise ImportError(
        "psycopg2 not installed. Run: pip install psycopg2-binary"
    )

from rag.embeddings import get_model


class PgVectorStore:
    """
    PostgreSQL + pgvector vector store. Drop-in alternative to ChromaDB.

    Activate by setting USE_PGVECTOR=true in .env and providing
    POSTGRES_URL=postgresql://leadgen:leadgen@postgres:5432/leadgen.
    """

    def __init__(
        self,
        postgres_url: str,
        collection_name: str = "hrms_knowledge",
    ) -> None:
        self.collection_name = collection_name
        self.table = "lead_embeddings"
        self.model = get_model()

        try:
            self.conn = psycopg2.connect(postgres_url)
            self.conn.autocommit = False
        except Exception as e:
            raise ConnectionError(
                f"Cannot connect to PostgreSQL at {postgres_url}: {e}"
            )

        self._setup_schema()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _setup_schema(self) -> None:
        """Create the pgvector extension, table, and HNSW index if missing."""
        with self.conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    id       TEXT PRIMARY KEY,
                    document TEXT NOT NULL,
                    embedding vector(384),
                    metadata JSONB DEFAULT '{{}}'
                );
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {self.table}_hnsw
                    ON {self.table} USING hnsw (embedding vector_cosine_ops);
                """
            )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Public API (mirrors ChromaDB collection interface)
    # ------------------------------------------------------------------

    def add_documents(
        self,
        documents: List[str],
        metadatas: Optional[List[dict]] = None,
    ) -> None:
        """
        Embed each document and upsert into the vector table.

        Args:
            documents: Plain-text documents to store.
            metadatas: Optional parallel list of metadata dicts.
        """
        if not documents:
            return

        if metadatas is None:
            metadatas = [{} for _ in documents]

        embeddings = self.model.encode(documents, show_progress_bar=False).tolist()

        rows = [
            (
                str(uuid.uuid4()),
                doc,
                embedding,
                json.dumps(meta),
            )
            for doc, embedding, meta in zip(documents, embeddings, metadatas)
        ]

        with self.conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                f"""
                INSERT INTO {self.table} (id, document, embedding, metadata)
                VALUES %s
                ON CONFLICT (id) DO UPDATE
                    SET document  = EXCLUDED.document,
                        embedding = EXCLUDED.embedding,
                        metadata  = EXCLUDED.metadata;
                """,
                rows,
                template="(%s, %s, %s::vector, %s::jsonb)",
            )
        self.conn.commit()

    def similarity_search(self, query: str, k: int = 3) -> List[str]:
        """
        Return the top-k most similar documents for the given query.

        Uses cosine distance (<=> operator) via the HNSW index.

        Args:
            query: Natural-language query string.
            k: Number of results to return.

        Returns:
            List of document strings ordered by similarity (closest first).
        """
        query_embedding = self.model.encode([query], show_progress_bar=False)[0].tolist()

        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT document
                FROM {self.table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (query_embedding, k),
            )
            rows = cur.fetchall()

        return [row[0] for row in rows]

    def count(self) -> int:
        """Return total number of stored embeddings (health check helper)."""
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {self.table};")
            result = cur.fetchone()
        return result[0] if result else 0
