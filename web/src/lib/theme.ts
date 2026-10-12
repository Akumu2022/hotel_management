/** Light / dark theme. Always opens in light; dark is a switch for the current visit only. */
import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
const listeners = new Set<() => void>();

let theme: Theme = "light";

function apply() {
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#2b2d31" : "#DC4B12");
}

export function setTheme(next: Theme) {
  theme = next;
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
