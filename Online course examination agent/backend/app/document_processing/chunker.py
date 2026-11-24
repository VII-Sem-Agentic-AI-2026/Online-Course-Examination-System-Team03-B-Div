def chunk_text(
    text: str,
    chunk_size: int = 180,
    overlap: int = 30,
) -> list[dict]:

    if not text or not text.strip():
        return []

    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Invalid chunk settings.")

    words = text.split()
    chunks = []

    start = 0
    chunk_number = 1

    while start < len(words):
        end = min(start + chunk_size, len(words))

        content = " ".join(words[start:end]).strip()

        if content:
            chunks.append({
                "chunk_id": f"chunk_{chunk_number}",
                "text": content,
                "start_word": start,
                "end_word": end,
            })

        if end == len(words):
            break

        start = end - overlap
        chunk_number += 1

    return chunks