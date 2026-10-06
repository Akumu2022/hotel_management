import "leaflet/dist/leaflet.css";

import { useQuery } from "@tanstack/react-query";
import L from "leaflet";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";
import { distanceKm } from "../lib/geo";
import { useT } from "../lib/i18n";
import type { TrackLive } from "./types";

type Ping = { lat: number; lng: number; at: string };
type Pt = [number, number];
const GLIDE_MS = 6000; // fixes arrive every 10-30 s: glide between them instead of jumping
const SPEED_KMH = 20; // a motorbike in town, for the arrival estimate

const icon = (cls: string, html: string, size: number) =>
  L.divIcon({ className: cls, html, iconSize: [size, size], iconAnchor: [size / 2, size / 2] });

const BIKE =
  '<span class="rider-pulse"></span><span class="rider-pin"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="5.5" cy="17.5" r="3.5"/><circle cx="18.5" cy="17.5" r="3.5"/><path d="M15 6h-3l-3 6.5M12 12l3.5 5.5M15 6l3 11.5M14 6h3"/></svg></span>';
const HOME = '<span class="dest-pin">🏠</span>';
const SHOP = '<span class="hotel-pin">🏪</span>';

/** The road line still to go: from the rider's position on it to the customer's pin. */
function remaining(route: Pt[] | null, rider: Pt, dest: Pt): Pt[] {
  if (!route || route.length < 2) return [rider, dest];
  let best = 0;
  let bestD = Infinity;
  route.forEach((p, i) => {
    const d = (p[0] - rider[0]) ** 2 + (p[1] - rider[1]) ** 2;
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  });
  return [rider, ...route.slice(best + 1)];
}

const lengthKm = (pts: Pt[]) => pts.slice(1).reduce((km, p, i) => km + distanceKm(pts[i][0], pts[i][1], p[0], p[1]), 0);

/**
 * The customer's live map once the food is on the road: the rider glides along, a dotted line
 * flows from them to the door and shortens as they get closer.
 */
