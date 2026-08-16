// Relative -- requests go through Next.js's own rewrite proxy (see
// next.config.js), which forwards to the backend server-side. Same origin
// as the page itself in every environment, so no CORS/URL-guessing needed.
const API_URL = "";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("access_token");
}

export function setToken(token: string) {
  window.localStorage.setItem("access_token", token);
}

export function clearToken() {
  window.localStorage.removeItem("access_token");
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.body && !(options.body instanceof URLSearchParams) ? { "Content-Type": "application/json" } : {}),
    ...(options.body instanceof URLSearchParams ? { "Content-Type": "application/x-www-form-urlencoded" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers as Record<string, string> | undefined),
  };

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, detail.detail || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  postForm: <T,>(path: string, body: URLSearchParams) => request<T>(path, { method: "POST", body }),
};
