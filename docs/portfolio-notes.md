# Portfolio wording for Sentinel-Lite

Suggested description:

> Built a local procurement review assistant that combines FastAPI, FAISS-based document retrieval, Ollama-generated answers, and deterministic transaction checks. Reviewers can upload a transaction CSV and approved rate card, inspect source-linked findings, record decisions, and export a case report.

> Added case-specific SQLite history and citations to PDF pages, TXT lines, and CSV rows. Evaluated the detector on a 240-transaction synthetic benchmark with 75% precision, 100% recall, and 85.7% F1; documented the false positives and limits of synthetic testing.

Accuracy notes for interviews:

- This implementation calls sentence-transformers and FAISS directly. It does not use LangChain; remove LangChain from résumé keywords unless it is actually added and used.
- Ollama runs locally in the documented setup. The project does not prove enterprise security, access controls, or compliance certification.
- The 240-transaction benchmark is synthetic. Do not claim measured manual-review time savings or real-world accuracy without a study.
- The 20-question RAG harness measures retrieval and answer similarity on bundled sample documents. CI runs retrieval-only checks without an Ollama server.
- The anomaly engine uses explicit duplicate, Z-score, IQR, and approved-rate rules; it is not a trained fraud classifier.
