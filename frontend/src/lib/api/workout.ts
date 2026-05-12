import type { WorkoutAnalysisResponse } from "@/types/chat";
import { extractApiMessage } from "./errors";

const API_BASE = "";

export class WorkoutError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "WorkoutError";
  }
}

export async function analyzeWorkout(
  question: string,
  token: string,
  dateFrom?: string,
  dateTo?: string,
): Promise<WorkoutAnalysisResponse> {
  const body: Record<string, unknown> = { question };
  if (dateFrom) body.date_from = dateFrom;
  if (dateTo) body.date_to = dateTo;

  const res = await fetch(`${API_BASE}/api/v1/workout/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new WorkoutError(
      res.status,
      extractApiMessage(errBody, `Request failed (${res.status})`),
    );
  }

  return res.json() as Promise<WorkoutAnalysisResponse>;
}

interface WorkoutStreamDone {
  type: "done";
  answer: string;
  data_summary: WorkoutAnalysisResponse["data_summary"];
  question_type?: string;
  focus?: string | null;
  model: string | null;
  usage: WorkoutAnalysisResponse["usage"];
}

export async function analyzeWorkoutStream(
  question: string,
  token: string,
  onToken: (token: string) => void,
): Promise<WorkoutAnalysisResponse> {
  const res = await fetch(`${API_BASE}/api/v1/workout/analyze/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ question }),
  });

  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new WorkoutError(res.status, extractApiMessage(errBody, `Request failed (${res.status})`));
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let donePayload: WorkoutStreamDone | null = null;

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
        else if (data.type === "done") donePayload = data as unknown as WorkoutStreamDone;
        else if (data.type === "error") throw new WorkoutError(500, String(data.message ?? "Stream error"));
      } catch (e) {
        if (e instanceof WorkoutError) throw e;
      }
    }
  }

  if (!donePayload) throw new WorkoutError(500, "Stream ended without a done event");
  return {
    answer: donePayload.answer,
    data_summary: donePayload.data_summary,
    question_type: donePayload.question_type,
    focus: donePayload.focus ?? null,
    model: donePayload.model,
    usage: donePayload.usage,
  };
}
