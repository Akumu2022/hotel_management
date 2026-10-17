/** Which part of Chakula the customer is looking at: food hotels or drinks (liquor stores). The
 * header switch and the home page share it, and it is remembered for the visit. */
import { useSyncExternalStore } from "react";

export type Section = "hotel" | "liquor";
const KEY = "chakula.section";
const listeners = new Set<() => void>();

function read(): Section {
  try {
    return sessionStorage.getItem(KEY) === "liquor" ? "liquor" : "hotel";
  } catch {
    return memory;
  }
}
let memory: Section = "hotel";

export function setSection(s: Section) {
  memory = s;
  try {
    sessionStorage.setItem(KEY, s);
  } catch {
    /* kept in memory for this visit */
  }
  listeners.forEach((fn) => fn());
}

export const useSection = (): Section => useSyncExternalStore((fn) => (listeners.add(fn), () => listeners.delete(fn)), read);
