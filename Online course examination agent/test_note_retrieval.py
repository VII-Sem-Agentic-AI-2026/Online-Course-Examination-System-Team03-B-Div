from backend.app.document_processing.vector_store import search_chunks

# Use the document ID from your latest successful upload.
DOCUMENT_ID = "babd112e-3749-4f17-a3a8-803492425945"

TEACHER_ID = 2

queries = [
    "Explain classes and objects",
    "What is a constructor?",
    "Explain method overloading",
    "What are static members?",
]

for query in queries:

    print("\n" + "=" * 70)
    print("QUERY:", query)
    print("=" * 70)

    results = search_chunks(
        query=query,
        teacher_id=TEACHER_ID,
        subject="OOP",
        document_ids=[DOCUMENT_ID],
        top_k=3,
    )

    for result in results:
        print("\nChunk:", result["chunk_id"])
        print("Similarity:", round(result["similarity"], 4))
        print("Content:")
        print(result["text"][:700])