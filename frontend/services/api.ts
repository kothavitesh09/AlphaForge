const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export function token(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("alphaforge_token");
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  const auth = token();
  if (auth) headers.set("Authorization", `Bearer ${auth}`);
  const response = await fetch(`${API_URL}${path}`, { ...options, headers, cache: "no-store" });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Request failed");
  return response.json();
}

export async function auth(path: "/auth/login" | "/auth/register", payload: Record<string, string>) {
  const result = await api<{ access_token: string; user: Record<string, unknown> }>(path, { method: "POST", body: JSON.stringify(payload) });
  localStorage.setItem("alphaforge_token", result.access_token);
  return result;
}
