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
