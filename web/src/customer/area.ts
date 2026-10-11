/**
 * Where the customer is, so the home page shows only hotels near them.
 * Order of trust: this phone's GPS (asked once, refreshed silently while permission stays
 * granted), the last delivery pin they dropped, then a town they pick. Stored on the phone only.
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";

import { distanceKm } from "../lib/geo";
import { profile } from "./store";

export type Area = { lat: number; lng: number; label: string; source: "gps" | "pin" | "town" };

export const TOWNS: { name: string; lat: number; lng: number }[] = [
  { name: "Bungoma", lat: 0.5636, lng: 34.5606 },
  { name: "Kakamega", lat: 0.2827, lng: 34.7519 },
  { name: "Kisumu", lat: -0.0917, lng: 34.768 },
  { name: "Eldoret", lat: 0.5143, lng: 35.2698 },
  { name: "Nakuru", lat: -0.3031, lng: 36.08 },
  { name: "Nairobi", lat: -1.2921, lng: 36.8219 },
  { name: "Mombasa", lat: -4.0435, lng: 39.6682 },
];

const KEY = "area-v1";
const listeners = new Set<() => void>();

function readArea(): Area | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Area) : null;
  } catch {
    return null;
  }
}

let current: Area | null = readArea();

export function setArea(next: Area | null) {
  current = next;
  try {
    if (next) localStorage.setItem(KEY, JSON.stringify(next));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: keep it in memory for this visit */
  }
  listeners.forEach((fn) => fn());
}

/** "Bungoma" when within 40 km of a known town, else a plain "your location". */
export function labelFor(lat: number, lng: number): string {
  let best: { name: string; km: number } | null = null;
  for (const t of TOWNS) {
    const km = distanceKm(lat, lng, t.lat, t.lng);
    if (!best || km < best.km) best = { name: t.name, km };
  }
  return best && best.km <= 40 ? best.name : "your location";
}

export const townArea = (name: string): Area => {
  const t = TOWNS.find((x) => x.name === name)!;
  return { lat: t.lat, lng: t.lng, label: t.name, source: "town" };
};

export type LocateResult = "ok" | "denied" | "unavailable";

/** Ask the browser for the phone's position. Never throws. */
export function locate(): Promise<LocateResult> {
  return new Promise((resolve) => {
    if (!navigator.geolocation || !window.isSecureContext) return resolve("unavailable");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude: lat, longitude: lng } = pos.coords;
        setArea({ lat: +lat.toFixed(4), lng: +lng.toFixed(4), label: labelFor(lat, lng), source: "gps" });
        resolve("ok");
      },
      (err) => resolve(err.code === err.PERMISSION_DENIED ? "denied" : "unavailable"),
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 5 * 60_000 },
    );
  });
}

async function permissionState(): Promise<PermissionState | "unknown"> {
  try {
    return (await navigator.permissions.query({ name: "geolocation" })).state;
  } catch {
    return "unknown";
  }
}

/** The saved area, plus a silent first-visit setup. Returns null until one is known. */
export function useArea(): Area | null {
  const area = useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => current,
  );
  const init = useCallback(async () => {
    const granted = (await permissionState()) === "granted";
    if (current?.source === "gps" || (!current && granted)) {
      // Already allowed: refresh quietly so the list follows the customer when they move.
      if (granted) await locate();
      return;
    }
    if (!current) {
      const { lat, lng } = profile.get();
      // A previous delivery pin is a good enough start: no prompt needed.
      if (lat != null && lng != null) setArea({ lat, lng, label: labelFor(lat, lng), source: "pin" });
    }
  }, []);
  useEffect(() => {
    void init();
  }, [init]);
  return area;
}

/** Query-string for the nearby endpoints ("" when the location is not known yet). */
export const areaQuery = (a: Area | null) => (a ? `lat=${a.lat}&lng=${a.lng}` : "");
