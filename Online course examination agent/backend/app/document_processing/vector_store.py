import os
import json
import math
import sqlite3

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing from .env")

EMBEDDING_MODEL = os.getenv(
    "GEMINI_EMBEDDING_MODEL",
    "gemini-embedding-001",
)

client = genai.Client(api_key=API_KEY)

DB_PATH = Path(__file__).resolve().parents[1] / "auth_users.db"


# --------------------------------------------------
# DATABASE INITIALIZATION
# --------------------------------------------------

def init_vector_db():

    with sqlite3.connect(DB_PATH) as db:

        db.execute("""
            CREATE TABLE IF NOT EXISTS note_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                teacher_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                topic TEXT,
                chunk_id TEXT NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_note_chunks_document
            ON note_chunks(document_id)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_note_chunks_teacher
            ON note_chunks(teacher_id, subject)
        """)

        db.commit()


# --------------------------------------------------
# GENERATE EMBEDDING
# --------------------------------------------------

def generate_embedding(text: str) -> list[float]:

    if not text.strip():
        raise ValueError("Cannot embed empty text.")

    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )

    if not response.embeddings:
        raise RuntimeError("Gemini returned no embedding.")

    return response.embeddings[0].values


# --------------------------------------------------
# SAVE DOCUMENT CHUNKS
# --------------------------------------------------

def save_chunks(
    document_id: str,
    teacher_id: int,
    subject: str,
    topic: str | None,
    chunks: list[dict[str, Any]],
) -> int:

    if not chunks:
        raise ValueError("No chunks provided.")

    records = []

    for chunk in chunks:

        text = chunk["text"].strip()

        if not text:
            continue

        embedding = generate_embedding(text)

        records.append((
            document_id,
            teacher_id,
            subject,
            topic,
            chunk["chunk_id"],
            text,
            json.dumps(embedding),
        ))

    if not records:
        raise ValueError("No valid chunks to save.")

    with sqlite3.connect(DB_PATH) as db:

        db.execute(
            "DELETE FROM note_chunks WHERE document_id = ?",
            (document_id,),
        )

        db.executemany("""
            INSERT INTO note_chunks (
                document_id,
                teacher_id,
                subject,
                topic,
                chunk_id,
                chunk_text,
                embedding
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, records)

        db.commit()

    return len(records)


# --------------------------------------------------
# COSINE SIMILARITY
# --------------------------------------------------

def cosine_similarity(
    vector_a: list[float],
    vector_b: list[float],
) -> float:

    dot_product = sum(
        a * b for a, b in zip(vector_a, vector_b)
    )

    magnitude_a = math.sqrt(sum(a * a for a in vector_a))
    magnitude_b = math.sqrt(sum(b * b for b in vector_b))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


# --------------------------------------------------
# SEARCH RELEVANT NOTE CHUNKS
# --------------------------------------------------

def search_chunks(
    query: str,
    teacher_id: int,
    subject: str,
    document_ids: list[str] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:

    if not document_ids:
        return []

    query_embedding = generate_embedding(query)

    placeholders = ",".join("?" for _ in document_ids)

    sql = f"""
        SELECT
            document_id,
            chunk_id,
            chunk_text,
            embedding
        FROM note_chunks
        WHERE teacher_id = ?
        AND subject = ?
        AND document_id IN ({placeholders})
    """

    with sqlite3.connect(DB_PATH) as db:

        rows = db.execute(
            sql,
            [teacher_id, subject, *document_ids],
        ).fetchall()

    results = []

    for row in rows:

        stored_embedding = json.loads(row[3])

        score = cosine_similarity(
            query_embedding,
            stored_embedding,
        )

        results.append({
            "document_id": row[0],
            "chunk_id": row[1],
            "text": row[2],
            "similarity": score,
        })

    results.sort(
        key=lambda item: item["similarity"],
        reverse=True,
    )

    return results[:top_k]


# --------------------------------------------------
# INITIALIZE DATABASE
# --------------------------------------------------

init_vector_db()