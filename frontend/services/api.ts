export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
const API_ROOT = API_BASE.endsWith("/api") ? API_BASE : `${API_BASE}/api`;

export const API = {
  dashboard: `${API_ROOT}/dashboard`,
  signals: `${API_ROOT}/signals`,
  signal: (symbol: string) => `${API_ROOT}/signals/${encodeURIComponent(symbol)}`,
  predictions: `${API_ROOT}/predictions`,
  analytics: `${API_ROOT}/analytics/stats`,
  mlAnalytics: `${API_ROOT}/ml/analytics`,
  portfolio: `${API_ROOT}/paper-trade/portfolio`,
  paperTrade: (side: "buy" | "sell") => `${API_ROOT}/paper-trade/${side}`,
  executeSignal: `${API_ROOT}/paper-trade/execute-signal`,
  markets: `${API_ROOT}/coins`,
  coin: (symbol: string) => `${API_ROOT}/coins/${encodeURIComponent(symbol)}`,
  settings: `${API_ROOT}/settings`,
  login: `${API_ROOT}/auth/login`,
  register: `${API_ROOT}/auth/register`,
  websocket: (path = "/ws") => `${API_BASE.replace(/^http/, "ws").replace(/\/api$/, "")}${path}`
};

export function token(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("alphaforge_token");
}

function resolveUrl(pathOrUrl: string) {
  if (/^https?:\/\//.test(pathOrUrl)) return pathOrUrl;
  const path = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  if (path.startsWith("/api/")) return `${API_BASE}${path}`;
  return `${API_ROOT}${path}`;
}

export async function api<T>(pathOrUrl: string, options: RequestInit = {}): Promise<T> {
  const url = resolveUrl(pathOrUrl);
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  const auth = token();
  if (auth) headers.set("Authorization", `Bearer ${auth}`);
  let response: Response;
  try {
    response = await fetch(url, { ...options, headers, cache: "no-store" });
  } catch (err) {
    console.error("API Request Failed", url, 0, err);
    throw err;
  }
  if (!response.ok) {
    const body = await response.json().catch(async () => response.text().catch(() => ""));
    console.error("API Request Failed", url, response.status, body);
    throw new Error((typeof body === "object" && body && "detail" in body ? String(body.detail) : "") || "Request failed");
  }
  return response.json();
}

export async function auth(path: "/auth/login" | "/auth/register", payload: Record<string, string>) {
  const result = await api<{ access_token: string; user: Record<string, unknown> }>(path === "/auth/login" ? API.login : API.register, { method: "POST", body: JSON.stringify(payload) });
  localStorage.setItem("alphaforge_token", result.access_token);
  return result;
}