export default function RiderMap({ token, live, ping, riderName }: { token: string; live: TrackLive; ping: Ping | null; riderName: string }) {
  const t = useT();
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const riderMarker = useRef<L.Marker | null>(null);
  const halo = useRef<L.Polyline | null>(null);
  const flow = useRef<L.Polyline | null>(null);
  const shown = useRef<Pt | null>(null); // where the marker is drawn right now
  const glide = useRef(0);
  const userMoved = useRef(false);
  const lastRouteFrom = useRef<Pt | null>(null);
  const [now, setNow] = useState(Date.now());

  // The newest fix: a pushed one, else the one the page loaded with.
  const fix = ping && new Date(ping.at) > new Date(live.at) ? ping : { lat: live.rider_lat, lng: live.rider_lng, at: live.at };
  const rider: Pt = [fix.lat, fix.lng];
  const dest: Pt = [live.dest_lat, live.dest_lng];
  const ageS = Math.max(0, Math.round((now - new Date(fix.at).getTime()) / 1000));
  const stale = ageS > 300 || !live.live;

  // Road line: fetched when we start, then only after the rider has moved a fair way (the server
  // caches too). If routing is unavailable the line is straight.
  const [routeKey, setRouteKey] = useState(0);
  const route = useQuery({
    queryKey: ["track-route", token, routeKey],
    queryFn: () => api.get<{ points: Pt[] | null }>(`/track/${token}/route`),
    staleTime: Infinity,
    refetchInterval: (q) => (q.state.data?.points ? false : 30_000), // routing busy: try again, line stays straight
  });
  useEffect(() => {
    const from = lastRouteFrom.current;
    if (!from) {
      lastRouteFrom.current = rider;
      return;
    }
    if (distanceKm(from[0], from[1], rider[0], rider[1]) > 0.3) {
      lastRouteFrom.current = rider;
      setRouteKey((k) => k + 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rider[0], rider[1]]);

  const points = route.data?.points ?? null;
  const line = useMemo(() => remaining(points, rider, dest), [points, rider[0], rider[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  const km = lengthKm(line);
  const minutes = Math.max(1, Math.round((km / SPEED_KMH) * 60));

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(id);
  }, []);

  // Build the map once.
  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current, { zoomControl: false, attributionControl: true });
    map.current = m;
    m.setView(dest, 15);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
    L.control.zoom({ position: "bottomright" }).addTo(m);
    if (live.hotel_lat != null && live.hotel_lng != null) L.marker([live.hotel_lat, live.hotel_lng], { icon: icon("map-emoji", SHOP, 32), interactive: false }).addTo(m);
    L.marker(dest, { icon: icon("map-emoji", HOME, 36), interactive: false, zIndexOffset: 500 }).addTo(m);
    halo.current = L.polyline([rider, dest], { color: "#ffffff", weight: 9, opacity: 0.9, lineCap: "round", interactive: false }).addTo(m);
    flow.current = L.polyline([rider, dest], { color: "#dc4b12", weight: 5, opacity: 1, lineCap: "round", dashArray: "1 11", className: "route-flow", interactive: false }).addTo(m);
    shown.current = rider;
    riderMarker.current = L.marker(rider, { icon: icon("map-rider", BIKE, 44), zIndexOffset: 1000, interactive: false }).addTo(m);
    m.fitBounds(L.latLngBounds([rider, dest]), { padding: [48, 48], maxZoom: 17 });
    m.on("dragstart", () => {
      userMoved.current = true; // the customer is looking around: stop re-framing the map
    });
    return () => {
      cancelAnimationFrame(glide.current);
      m.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Glide the rider to each new fix, and redraw the dotted line as they go.
  useEffect(() => {
    const m = riderMarker.current;
    if (!m || !shown.current) return;
    const from = shown.current;
    const start = performance.now();
    cancelAnimationFrame(glide.current);
    const step = (ts: number) => {
      const k = Math.min(1, (ts - start) / GLIDE_MS);
      const p: Pt = [from[0] + (rider[0] - from[0]) * k, from[1] + (rider[1] - from[1]) * k];
      shown.current = p;
      m.setLatLng(p);
      const pts = remaining(points, p, dest);
      halo.current?.setLatLngs(pts);
      flow.current?.setLatLngs(pts);
      if (k < 1) glide.current = requestAnimationFrame(step);
    };
    glide.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(glide.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rider[0], rider[1], points]);

  // Keep both ends in view unless the customer has moved the map themselves.
  useEffect(() => {
    if (userMoved.current || !map.current) return;
    map.current.fitBounds(L.latLngBounds([rider, dest]), { padding: [48, 48], maxZoom: 17, animate: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Math.round(rider[0] * 2000), Math.round(rider[1] * 2000)]);

  const near = km < 0.15;
  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-surface">
      <div className="flex items-center justify-between gap-3 px-5 py-4">
        <div className="min-w-0">
          <p className="text-[0.9375rem] font-semibold">
            {stale ? t("{name}'s location is paused", { name: riderName }) : near ? t("{name} is almost there", { name: riderName }) : t("{name} is on the way", { name: riderName })}
          </p>
          <p className="text-sm text-muted">
            {stale
              ? t("Last seen {min} min ago", { min: Math.max(1, Math.round(ageS / 60)) })
              : near
                ? t("Get ready with your code")
                : t("{km} km away · about {min} min", { km: km.toFixed(1), min: minutes })}
          </p>
        </div>
        <span className={stale ? "rounded-full bg-subtle px-2.5 py-1 text-xs font-semibold text-muted" : "flex items-center gap-1.5 rounded-full bg-ok-soft px-2.5 py-1 text-xs font-semibold text-ok"}>
          {stale ? null : <span className="size-2 animate-pulse rounded-full bg-ok" />}
          {stale ? t("Paused") : ageS < 15 ? t("Live") : t("Updated {s}s ago", { s: ageS })}
        </span>
      </div>
      <div ref={el} className="h-72 w-full sm:h-80" role="img" aria-label={t("Live map of your rider")} />
    </section>
  );
}
