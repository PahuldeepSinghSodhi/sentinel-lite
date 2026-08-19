"""Text chunker — splits documents into overlapping chunks for embedding.

Uses a sliding-window approach based on word count (a reasonable proxy
for token count in English). Overlap ensures that important information
near chunk boundaries isn't lost — a sentence split across two chunks
will appear fully in at least one of them.
"""


def chunk_text(
    text: str,
    chunk_size: int = 400,
    chunk_overlap: int = 50,
) -> list[dict]:
    """Split text into overlapping chunks.
    
    Args:
        text: The full document text to chunk.
        chunk_size: Target number of words per chunk.
        chunk_overlap: Number of overlapping words between consecutive chunks.
        
    Returns:
        List of dicts, each with:
            - "text": the chunk's text content
            - "chunk_index": integer index (0-based) of this chunk
            - "word_count": number of words in this chunk
    """
    if not text or not text.strip():
        return []
    
    words = text.split()
    
    # If the entire text fits in one chunk, return it as-is
    if len(words) <= chunk_size:
        return [{
            "text": text.strip(),
            "chunk_index": 0,
            "word_count": len(words),
        }]
    
    chunks = []
    # Step size = chunk_size - overlap. This controls how far the window
    # slides forward on each iteration.
    step = chunk_size - chunk_overlap
    
    for i, start in enumerate(range(0, len(words), step)):
        end = min(start + chunk_size, len(words))
        chunk_words = words[start:end]
        
        chunks.append({
            "text": " ".join(chunk_words),
            "chunk_index": i,
            "word_count": len(chunk_words),
        })
        
        # Stop if we've reached the end of the document
        if end >= len(words):
            break
    
    return chunks
