// Centralized HTTP client for the FastAPI backend.
//
// Auth model (see README "Authentication and browser clients"):
// - Access/refresh credentials are HttpOnly cookies; the browser sends them automatically.
// - Unsafe requests carry an X-CSRF-Token header. The token lives only in memory and is
//   re-fetched from GET /api/auth/csrf after a page reload.
// - A 401 triggers one shared refresh (POST /api/auth/refresh) and a single retry. If refresh
//   fails the session is over and listeners registered with onSessionExpired are notified.

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

export interface FieldErrorDetail {
  location: (string | number)[];
  message: string;
  code: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: FieldErrorDetail[];

  constructor(status: number, code: string, message: string, details: FieldErrorDetail[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Map validation details to form field paths, e.g. ["body","education",0,"degree"] -> "education.0.degree". */
  fieldErrors(): Record<string, string> {
    const result: Record<string, string> = {};
    for (const detail of this.details) {
      const path = detail.location.filter((part, index) => !(index === 0 && (part === "body" || part === "query" || part === "path")));
      const key = path.join(".") || "_form";
      result[key] ??= detail.message.replace(/^Value error, /, "");
    }
    return result;
  }
}

export const isApiError = (error: unknown): error is ApiError => error instanceof ApiError;

type Query = Record<string, string | number | boolean | null | undefined>;
type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
  /** "blob" returns the raw response body (file downloads). */
  responseType?: "json" | "blob";
}

const SAFE_METHODS = new Set<Method>(["GET"]);
const PUBLIC_AUTH_PATHS = new Set(["/api/auth/login", "/api/auth/register"]);
const NO_REFRESH_PATHS = new Set(["/api/auth/login", "/api/auth/register", "/api/auth/refresh", "/api/auth/csrf"]);

let csrfToken: string | null = null;
let csrfRequest: Promise<string> | null = null;
let refreshRequest: Promise<boolean> | null = null;
const expiryListeners = new Set<() => void>();

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function onSessionExpired(listener: () => void): () => void {
  expiryListeners.add(listener);
  return () => expiryListeners.delete(listener);
}

function buildUrl(path: string, query?: Query) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    params.append(key, String(value));
  }
  const search = params.toString();
  return `${API_BASE_URL}${path}${search ? `?${search}` : ""}`;
}

async function parseError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = response.statusText || "Request failed";
  let details: FieldErrorDetail[] = [];
  try {
    const data = await response.json();
    if (data?.error) {
      code = data.error.code ?? code;
      message = data.error.message ?? message;
      details = Array.isArray(data.error.details) ? data.error.details : [];
    }
  } catch {
    // Non-JSON error body (e.g. a proxy error page); keep the HTTP status text.
  }
  if (response.status >= 500) message = "The server could not complete the request. Please try again.";
  return new ApiError(response.status, code, message, details);
}

async function rawFetch(method: Method, path: string, options: RequestOptions, csrf: string | null) {
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers: Record<string, string> = { Accept: options.responseType === "blob" ? "*/*" : "application/json" };
  // Multipart bodies set their own Content-Type (with the boundary).
  if (options.body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (csrf && !SAFE_METHODS.has(method)) headers["X-CSRF-Token"] = csrf;
  try {
    return await fetch(buildUrl(path, options.query), {
      method,
      headers,
      credentials: "include",
      body: options.body === undefined ? undefined : isForm ? (options.body as FormData) : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") throw error;
    throw new ApiError(0, "network_error", "Cannot reach the server. Check your connection and try again.");
  }
}

async function fetchCsrfToken(): Promise<string> {
  csrfRequest ??= (async () => {
    const response = await rawFetch("GET", "/api/auth/csrf", {}, null);
    if (!response.ok) throw await parseError(response);
    const data = (await response.json()) as { csrf_token: string };
    csrfToken = data.csrf_token;
    return data.csrf_token;
  })().finally(() => {
    csrfRequest = null;
  });
  return csrfRequest;
}

/** Rotate the session using the refresh cookie. Resolves false when the session cannot be renewed. */
export function refreshSession(): Promise<boolean> {
  refreshRequest ??= (async () => {
    try {
      const token = await fetchCsrfToken();
      const response = await rawFetch("POST", "/api/auth/refresh", {}, token);
      if (!response.ok) return false;
      const data = (await response.json()) as { csrf_token: string };
      csrfToken = data.csrf_token;
      return true;
    } catch {
      return false;
    }
  })().finally(() => {
    refreshRequest = null;
  });
  return refreshRequest;
}

async function request<T>(method: Method, path: string, options: RequestOptions = {}, attempt = 0): Promise<T> {
  const needsCsrf = !SAFE_METHODS.has(method) && !PUBLIC_AUTH_PATHS.has(path);
  if (needsCsrf && !csrfToken) {
    try {
      await fetchCsrfToken();
    } catch (error) {
      if (!(isApiError(error) && error.status === 401)) throw error;
      // No usable session: send without a token so the 401 path below handles expiry uniformly.
    }
  }
  const response = await rawFetch(method, path, options, csrfToken);

  if (response.status === 401 && attempt === 0 && !NO_REFRESH_PATHS.has(path)) {
    if (await refreshSession()) return request<T>(method, path, options, attempt + 1);
    csrfToken = null;
    expiryListeners.forEach((listener) => listener());
    throw await parseError(response);
  }
  if (response.status === 403 && needsCsrf && attempt === 0) {
    const error = await parseError(response.clone());
    if (/csrf/i.test(error.message)) {
      csrfToken = null;
      await fetchCsrfToken();
      return request<T>(method, path, options, attempt + 1);
    }
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  if (options.responseType === "blob") return (await response.blob()) as T;
  return (await response.json()) as T;
}

export const http = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, { body, query }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body }),
  patch: <T>(path: string, body?: unknown, query?: Query) => request<T>("PATCH", path, { body, query }),
  delete: <T = void>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, { body: form }),
  blob: (path: string) => request<Blob>("GET", path, { responseType: "blob" }),
};
