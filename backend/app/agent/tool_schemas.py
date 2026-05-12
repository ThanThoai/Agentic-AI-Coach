from app.llm.base import ToolDefinition

TOOL_SCHEMAS: list[ToolDefinition] = [
    ToolDefinition(
        name="analyze_history",
        description=(
            "Analyse a specific athlete's workout history to answer questions about their "
            "training trends, exercise progression, muscle balance, deload weeks, or readiness "
            "to progress. Always specify the athlete by name. "
            "When the question covers ALL athletes, call this tool once per athlete name."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "athlete": {
                    "type": "string",
                    "description": (
                        "Name of the athlete to analyse. Must exactly match one of the names "
                        "in the roster provided in the system prompt (e.g. 'Alex', 'Binh'). "
                        "For all-athlete queries, call this tool once per athlete."
                    ),
                    "minLength": 1,
                    "maxLength": 50,
                },
                "question": {
                    "type": "string",
                    "description": (
                        "The specific analytical question to answer from the athlete's workout data. "
                        "Be precise — for example: 'bench press weight trend over last 4 weeks', "
                        "'push/pull volume ratio this month', 'muscles not trained in the last 14 days'."
                    ),
                    "minLength": 5,
                    "maxLength": 500,
                },
                "date_from": {
                    "type": "string",
                    "format": "date",
                    "description": "Start of analysis window (ISO-8601 date). Defaults to 90 days ago if omitted.",
                },
                "date_to": {
                    "type": "string",
                    "format": "date",
                    "description": "End of analysis window (ISO-8601 date). Defaults to today if omitted.",
                },
            },
            "required": ["athlete", "question"],
        },
    ),
    ToolDefinition(
        name="rag_search",
        description=(
            "Search the fitness knowledge base for general training, nutrition, and programming "
            "information. Use this when the question asks about principles, techniques, or general "
            "advice that doesn't depend on any specific athlete's workout history."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A focused search query. Rephrase the user's question as a targeted "
                        "knowledge lookup. Examples: 'progressive overload principles for "
                        "intermediate lifters', 'RPE scale usage in strength training', "
                        "'shoulder impingement prevention exercises'."
                    ),
                    "minLength": 3,
                    "maxLength": 300,
                },
            },
            "required": ["query"],
        },
    ),
]
