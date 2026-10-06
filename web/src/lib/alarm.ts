/**
 * Alarms that ring until the action is done.
 *
 * - One looping sound (WebAudio buffer, loop=true) keeps playing in background tabs, where
 *   timers are slowed down; it stops only when no screen reports anything waiting.
 * - Browsers need one user gesture before sound: the first touch or key press anywhere unlocks
 *   it, so staff never hunt for an "enable" button.
 * - While ringing: the tab title flashes, phones vibrate, and when the tab is hidden a system
 *   notification stays up (requireInteraction) until the action is done.
 * - "Silence" mutes sound, vibration and the system notification for a while. It never hides
 *   anything: the bell and badge stay, and it rings again when something new arrives or time is up.
 * Without Web Push (deployment) nothing rings once the browser itself is closed.
 */
import { useEffect, useSyncExternalStore } from "react";

export type Tone = "order" | "payment" | "job" | "duty";

type Reason = { tone: Tone; count: number; title: string };

const reasons = new Map<string, Reason>();
const listeners = new Set<() => void>();
let ctx: AudioContext | null = null;
let source: AudioBufferSourceNode | null = null;
let playingTone: Tone | null = null;
let unlocked = false;
let titleTimer: ReturnType<typeof setInterval> | null = null;
let vibrateTimer: ReturnType<typeof setInterval> | null = null;
let notification: Notification | null = null;
let silencedUntil = 0;
let silencedCounts: Record<string, number> = {};
let silenceTimer: ReturnType<typeof setTimeout> | null = null;
let baseTitle = typeof document !== "undefined" ? document.title : "";

/** What is waiting right now, for the notification bell. Same list the sound uses. */
export type ActiveAlarm = { id: string; tone: Tone; count: number; title: string };
let active: ActiveAlarm[] = [];
let activeKey = "";

const notify = () => {
  const next = [...reasons]
    .filter(([, r]) => r.count > 0)
    .map(([id, r]) => ({ id, ...r }));
  const key = JSON.stringify(next);
  if (key !== activeKey) {
    activeKey = key; // new array only when something changed, so React re-renders only then
    active = next;
  }
  listeners.forEach((fn) => fn());
};

/** A 2.4 s pattern for each tone, looped. Square waves cut through kitchen noise. */
function buffer(c: AudioContext, tone: Tone): AudioBuffer {
  const patterns: Record<Tone, [number, number, number][]> = {
    order: [[0, 880, 0.18], [0.22, 880, 0.18], [0.44, 1320, 0.3]],
    payment: [[0, 660, 0.25], [0.35, 990, 0.25]],
    job: [[0, 1047, 0.12], [0.16, 1319, 0.12], [0.32, 1568, 0.25]],
    duty: [[0, 740, 0.4], [0.6, 740, 0.4]],
  };
  const beeps = patterns[tone]; // [start s, frequency Hz, length s]
  const length = Math.floor(c.sampleRate * 2.4);
  const buf = c.createBuffer(1, length, c.sampleRate);
  const data = buf.getChannelData(0);
  for (const [start, freq, dur] of beeps) {
    const s0 = Math.floor(start * c.sampleRate);
    const n = Math.floor(dur * c.sampleRate);
    for (let i = 0; i < n && s0 + i < length; i++) {
      const t = i / c.sampleRate;
      const env = Math.min(1, i / 400, (n - i) / 800); // soft edges, no clicks
      data[s0 + i] = 0.3 * env * (Math.sin(2 * Math.PI * freq * t) >= 0 ? 1 : -1);
    }
  }
  return buf;
}

function strongest(): Reason | null {
  const order: Tone[] = ["order", "duty", "job", "payment"];
  const list = [...reasons.values()].filter((r) => r.count > 0);
  list.sort((a, b) => order.indexOf(a.tone) - order.indexOf(b.tone));
  return list[0] ?? null;
}

function stopSound() {
  source?.stop();
  source?.disconnect();
  source = null;
  playingTone = null;
}

/** Silenced right now? A new reason, or a bigger count than when silenced, ends it early. */
function isSilenced(): boolean {
  if (Date.now() >= silencedUntil) return false;
  for (const [id, r] of reasons) if (r.count > (silencedCounts[id] ?? 0)) return false;
  return true;
}

