/**
 * API client. Errors come back as {"error": {"code", "message", fields?}} (backend core/errors).
 * Access tokens last 15 minutes; on a 401 we rotate the refresh token (an httpOnly cookie) once
 * and retry.
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
// D29: only the (non-secret) profile is kept in the browser, to draw the screens. The refresh
// token is an httpOnly cookie the page can't read; the 15-minute access token lives in memory.
const USER_STORE = "chakula-user";
const OLD_STORE = "hotel-auth"; // before D29: whole session incl. refresh token. Migrated once.

export type Me = {
  id: string;
  role: "super_admin" | "hotel_admin" | "cashier" | "rider";
  hotel_id: string | null;
  name: string;
  phone: string;
  must_change_password?: boolean; // after an admin reset (D28)
};

/** What login, refresh and sign-up return. The refresh token comes as a cookie, not here. */
export type Session = { access_token: string; user: Me };

function read<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

let user: Me | null = read<Me>(USER_STORE);
let accessToken: string | null = null; // memory only
const listeners = new Set<() => void>();

function save(next: Session | null) {
  user = next?.user ?? null;
  accessToken = next?.access_token ?? null;
  try {
    if (user) localStorage.setItem(USER_STORE, JSON.stringify(user));
    else localStorage.removeItem(USER_STORE);
  } catch {
    /* private mode: the profile lives in memory only */
  }
  listeners.forEach((fn) => fn());
}

// One-time move of an old stored session to the cookie: refresh with it, then forget it.
let migrating: Promise<unknown> | null = null;
{
  const old = read<{ refresh_token?: string; user?: Me }>(OLD_STORE);
  if (old) {
    try {
      localStorage.removeItem(OLD_STORE);
    } catch {
      /* ignore */
    }
    if (old.refresh_token && old.user) {
      user = old.user;
      migrating = fetch(BASE + "/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: old.refresh_token }),
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((next: Session | null) => save(next))
        .catch(() => save(null))
        .finally(() => (migrating = null));
    }
  }
}

export const auth = {
  user: () => user,
  /** For EventSource (no headers): passed as ?access_token=. May be null right after a reload. */
  token: () => accessToken,
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  async login(phone: string, password: string) {
    save(await request<Session>("POST", "/auth/login", { phone, password }, { auth: false }));
  },
  async changePassword(current_password: string, new_password: string) {
    save(await request<Session>("POST", "/auth/change-password", { current_password, new_password }));
  },
  /** Sign-up endpoints return a login directly (rider registration). */
  adopt(next: Session) {
    save(next);
  },
  /** Make sure there is a fresh access token (after a reload it exists only as the cookie). */
  async ready(): Promise<boolean> {
    if (migrating) await migrating;
    return accessToken ? true : refresh();
  },
  async logout() {
    save(null);
    await request("POST", "/auth/logout", undefined, { auth: false }).catch(() => {});
  },
};

let refreshing: Promise<boolean> | null = null;

async function refresh(): Promise<boolean> {
  if (!user) return false;
  // One refresh at a time, in this tab and across tabs: refresh tokens rotate, and presenting an
  // already-used one logs every session out (token theft protection).
  refreshing ??= (async () => {
    const run = async () => {
      try {
        save(await request<Session>("POST", "/auth/refresh", undefined, { auth: false }));
        return true;
      } catch {
        save(null);
        return false;
      }
    };
    try {
      return navigator.locks ? await navigator.locks.request("chakula-refresh", run) : await run();
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
  // Logged in but no token yet (fresh page load): get one first instead of a wasted 401.
  if (opts.auth !== false && user && !accessToken) await auth.ready();
  if (opts.auth !== false && accessToken) headers.Authorization = `Bearer ${accessToken}`;
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
