/**
 * Web Push for staff and riders: alarms that still reach the phone when Chakula is closed.
 * The page rings by itself while it is open (alarm.ts); this only adds the closed-browser case.
 * Needs HTTPS (or localhost), a server with VAPID keys, and the person's permission.
 */
import { api } from "./api";

export type PushState = "unsupported" | "unavailable" | "blocked" | "off" | "on";

type PushConfig = { enabled: boolean; public_key: string | null };

const supported = () => typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

function keyBytes(b64url: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
  const raw = atob((b64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function registration() {
  return (await navigator.serviceWorker.getRegistration("/")) ?? navigator.serviceWorker.register("/sw.js");
}

export async function pushState(): Promise<PushState> {
  if (!supported()) return "unsupported";
  const cfg = await api.get<PushConfig>("/push/config").catch(() => null);
  if (!cfg?.enabled) return "unavailable";
  if (Notification.permission === "denied") return "blocked";
  const reg = await navigator.serviceWorker.getRegistration("/");
  const sub = await reg?.pushManager.getSubscription();
  return sub && Notification.permission === "granted" ? "on" : "off";
}

/** Ask permission, subscribe this browser, and tell the server. */
export async function enablePush(): Promise<PushState> {
  const cfg = await api.get<PushConfig>("/push/config");
  if (!supported() || !cfg.enabled || !cfg.public_key) return "unavailable";
  if ((await Notification.requestPermission()) !== "granted") return "blocked";
  const reg = await registration();
  await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(cfg.public_key) }));
  const json = sub.toJSON();
  await api.post("/push/subscribe", { endpoint: json.endpoint, keys: json.keys });
  return "on";
}

/** Stop alerts on this browser (also done when signing out, so the next person isn't woken). */
export async function disablePush(): Promise<void> {
  if (!supported()) return;
  const reg = await navigator.serviceWorker.getRegistration("/");
  const sub = await reg?.pushManager.getSubscription();
  if (!sub) return;
  await api.post("/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => undefined);
  await sub.unsubscribe().catch(() => undefined);
}
