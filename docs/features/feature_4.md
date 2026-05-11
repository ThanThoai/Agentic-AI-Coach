## Feature 4 — Evaluation Pipeline (Required)

Build an evaluation system that measures the quality of your RAG, analysis, and agent outputs.

Requirements:

- Create a test set of at least 15 question-answer pairs: 5 for RAG, 5 for workout analysis, 3 for the agent, 2 adversarial cases targeting guardrails
- Implement at least 3 evaluation metrics — one must be an LLM-as-judge metric (e.g. faithfulness, tone quality), one must be rule-based (e.g. source attribution present, data values referenced)
- Run the evaluation and include results in your submission
- Write an honest analysis: what failed, what surprised you, what you would change