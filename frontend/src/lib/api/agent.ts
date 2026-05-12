import type { AgentResponse } from "@/types/chat";
import { extractApiMessage } from "./errors";

const API_BASE = "";

export class AgentError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "AgentError";
  }
}

export async function askAgent(
  question: string,
  token: string,
): Promise<AgentResponse> {
  const res = await fetch(`${API_BASE}/api/v1/agent/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ question }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new AgentError(res.status, extractApiMessage(body, `Request failed (${res.status})`));
  }

  return res.json() as Promise<AgentResponse>;
}

interface AgentStreamDone {
  type: "done";
  answer: string;
  tools_used: string[];
  iterations: number;
  usage: AgentResponse["usage"];
}

export async function askAgentStream(
  question: string,
  token: string,
  onToken: (token: string) => void,
  onStatus?: (tools: string[]) => void,
): Promise<AgentResponse> {
  const res = await fetch(`${API_BASE}/api/v1/agent/ask/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ question }),
  });

  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new AgentError(res.status, extractApiMessage(errBody, `Request failed (${res.status})`));
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let donePayload: AgentStreamDone | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data: ")) continue;
      try {
        const data = JSON.parse(line.slice(6)) as Record<string, unknown>;
        if (data.type === "token") onToken(data.content as string);
        else if (data.type === "status") onStatus?.(data.tools as string[]);
        else if (data.type === "done") donePayload = data as unknown as AgentStreamDone;
        else if (data.type === "ping") { /* keepalive — ignore */ }
        else if (data.type === "error") throw new AgentError(500, String(data.message ?? "Stream error"));
      } catch (e) {
        if (e instanceof AgentError) throw e;
      }
    }
  }

  if (!donePayload) throw new AgentError(500, "Stream ended without a done event");
  return {
    answer: donePayload.answer,
    tools_used: donePayload.tools_used,
    iterations: donePayload.iterations,
    usage: donePayload.usage,
  };
}
