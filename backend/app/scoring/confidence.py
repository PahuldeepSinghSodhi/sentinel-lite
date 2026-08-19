import re
from typing import List, Dict, Any

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't", "as", "at", 
    "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can't", "cannot", "could", 
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during", "each", "few", "for", 
    "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", 
    "her", "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", 
    "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", 
    "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours", 
    "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", 
    "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there", 
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those", "through", "to", "too", 
    "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", 
    "what's", "when", "when's", "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", 
    "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
}

def extract_entities(text: str) -> set:
    """Extract heuristic proper nouns (capitalized words not at start of sentence) and numbers."""
    entities = set()
    sentences = re.split(r'[.!?]+', text)
    for sentence in sentences:
        words = re.findall(r'\b\w+\b', sentence)
        for i, word in enumerate(words):
            if word.isdigit():
                entities.add(word)
            elif i > 0 and word.istitle() and word.lower() not in STOP_WORDS:
                entities.add(word)
    return entities

def compute_confidence(query: str, chunks: List[Dict[str, Any]], answer: str) -> Dict[str, Any]:
    """
    Computes a confidence score for RAG answers based on retrieval quality metrics.
    """
    if not chunks:
        return {
            "overall_confidence": 0.0,
            "retrieval_score": 0.0,
            "source_agreement": 0.0,
            "coverage_score": 0.0,
            "answer_grounding": 0.0,
            "confidence_level": "low"
        }

    top_3_chunks = chunks[:3]
    num_chunks = len(top_3_chunks)
    
    # 1. Retrieval Score (weight: 0.4)
    retrieval_score = sum(max(0.0, min(1.0, float(c.get('score', 0.0)))) for c in top_3_chunks) / num_chunks
    
    # 2. Source Agreement (weight: 0.2)
    sources = [c.get('source') for c in top_3_chunks if c.get('source')]
    if not sources:
        source_agreement = 0.0
    else:
        source_counts = {src: sources.count(src) for src in set(sources)}
        max_count = max(source_counts.values())
        source_agreement = max_count / num_chunks
        
    # 3. Coverage Score (weight: 0.2)
    query_words = set(re.findall(r'\b\w+\b', query.lower()))
    sig_query_words = query_words - STOP_WORDS
    if not sig_query_words:
        coverage_score = 1.0
    else:
        combined_text = " ".join(c.get('text', '').lower() for c in top_3_chunks)
        chunk_words = set(re.findall(r'\b\w+\b', combined_text))
        matched = sig_query_words.intersection(chunk_words)
        coverage_score = len(matched) / len(sig_query_words)
        
    # 4. Answer Grounding (weight: 0.2)
    combined_context = " ".join(c.get('text', '') for c in chunks)
    context_entities = extract_entities(combined_context)
    
    answer_sentences = [s.strip() for s in re.split(r'[.!?]+', answer) if s.strip()]
    if not answer_sentences:
        answer_grounding = 0.0
    else:
        grounded_sentences = 0
        for sentence in answer_sentences:
            sentence_entities = extract_entities(sentence)
            if sentence_entities.intersection(context_entities):
                grounded_sentences += 1
                
        answer_grounding = grounded_sentences / len(answer_sentences)
        
    overall = (retrieval_score * 0.4) + (source_agreement * 0.2) + (coverage_score * 0.2) + (answer_grounding * 0.2)
    overall = max(0.0, min(1.0, overall))
    
    if overall > 0.7:
        level = "high"
    elif overall >= 0.4:
        level = "medium"
    else:
        level = "low"
        
    return {
        "overall_confidence": round(overall, 4),
        "retrieval_score": round(retrieval_score, 4),
        "source_agreement": round(source_agreement, 4),
        "coverage_score": round(coverage_score, 4),
        "answer_grounding": round(answer_grounding, 4),
        "confidence_level": level
    }
