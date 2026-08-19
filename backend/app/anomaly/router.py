import logging

logger = logging.getLogger(__name__)

# Keywords for rule-based classification
ANALYSIS_KEYWORDS = {
    "anomaly", "anomalies", "outlier", "duplicate", "flag", "detect", 
    "scan", "check", "analyze", "analysis", "unusual", "suspicious", 
    "discrepancy", "violation", "compliance"
}

LOOKUP_KEYWORDS = {
    "what", "who", "when", "where", "how", "tell me", "explain", 
    "describe", "policy", "rate", "agreement", "invoice", "contract"
}

def classify_query(query: str) -> str:
    """
    Classify the incoming query into 'lookup' or 'analysis' using a rule-based approach.
    """
    query_lower = query.lower()
    
    has_analysis = any(kw in query_lower for kw in ANALYSIS_KEYWORDS)
    has_lookup = any(kw in query_lower for kw in LOOKUP_KEYWORDS)
    
    if has_analysis and not has_lookup:
        return "analysis"
    elif has_lookup and not has_analysis:
        return "lookup"
    elif has_analysis and has_lookup:
        # When both match, analysis intent takes priority because
        # the lookup keywords are likely just context (e.g., "check
        # invoices for anomalies" -- the user wants analysis, not lookup)
        return "analysis"
    else:
        # Neither matched -- default to lookup (safer, no data mutation)
        return "lookup"

def classify_query_with_llm(query: str) -> str:
    """
    Optional LLM-assisted fallback function for classifying queries.
    Uses Ollama client if available, otherwise falls back to rule-based logic.
    """
    try:
        from app.llm.ollama_client import get_ollama_client
        
        prompt = f"""
        Classify the following query into exactly one of two categories: 'lookup' or 'analysis'.
        - 'lookup' means the user is asking for information retrieval, policies, specific values, or facts (e.g., "What is the rate for a senior engineer?").
        - 'analysis' means the user wants to detect anomalies, outliers, check compliance, or scan data for issues (e.g., "Check invoices for duplicates").
        
        Query: "{query}"
        
        Return only the category name ("lookup" or "analysis") in lowercase.
        """
        llm = get_ollama_client()
        response = llm.generate(prompt, temperature=0.1, max_output_tokens=10).strip().lower()
        if response in ["lookup", "analysis"]:
            return response
        else:
            logger.warning(f"Unexpected LLM response for query classification: {response}")
            return "lookup"
    except Exception as e:
        logger.warning(f"LLM classification failed, falling back to rule-based: {e}")
        return classify_query(query)