function update() {
  if (silencedUntil && !isSilenced()) {
    silencedUntil = 0;
    silencedCounts = {};
  }
  const top = strongest();
  const loud = silencedUntil ? null : top;
  // Sound
  if (!loud) stopSound();
  else if (ctx && unlocked && playingTone !== loud.tone) {
    stopSound();
    source = ctx.createBufferSource();
    source.buffer = buffer(ctx, loud.tone);
    source.loop = true;
    source.connect(ctx.destination);
    source.start();
    playingTone = loud.tone;
  }
  // Title flash
  if (top && !titleTimer) {
    baseTitle = document.title;
    let on = false;
    titleTimer = setInterval(() => {
      const t = strongest();
      on = !on;
      document.title = on && t ? `🔔 (${t.count}) ${t.title}` : baseTitle;
    }, 1000);
  } else if (!top && titleTimer) {
    clearInterval(titleTimer);
    titleTimer = null;
    document.title = baseTitle;
  }
  // Vibration (phones)
  if (loud && !vibrateTimer && "vibrate" in navigator) {
    vibrateTimer = setInterval(() => navigator.vibrate?.([300, 150, 300]), 2400);
  } else if (!loud && vibrateTimer) {
    clearInterval(vibrateTimer);
    vibrateTimer = null;
  }
  // System notification while the tab is hidden; it stays until the action is done.
  if (loud && document.hidden && typeof Notification !== "undefined" && Notification.permission === "granted") {
    if (!notification || notification.title !== loud.title) {
      notification?.close();
      notification = new Notification(loud.title, { body: `${loud.count} waiting. Open Chakula to act.`, tag: "chakula-alarm", requireInteraction: true });
      notification.onclick = () => window.focus();
    }
  } else if (notification && (!loud || !document.hidden)) {
    notification.close();
    notification = null;
  }
  notify();
}

function unlock() {
  ctx ??= new AudioContext();
  void ctx.resume().then(() => {
    unlocked = ctx!.state === "running";
    if (typeof Notification !== "undefined" && Notification.permission === "default") void Notification.requestPermission();
    update();
  });
}

if (typeof window !== "undefined") {
  const once = () => unlock();
  window.addEventListener("pointerdown", once, { capture: true });
  window.addEventListener("keydown", once, { capture: true });
  document.addEventListener("visibilitychange", update);
}

/** Ring while `count` > 0. Several screens can ring at once; the most urgent tone plays. */
export function useAlarm(id: string, count: number, tone: Tone, title: string) {
  useEffect(() => {
    reasons.set(id, { tone, count, title });
    update();
  }, [id, count, tone, title]);
  useEffect(
    () => () => {
      reasons.delete(id);
      update();
    },
    [id],
  );
}

/** True when something is waiting but sound is still blocked (no touch yet). */
export function useAlarmBlocked(): boolean {
  return useSyncExternalStore(
    (fn) => (listeners.add(fn), () => listeners.delete(fn)),
    () => !unlocked && strongest() !== null,
  );
}

export function useAlarmUnlocked(): boolean {
  return useSyncExternalStore(
    (fn) => (listeners.add(fn), () => listeners.delete(fn)),
    () => unlocked,
  );
}

export function useActiveAlarms(): ActiveAlarm[] {
  return useSyncExternalStore(
    (fn) => (listeners.add(fn), () => listeners.delete(fn)),
    () => active,
  );
}

/** Mute the sound for a while. Anything new (or more of the same) rings again at once. */
export function silenceAlarm(minutes: number) {
  silencedUntil = Date.now() + minutes * 60_000;
  silencedCounts = Object.fromEntries([...reasons].map(([id, r]) => [id, r.count]));
  if (silenceTimer) clearTimeout(silenceTimer);
  silenceTimer = setTimeout(update, minutes * 60_000 + 50);
  update();
}

export function resumeAlarm() {
  silencedUntil = 0;
  silencedCounts = {};
  if (silenceTimer) clearTimeout(silenceTimer);
  update();
}

/** When the current silence ends (ms since epoch), or 0 when the alarm is live. */
export function useSilencedUntil(): number {
  return useSyncExternalStore(
    (fn) => (listeners.add(fn), () => listeners.delete(fn)),
    () => silencedUntil,
  );
}

export { unlock as unlockAlarm };

// Lets automated browser checks see whether the alarm is sounding (sound itself can't be heard).
if (typeof window !== "undefined") {
  const w = window as unknown as { __alarm?: () => string | null; __alarms?: () => Record<string, number> };
  w.__alarm = () => (source ? playingTone : null);
  w.__alarms = () => Object.fromEntries([...reasons].map(([id, r]) => [id, r.count]));
}
