/**
 * Dispatch map (D27): riders' live positions against the hotels they collect from and the
 * customers they deliver to. Loaded only on the Dispatch page (Leaflet is big).
 */
import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { useEffect, useRef } from "react";

export type MapOrder = {
  id: string;
  code: string;
  status: string;
  hotel_name: string;
  hotel_lat: number | null;
  hotel_lng: number | null;
  lat: number | null;
  lng: number | null;
  rider_id: string | null;
  customer_name: string;
};
export type MapRider = {
  id: string;
  name: string;
  is_online: boolean;
  active_jobs: number;
  lat: number | null;
  lng: number | null;
  accuracy_m: number | null;
  location_at: string | null;
  live: boolean;
};

const ON_ROAD = ["picked_up", "on_the_way"];

export function km(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  const r = 6371;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos((a.lat * Math.PI) / 180) * Math.cos((b.lat * Math.PI) / 180) * Math.sin(dLng / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(h));
}

function seen(iso: string | null) {
  if (!iso) return "no location yet";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  return s < 60 ? `${s} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
}

const esc = (t: string) => t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

function badge(html: string, bg: string, size = 34) {
  return L.divIcon({
    className: "",
    html: `<div style="width:${size}px;height:${size}px;border-radius:999px;background:${bg};color:#fff;display:flex;align-items:center;justify-content:center;font:700 14px Inter,system-ui;box-shadow:0 3px 10px rgba(0,0,0,.3);border:3px solid #fff">${html}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

export default function DispatchMap({ orders, riders }: { orders: MapOrder[]; riders: MapRider[] }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const fitted = useRef(false);

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current, { zoomControl: true }).setView([0.5636, 34.5606], 13);
    map.current = m;
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    return () => {
      m.remove();
      map.current = null;
      layer.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    const g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    const points: L.LatLngExpression[] = [];

    // Hotels with work in progress.
    const hotels = new Map<string, MapOrder>();
    orders.forEach((o) => o.hotel_lat != null && hotels.set(o.hotel_name, o));
    hotels.forEach((o) => {
      L.marker([o.hotel_lat!, o.hotel_lng!], { icon: badge("🏪", "#18181b", 34), zIndexOffset: 100 })
        .bindTooltip(`<b>${esc(o.hotel_name)}</b>`, { direction: "top", offset: [0, -16] })
        .addTo(g);
      points.push([o.hotel_lat!, o.hotel_lng!]);
    });

    // Customers.
    orders.forEach((o) => {
      if (o.lat == null || o.lng == null) return;
      L.marker([o.lat, o.lng], {
        icon: L.divIcon({
          className: "",
          html: `<div style="transform:translate(-50%,-100%);display:inline-block;white-space:nowrap;background:#dc4b12;color:#fff;font:700 12px Inter,system-ui;padding:3px 8px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.25)">#${esc(o.code)}</div>`,
          iconSize: [0, 0],
        }),
      })
        .bindTooltip(`<b>#${esc(o.code)}</b> · ${esc(o.customer_name)}`, { direction: "top" })
        .addTo(g);
      points.push([o.lat, o.lng]);
    });

    // Riders, and a line to where each is heading next.
    riders.forEach((r) => {
      if (r.lat == null || r.lng == null || !r.is_online) return;
      const color = !r.live ? "#a1a1aa" : r.active_jobs ? "#c2410c" : "#16a34a";
      const here = { lat: r.lat, lng: r.lng };
      const jobs = orders.filter((o) => o.rider_id === r.id);
      const next = jobs.map((o) => {
        const toCustomer = ON_ROAD.includes(o.status);
        const lat = toCustomer ? o.lat : o.hotel_lat;
        const lng = toCustomer ? o.lng : o.hotel_lng;
        return lat != null && lng != null ? { o, to: { lat, lng }, toCustomer } : null;
      });
      const lines = next
        .filter((n): n is NonNullable<typeof n> => n != null)
        .map((n) => {
          L.polyline([here, n.to], { color, weight: 3, dashArray: "6 8", opacity: 0.9 }).addTo(g);
          return `#${esc(n.o.code)}: ${km(here, n.to).toFixed(1)} km to ${n.toCustomer ? "customer" : esc(n.o.hotel_name)}`;
        });
      if (r.accuracy_m && r.accuracy_m > 30) L.circle([r.lat, r.lng], { radius: r.accuracy_m, color, weight: 1, fillOpacity: 0.08, interactive: false }).addTo(g);
      L.marker([r.lat, r.lng], { icon: badge(esc(r.name.slice(0, 1)), color, 36), zIndexOffset: 200 })
        .bindTooltip(
          `<b>${esc(r.name)}</b><br>${r.active_jobs ? `${r.active_jobs} job${r.active_jobs > 1 ? "s" : ""}` : "Free"} · seen ${seen(r.location_at)}${lines.length ? `<br>${lines.join("<br>")}` : ""}`,
          { direction: "top", offset: [0, -18] },
        )
        .addTo(g);
      points.push([r.lat, r.lng]);
    });

    if (!fitted.current && points.length) {
      m.invalidateSize(); // the box may have just been laid out
      m.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 15 });
      fitted.current = true;
    }
  }, [orders, riders]);

  return (
    <div className="relative">
      <div ref={el} className="isolate z-0 h-[26rem] w-full overflow-hidden rounded-3xl border border-line" role="application" aria-label="Map of riders, hotels and customers" />
      <div className="pointer-events-none absolute bottom-3 left-3 z-[400] flex flex-wrap gap-2 rounded-xl bg-surface/95 px-3 py-2 text-xs font-semibold shadow">
        <span className="flex items-center gap-1.5"><span className="size-3 rounded-full bg-ok" /> Free</span>
        <span className="flex items-center gap-1.5"><span className="size-3 rounded-full bg-warn" /> On a job</span>
        <span className="flex items-center gap-1.5"><span className="size-3 rounded-full bg-[#a1a1aa]" /> Not seen 5+ min</span>
        <span>🏪 Hotel</span>
        <span className="rounded bg-brand px-1 text-white">#CODE</span> <span>Customer</span>
      </div>
    </div>
  );
}
