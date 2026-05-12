import type { DemoUser, UserRole } from "@/types/chat";

const API_BASE = "";

type DemoUserName = "alex" | "binh" | "coach";

export async function fetchDemoToken(userName: DemoUserName): Promise<DemoUser> {
  const res = await fetch(`${API_BASE}/api/v1/auth/demo-token/${userName}`);
  if (!res.ok) throw new Error(`Failed to fetch demo token for ${userName}`);
  const data = await res.json() as {
    user_id: string;
    access_token: string;
    name: string;
    role: UserRole;
  };
  return { ...data, key: userName };
}
