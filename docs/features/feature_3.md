## Feature 3 — Coach Assist Agent

Build a simple agent that helps a coach answer a multi-step question by deciding which tools to use and in what order.
The agent must have access to at least two tools:
rag_search(query) — your Feature 1 RAG pipeline
analyze_history(user_id, question) — your Feature 2 analysis endpoint

Example multi-step questions the agent should handle:
- "Based on John's recent workout history, is he ready to increase bench press weight? What does proper progressive overload look like for his current level?"
- "My client hasn't done any pulling exercises this month and is complaining of shoulder tightness. What should I tell her?"

The agent must:
- Decide which tools to call and in what sequence — do not hardcode the call order
- Produce a single coherent response that cites both data sources when both are used
- Handle the case where one tool returns insufficient data gracefully
