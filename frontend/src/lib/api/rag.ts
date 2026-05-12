import type { RAGResponse } from "@/types/chat";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class RAGError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "RAGError";
  }
}

export async function queryRAG(
  question: string,
  maxSources = 5,
): Promise<RAGResponse> {
  const res = await fetch(`${API_BASE}/api/v1/rag/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, max_sources: maxSources }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new RAGError(
      res.status,
      body?.error?.message ?? `Request failed with status ${res.status}`,
    );
  }

  return res.json() as Promise<RAGResponse>;
}
