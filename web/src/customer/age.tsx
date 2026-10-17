/** Liquor stores are for people 18 and older: the customer confirms once, and the phone remembers. */
import { ShieldAlert } from "lucide-react";
import { useSyncExternalStore } from "react";

import { useT } from "../lib/i18n";

const KEY = "chakula.age18";
let memory = false; // used when the browser won't let us store anything
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return memory || localStorage.getItem(KEY) === "1";
  } catch {
    return memory;
  }
}

export function confirmAge() {
  memory = true;
  try {
    localStorage.setItem(KEY, "1");
  } catch {
    /* kept in memory for this visit */
  }
  listeners.forEach((fn) => fn());
}

export const ageConfirmed = read;

export function useAgeConfirmed(): boolean {
  return useSyncExternalStore((fn) => (listeners.add(fn), () => listeners.delete(fn)), read);
}

export function AgeGate({ onNo }: { onNo: () => void }) {
  const t = useT();
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-line bg-surface px-6 py-10 text-center">
      <span className="flex size-14 items-center justify-center rounded-full bg-warn-soft text-warn"><ShieldAlert className="size-7" /></span>
      <p className="text-lg font-semibold">{t("Are you 18 or older?")}</p>
      <p className="max-w-xs text-sm text-muted">{t("Alcohol is sold only to people aged 18 and over. The rider will check your ID at the door.")}</p>
      <div className="mt-2 flex w-full max-w-xs flex-col gap-2">
        <button type="button" onClick={confirmAge} className="h-11 rounded-full bg-brand text-sm font-bold text-white shadow-md shadow-brand/25">
          {t("Yes, I am 18 or older")}
        </button>
        <button type="button" onClick={onNo} className="h-11 rounded-full border border-line text-sm font-semibold hover:bg-subtle">
          {t("No, go back")}
        </button>
      </div>
    </div>
  );
}
