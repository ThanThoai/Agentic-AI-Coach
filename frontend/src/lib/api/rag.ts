import type { RAGResponse, RAGSource, TokenUsage, PipelineTrace } from "@/types/chat";
import { extractApiMessage } from "./errors";

const API_BASE = "";

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
    throw new RAGError(res.status, extractApiMessage(body, `Request failed (${res.status})`));
  }

  return res.json() as Promise<RAGResponse>;
}

interface StreamDoneEvent {
  type: "done";
  answer: string;
  in_scope: boolean;
  sources: RAGSource[];
  intent: string | null;
  model: string | null;
  usage: TokenUsage | null;
  trace: PipelineTrace | null;
}

/**
 * Stream a RAG query. Calls `onToken` for each incremental text chunk,
 * then resolves with the full RAGResponse when the stream ends.
 */
export async function queryRAGStream(
  question: string,
  onToken: (token: string) => void,
  maxSources = 5,
): Promise<RAGResponse> {
  const res = await fetch(`${API_BASE}/api/v1/rag/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, max_sources: maxSources }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new RAGError(res.status, extractApiMessage(body, `Request failed (${res.status})`));
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let donePayload: StreamDoneEvent | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    // SSE events are separated by double newline
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data: ")) continue;
      try {
        const data = JSON.parse(line.slice(6));
        if (data.type === "token") {
          onToken(data.content as string);
        } else if (data.type === "done") {
          donePayload = data as StreamDoneEvent;
        } else if (data.type === "error") {
          throw new RAGError(500, data.message ?? "Stream error");
        }
      } catch (e) {
        if (e instanceof RAGError) throw e;
        // ignore malformed SSE lines
      }
    }
  }

  if (!donePayload) {
    throw new RAGError(500, "Stream ended without a done event");
  }

  return {
    answer: donePayload.answer,
    in_scope: donePayload.in_scope,
    sources: donePayload.sources,
    intent: donePayload.intent,
    model: donePayload.model,
    usage: donePayload.usage,
    trace: donePayload.trace,
  };
}
