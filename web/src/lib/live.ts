/**
 * Live updates over Server-Sent Events (backend services/events.py). Reconnects on drop; for
 * staff streams, an expired login is refreshed before reconnecting.
 */
import { useEffect, useRef } from "react";

import { api, auth } from "./api";

export type LiveEvent = { type: string; status?: string; code?: string; order_id?: string; new_paid?: boolean; new_order?: boolean; [k: string]: unknown };

export function useLive(path: string | null, onEvent: (e: LiveEvent) => void, opts: { staff?: boolean } = {}) {
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (!path) return;
    let es: EventSource | null = null;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (stopped) return;
      if (opts.staff && !auth.token()) {
        // After a reload the login is only a cookie: fetch an access token, then connect.
        void auth.ready().then((ok) => {
          if (ok && !stopped) connect();
        });
        return;
      }
      const token = opts.staff ? auth.token() : null;
      const url = `/api/v1${path}${token ? `${path.includes("?") ? "&" : "?"}access_token=${encodeURIComponent(token)}` : ""}`;
      es = new EventSource(url);
      es.onmessage = (m) => {
        try {
          handler.current(JSON.parse(m.data));
        } catch {
          /* ignore malformed */
        }
      };
      es.onerror = () => {
        es?.close();
        // A 401 (15-minute token) looks like an error here: refresh the login, then reconnect.
        const refresh = opts.staff ? api.get("/auth/me").catch(() => null) : Promise.resolve(null);
        retry = setTimeout(() => refresh.finally(connect), 2000);
      };
      // Something may have changed while we were disconnected.
      es.onopen = () => handler.current({ type: "reconnected" });
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      es?.close();
    };
  }, [path, opts.staff]);
}
