/** Light / dark theme. Follows the phone's setting until the user picks one. */
import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
const KEY = "theme-v1";
const listeners = new Set<() => void>();

function systemDark() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

function current(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    if (t === "light" || t === "dark") return t;
  } catch {
    /* ignore */
  }
  return systemDark() ? "dark" : "light";
}

let theme: Theme = current();

function apply() {
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#17171a" : "#DC4B12");
}

export function setTheme(next: Theme) {
  theme = next;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* ignore */
  }
  apply();
  listeners.forEach((fn) => fn());
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    (fn) => (listeners.add(fn), () => listeners.delete(fn)),
    () => theme,
  );
}

apply();
