/** Notification bell: shows exactly what is ringing (the same list that plays the sound),
 * plus things that wait quietly, each with a link to where it's fixed. "Silence" mutes the sound
 * for a while but hides nothing, and anything new rings again at once. */
import clsx from "clsx";
import { Bell, BellOff, BellRing, ChevronRight, Smartphone, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { disablePush, enablePush, pushState, type PushState } from "../lib/push";
import { type Tone, resumeAlarm, silenceAlarm, unlockAlarm, useActiveAlarms, useAlarmBlocked, useSilencedUntil } from "../lib/alarm";

export type QuietItem = { id: string; label: string; count: number; to: string };

const TONE: Record<Tone, { label: string; dot: string }> = {
  order: { label: "Order", dot: "bg-brand" },
  duty: { label: "Urgent", dot: "bg-bad" },
  job: { label: "Job", dot: "bg-ok" },
  payment: { label: "Payment", dot: "bg-warn" },
};

export function NotificationBell({ links, quiet = [] }: { links: Record<string, string>; quiet?: QuietItem[] }) {
  const ringing = useActiveAlarms();
  const blocked = useAlarmBlocked();
  const silencedUntil = useSilencedUntil();
  const waiting = quiet.filter((q) => q.count > 0);
  const total = ringing.reduce((n, a) => n + a.count, 0) + waiting.reduce((n, q) => n + q.count, 0);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const [push, setPush] = useState<PushState>("unavailable");
  const [pushBusy, setPushBusy] = useState(false);
  useEffect(() => {
    if (open) void pushState().then(setPush).catch(() => setPush("unavailable"));
  }, [open]);
  const togglePush = async () => {
    setPushBusy(true);
    try {
      if (push === "on") {
        await disablePush();
        setPush("off");
      } else setPush(await enablePush());
    } catch {
      setPush(await pushState().catch(() => "unavailable" as const));
    } finally {
      setPushBusy(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const silenced = silencedUntil > 0;
  const Icon = silenced ? BellOff : ringing.length ? BellRing : Bell;
  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={total ? `Notifications: ${total} waiting` : "Notifications"}
        aria-expanded={open}
        className={clsx(
          "relative flex size-10 items-center justify-center rounded-xl border",
          ringing.length && !silenced ? "border-bad/40 bg-bad-soft text-bad" : "border-line text-muted hover:bg-subtle",
        )}
      >
        <Icon className={clsx("size-5", ringing.length && !silenced && "animate-pulse")} />
        {total ? (
          <span className="absolute -top-1.5 -right-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-bad px-1 text-xs font-bold text-white ring-2 ring-surface">
            {total > 99 ? "99+" : total}
          </span>
        ) : null}
      </button>

      {open ? (
        <div role="dialog" aria-label="Notifications" className="fixed inset-x-4 top-16 z-50 overflow-hidden sm:absolute sm:inset-x-auto sm:top-full sm:right-0 sm:mt-2 sm:w-80 rounded-2xl border border-line bg-surface shadow-xl">
          <div className="border-b border-line px-4 py-3">
            <p className="font-bold">Notifications</p>
            <p className="text-xs text-muted">
              {silenced
                ? `Sound is silenced until ${new Date(silencedUntil).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}. Anything new rings again.`
                : ringing.length
                  ? "The alarm rings until each of these is dealt with."
                  : "Nothing is ringing."}
            </p>
          </div>
          {silenced ? (
            <button onClick={resumeAlarm} className="flex w-full items-center gap-2 border-b border-line bg-subtle px-4 py-2.5 text-left text-sm font-semibold hover:bg-line/40">
              <BellRing className="size-4 shrink-0" /> Turn the sound back on
            </button>
          ) : ringing.length ? (
            <div className="flex items-center gap-2 border-b border-line bg-subtle px-4 py-2.5">
              <BellOff className="size-4 shrink-0 text-muted" />
              <span className="flex-1 text-sm font-semibold">Silence for</span>
              {[10, 30, 60].map((m) => (
                <button key={m} onClick={() => silenceAlarm(m)} className="h-8 rounded-lg border border-line bg-surface px-2.5 text-sm font-semibold hover:bg-line/40">
                  {m === 60 ? "1 h" : `${m} min`}
                </button>
              ))}
            </div>
          ) : null}
          {blocked ? (
            <button onClick={unlockAlarm} className="flex w-full items-center gap-2 bg-bad-soft px-4 py-2.5 text-left text-sm font-semibold text-bad">
              <VolumeX className="size-4 shrink-0" /> Sound is off in this tab: tap to turn it on
            </button>
          ) : null}
          {push === "off" || push === "on" || push === "blocked" ? (
            <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
              <Smartphone className="size-4 shrink-0 text-muted" />
              <span className="min-w-0 flex-1 text-sm">
                <span className="block font-semibold">{push === "on" ? "Alerts on for this device" : "Alerts when Chakula is closed"}</span>
                <span className="block text-xs text-muted">
                  {push === "blocked" ? "Blocked in this browser's settings. Allow notifications for this site to use it." : push === "on" ? "You'll be woken even if the browser is closed." : "Get woken for new orders and jobs even if the browser is closed."}
                </span>
              </span>
              {push !== "blocked" ? (
                <button onClick={() => void togglePush()} disabled={pushBusy} className="h-8 shrink-0 rounded-lg border border-line bg-surface px-2.5 text-sm font-semibold hover:bg-subtle disabled:opacity-50">
                  {push === "on" ? "Turn off" : "Turn on"}
                </button>
              ) : null}
            </div>
          ) : null}
          <ul className="max-h-[60vh] overflow-y-auto">
            {ringing.map((a) => (
              <Row key={a.id} to={links[a.id]} onGo={() => setOpen(false)} dot={TONE[a.tone].dot} kind={`Ringing · ${TONE[a.tone].label}`} title={a.title} count={a.count} />
            ))}
            {waiting.length ? <li className="bg-subtle px-4 py-1.5 text-xs font-semibold tracking-wide text-muted uppercase">Also waiting (no sound)</li> : null}
            {waiting.map((q) => (
              <Row key={q.id} to={q.to} onGo={() => setOpen(false)} dot="bg-line" kind="Waiting" title={q.label} count={q.count} />
            ))}
            {!ringing.length && !waiting.length ? <li className="px-4 py-8 text-center text-sm text-muted">All quiet. You're up to date.</li> : null}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function Row({ to, onGo, dot, kind, title, count }: { to?: string; onGo: () => void; dot: string; kind: string; title: string; count: number }) {
  const body = (
    <>
      <span className={clsx("mt-1.5 size-2.5 shrink-0 rounded-full", dot)} />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">{title}</span>
        <span className="block text-xs text-muted">{kind} · {count} waiting</span>
      </span>
      {to ? <span className="flex items-center gap-0.5 self-center text-xs font-semibold text-brand">Go <ChevronRight className="size-3.5" /></span> : null}
    </>
  );
  return (
    <li className="border-b border-line last:border-b-0">
      {to ? (
        <Link to={to} onClick={onGo} className="flex items-start gap-3 px-4 py-3 hover:bg-subtle">{body}</Link>
      ) : (
        <div className="flex items-start gap-3 px-4 py-3">{body}</div>
      )}
    </li>
  );
}
