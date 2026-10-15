import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, http, onSessionExpired, setCsrfToken } from "./client";

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const apiError = (status: number, code: string, message: string, details?: unknown[]) => json(status, { error: { code, message, ...(details ? { details } : {}) } });

let calls: { url: string; method: string; csrf: string | null }[];
function mockFetch(handler: Handler) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      const headers = (init.headers ?? {}) as Record<string, string>;
      calls.push({ url, method: init.method ?? "GET", csrf: headers["X-CSRF-Token"] ?? null });
      return handler(url, init);
    }),
  );
}

beforeEach(() => setCsrfToken(null));
afterEach(() => vi.unstubAllGlobals());

describe("http client", () => {
  it("sends credentials and the CSRF token on unsafe requests only", async () => {
    setCsrfToken("token-1");
    mockFetch(() => json(200, { ok: true }));
    await http.get("/api/candidates", { q: "ada", skill: undefined, skip: 0 });
    await http.post("/api/candidates", { full_name: "Ada" });
    expect(calls[0]).toEqual({ url: "/api/candidates?q=ada&skip=0", method: "GET", csrf: null });
    expect(calls[1]).toEqual({ url: "/api/candidates", method: "POST", csrf: "token-1" });
    const init = vi.mocked(fetch).mock.calls[1]![1]!;
    expect(init.credentials).toBe("include");
  });

  it("fetches a CSRF token first when none is cached (e.g. after a reload)", async () => {
    mockFetch((url) => (url === "/api/auth/csrf" ? json(200, { csrf_token: "fresh" }) : json(201, { id: 1 })));
    await http.post("/api/jobs", {});
    expect(calls.map((call) => [call.url, call.csrf])).toEqual([
      ["/api/auth/csrf", null],
      ["/api/jobs", "fresh"],
    ]);
  });

  it("refreshes once on 401 and retries the original request", async () => {
    let meCalls = 0;
    mockFetch((url) => {
      if (url === "/api/auth/me") return ++meCalls === 1 ? apiError(401, "unauthorized", "Access session is invalid or expired") : json(200, { id: 7 });
      if (url === "/api/auth/csrf") return json(200, { csrf_token: "refresh-csrf" });
      if (url === "/api/auth/refresh") return json(200, { csrf_token: "rotated" });
      throw new Error(`unexpected ${url}`);
    });
    await expect(http.get("/api/auth/me")).resolves.toEqual({ id: 7 });
    expect(calls.map((call) => call.url)).toEqual(["/api/auth/me", "/api/auth/csrf", "/api/auth/refresh", "/api/auth/me"]);
    expect(calls[2]!.csrf).toBe("refresh-csrf");
  });

  it("shares one refresh between concurrent 401s", async () => {
    const seen = new Set<string>();
    mockFetch((url) => {
      if (url === "/api/auth/csrf") return json(200, { csrf_token: "c" });
      if (url === "/api/auth/refresh") return json(200, { csrf_token: "r" });
      if (!seen.has(url)) {
        seen.add(url);
        return apiError(401, "unauthorized", "expired");
      }
      return json(200, { url });
    });
    await Promise.all([http.get("/api/jobs"), http.get("/api/candidates")]);
    expect(calls.filter((call) => call.url === "/api/auth/refresh")).toHaveLength(1);
  });

  it("notifies listeners and throws when the session cannot be refreshed", async () => {
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);
    mockFetch((url) => (url === "/api/auth/csrf" ? apiError(401, "unauthorized", "Authentication required") : apiError(401, "unauthorized", "Authentication required")));
    await expect(http.get("/api/jobs")).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("re-fetches a rotated CSRF token once on a CSRF 403", async () => {
    setCsrfToken("stale");
    let attempts = 0;
    mockFetch((url) => {
      if (url === "/api/auth/csrf") return json(200, { csrf_token: "current" });
      return ++attempts === 1 ? apiError(403, "forbidden", "CSRF token is missing or invalid") : json(200, { ok: true });
    });
    await http.patch("/api/applications/1", { status: "Under Review" });
    expect(calls.map((call) => [call.url, call.csrf])).toEqual([
      ["/api/applications/1", "stale"],
      ["/api/auth/csrf", null],
      ["/api/applications/1", "current"],
    ]);
  });

  it("parses the backend error envelope and maps field errors", async () => {
    setCsrfToken("t");
    mockFetch(() =>
      apiError(422, "validation_error", "Request validation failed", [
        { location: ["body", "email"], message: "value is not a valid email address", code: "value_error" },
        { location: ["body", "education", 0, "degree"], message: "Field required", code: "missing" },
        { location: ["body"], message: "Value error, Criterion weights must sum to 100", code: "value_error" },
      ]),
    );
    const error = (await http.post("/api/candidates", {}).catch((caught: unknown) => caught)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("validation_error");
    expect(error.fieldErrors()).toEqual({
      email: "value is not a valid email address",
      "education.0.degree": "Field required",
      _form: "Criterion weights must sum to 100",
    });
  });

  it("turns network failures and 5xx into readable errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(http.get("/api/jobs")).rejects.toMatchObject({ code: "network_error", status: 0 });
    mockFetch(() => new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(http.get("/api/jobs")).rejects.toMatchObject({ status: 502, message: "The server could not complete the request. Please try again." });
  });
});
