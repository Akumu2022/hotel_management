/** A small "Saved" message for the staff and owner screens, so a save never goes unnoticed. */
import { CheckCircle2 } from "lucide-react";
import { useSyncExternalStore } from "react";

let state: { id: number; text: string } | null = null;
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setTimeout> | undefined;

export function toast(text: string) {
  state = { id: Date.now(), text };
  listeners.forEach((fn) => fn());
  clearTimeout(timer);
  timer = setTimeout(() => {
    state = null;
    listeners.forEach((fn) => fn());
  }, 2400);
}

export function Toaster() {
  const t = useSyncExternalStore(
    (fn) => (listeners.add(fn), () => listeners.delete(fn)),
    () => state,
  );
  return (
    <div className="pointer-events-none fixed inset-x-0 top-4 z-[80] flex justify-center px-4" aria-live="polite">
      {t ? (
        <div key={t.id} role="status" className="flex animate-[toast-in_.25s_ease-out] items-center gap-2.5 rounded-full bg-ink py-2.5 pr-5 pl-3 text-sm font-medium text-white shadow-xl">
          <CheckCircle2 className="size-5 text-green-400" />
          {t.text}
        </div>
      ) : null}
    </div>
  );
}
