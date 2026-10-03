/**
 * API client. Errors come back as {"error": {"code", "message", fields?}} (backend core/errors).
 * Access tokens last 15 minutes; on a 401 we rotate the refresh token once and retry.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields?: { loc: (string | number)[]; message: string }[],
    public extra?: Record<string, unknown>,
  ) {
    super(message);
  }
}

const BASE = "/api/v1";
const STORE = "hotel-auth";

export type Me = {
  id: string;
  role: "super_admin" | "hotel_admin" | "cashier" | "rider";
  hotel_id: string | null;
  name: string;
  phone: string;
};

export type Session = { access_token: string; refresh_token: string; user: Me };

function load(): Session | null {
  try {
    const raw = localStorage.getItem(STORE);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

let session: Session | null = load();
const listeners = new Set<() => void>();

function save(next: Session | null) {
  session = next;
  try {
    if (next) localStorage.setItem(STORE, JSON.stringify(next));
    else localStorage.removeItem(STORE);
  } catch {
    /* private mode: session lives in memory only */
  }
  listeners.forEach((fn) => fn());
}

export const auth = {
  user: () => session?.user ?? null,
  /** For EventSource (no headers): passed as ?access_token=. */
  token: () => session?.access_token ?? null,
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  async login(phone: string, password: string) {
    save(await request<Session>("POST", "/auth/login", { phone, password }, { auth: false }));
  },
  /** Sign-up endpoints return a login directly (rider registration). */
  adopt(next: Session) {
    save(next);
  },
  async logout() {
    const token = session?.refresh_token;
    save(null);
    if (token) await request("POST", "/auth/logout", { refresh_token: token }, { auth: false }).catch(() => {});
  },
};

let refreshing: Promise<boolean> | null = null;

async function refresh(): Promise<boolean> {
  if (!session) return false;
  // One refresh at a time: parallel 401s share it (a reused refresh token logs everyone out).
  refreshing ??= (async () => {
    try {
      const next = await request<Session>(
        "POST",
        "/auth/refresh",
        { refresh_token: session!.refresh_token },
        { auth: false },
      );
      save(next);
      return true;
    } catch {
      save(null);
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

type Options = { auth?: boolean; form?: FormData; retry?: boolean; headers?: Record<string, string> };

export async function request<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
  opts: Options = {},
): Promise<T> {
  const headers: Record<string, string> = { ...opts.headers };
  if (opts.auth !== false && session) headers.Authorization = `Bearer ${session.access_token}`;
  let payload: BodyInit | undefined;
  if (opts.form) payload = opts.form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let res: Response;
  try {
    res = await fetch(BASE + path, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "offline", "You're offline. Check your connection and try again.");
  }

  if (res.status === 401 && opts.auth !== false && opts.retry !== false && (await refresh())) {
    return request<T>(method, path, body, { ...opts, retry: false });
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const { code, message, fields, ...extra } = data?.error ?? {};
    throw new ApiError(res.status, code ?? "error", message ?? "Something went wrong", fields, extra);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: (path: string) => request<void>("DELETE", path),
  upload: <T>(path: string, file: Blob, name: string) => {
    const form = new FormData();
    form.append("file", file, name);
    return request<T>("POST", path, undefined, { form });
  },
};
