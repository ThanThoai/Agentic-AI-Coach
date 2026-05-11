Feature 1 — Fitness Knowledge RAG (Required)
Build a RAG pipeline that answers fitness-related questions using a provided knowledge base (~20 markdown documents). You may supplement with your own curated content — document what you added and why.
The system must:
    - Ingest documents, chunk them, and store embeddings in a vector database
    - Accept a natural language question via API and return a grounded answer
    - Include source references (which document/chunk was used) in the response
    - Handle out-of-scope questions gracefully — "What's the weather today?" must not produce a fitness answer