import type { AgentResponse } from "@/types/chat";

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
    const body = await res.json().catch(() => ({ detail: res.statusText })) as {
      detail?: string;
    };
    throw new AgentError(res.status, body.detail ?? res.statusText);
  }

  return res.json() as Promise<AgentResponse>;
}
