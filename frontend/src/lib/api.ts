// Typed API client. Paths and payloads come from the generated OpenAPI types; nothing here
// hand-writes an API shape.
//
// Auth: the access token lives in memory only (never localStorage, so an XSS can't read a
// long-lived copy). On a 401 the client refreshes once using the httpOnly cookie, retries, and
// if that fails sends the user to /login. Concurrent 401s share one refresh.
import createClient from "openapi-fetch";

import type { components, paths } from "./api-schema";

export type Schemas = components["schemas"];

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSignedOut: () => void = () => {
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
};

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

export function setSignedOutHandler(handler: () => void): void {
  onSignedOut = handler;
}

export async function refreshAccessToken(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const response = await fetch("/v1/auth/refresh", { method: "POST", credentials: "same-origin" });
      if (!response.ok) {
        accessToken = null;
        return false;
      }
      const body = (await response.json()) as Schemas["TokenOut"];
      accessToken = body.access_token;
      return true;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

function withAuth(request: Request): Request {
  const headers = new Headers(request.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  return new Request(request, { headers, credentials: "same-origin" });
}

/** fetch with the bearer token and one refresh-and-retry on 401. */
export async function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const original = new Request(input, init);
  const retryCopy = original.clone();
  const response = await fetch(withAuth(original));
  if (response.status !== 401 || original.url.includes("/v1/auth/")) return response;
  if (await refreshAccessToken()) return fetch(withAuth(retryCopy));
  onSignedOut();
  return response;
}

export const api = createClient<paths>({ baseUrl: "", fetch: (request) => authFetch(request) });

/** An API error carrying the RFC 9457 problem body. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly problem: { title?: string; detail?: string | null; request_id?: string | null },
  ) {
    super(problem.detail ?? problem.title ?? `Request failed (${status})`);
  }
}

/** Turn an openapi-fetch result into data or a thrown ApiError, for React Query. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const problem = (result.error ?? {}) as ApiError["problem"];
    throw new ApiError(result.response.status, problem);
  }
  return result.data;
}
