import type { DemoUser } from "@/types/chat";

const API_BASE = "";

export async function fetchDemoToken(userName: "alex" | "binh"): Promise<DemoUser> {
  const res = await fetch(`${API_BASE}/api/v1/auth/demo-token/${userName}`);
  if (!res.ok) throw new Error(`Failed to fetch demo token for ${userName}`);
  const data = await res.json() as { user_id: string; access_token: string; name: string };
  return { ...data, key: userName };
}
