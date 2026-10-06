// Relative -- requests go through the Next.js Route Handler at
// app/api/[...path]/route.ts, which forwards to the backend server-side. Same
// origin as the page itself in every environment, so no CORS/URL-guessing needed.
const API_URL = "";

export class ApiError extends Error {
  status: number;
  // Raw `detail` from the backend: a string, or an object for structured 422s
  // (row errors / conflicts) that callers may want to render themselves.
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    // FormData: leave Content-Type unset so the browser adds the multipart boundary.
    ...(typeof options.body === "string" ? { "Content-Type": "application/json" } : {}),
    ...(options.body instanceof URLSearchParams ? { "Content-Type": "application/x-www-form-urlencoded" } : {}),
    ...(options.headers as Record<string, string> | undefined),
  };

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    const d = detail.detail;
    const message =
      typeof d === "string"
        ? d
        : d && typeof d === "object" && typeof d.message === "string"
          ? d.message
          : Array.isArray(d)
            ? d.map((e: { msg?: string }) => e.msg).filter(Boolean).join("; ") || res.statusText
            : res.statusText;
    throw new ApiError(res.status, message, d);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  postForm: <T,>(path: string, body: URLSearchParams) => request<T>(path, { method: "POST", body }),
  postMultipart: <T,>(path: string, body: FormData) => request<T>(path, { method: "POST", body }),
  del: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
  put: <T,>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
};
