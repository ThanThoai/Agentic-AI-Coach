import type { WorkoutAnalysisResponse } from "@/types/chat";

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
    const err = await res.json().catch(() => ({})) as Record<string, unknown>;
    const msg =
      typeof err.detail === "string"
        ? err.detail
        : `Request failed with status ${res.status}`;
    throw new WorkoutError(res.status, msg);
  }

  return res.json() as Promise<WorkoutAnalysisResponse>;
}
