import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { AlertTriangle, CheckCircle2, LocateFixed } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { type LngLat, pointInZone } from "../lib/geo";
import { useT } from "../lib/i18n";

type Point = { lat: number; lng: number };

/**
 * Tap the map (or use GPS) to drop a pin. When a delivery zone is given, everything outside it
 * is shaded and a pin outside turns red with a clear message, before the customer submits.
 */
export default function MapPicker({
  zone = [],
  value,
  onChange,
  hotel,
  height = "h-64",
  checkZone = true,
  rangeKm,
}: {
  zone?: LngLat[];
  value: Point | null;
  onChange: (p: Point) => void;
  hotel?: { lat: number; lng: number; name: string } | null;
  height?: string;
  checkZone?: boolean;
  rangeKm?: number; // no drawn area: show how far riders go from the hotel
}) {
  const t = useT();
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const [locating, setLocating] = useState(false);
  const [gpsError, setGpsError] = useState<string | null>(null);

  const hasZone = checkZone && zone.length >= 3;
  const inside = value && hasZone ? pointInZone(value.lat, value.lng, zone) : null;

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current, { zoomControl: true, attributionControl: true });
    map.current = m;
    // Give the map a view first: layers added to a map with no view aren't attached yet.
    m.setView(value ? [value.lat, value.lng] : hotel ? [hotel.lat, hotel.lng] : [0.5636, 34.5606], value ? 15 : hotel ? 14 : 12);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
    const ring = zone.map(([lng, lat]) => L.latLng(lat, lng));
    if (hasZone) {
      // Grey everything outside the delivery area so it stands out.
      const world = [L.latLng(-89, -179), L.latLng(-89, 179), L.latLng(89, 179), L.latLng(89, -179)];
      L.polygon([world, ring], { stroke: false, fillColor: "#18181b", fillOpacity: 0.28, interactive: false }).addTo(m);
      const poly = L.polygon(ring, { color: "#dc4b12", weight: 2.5, fill: false, dashArray: "6 6", interactive: false }).addTo(m);
      m.fitBounds(poly.getBounds(), { padding: [16, 16] });
      if (value) m.setView([value.lat, value.lng], 15);
    } else if (hotel && rangeKm) {
      L.circle([hotel.lat, hotel.lng], { radius: rangeKm * 1000, color: "#dc4b12", weight: 2.5, dashArray: "6 6", fillOpacity: 0.04, interactive: false }).addTo(m);
      // Bounds from the coordinates (circle.getBounds() needs the layer attached to the map).
      m.fitBounds(L.latLng(hotel.lat, hotel.lng).toBounds(rangeKm * 2000), { padding: [12, 12] });
      if (value) m.setView([value.lat, value.lng], 15);
    }
    if (hotel) {
      L.marker([hotel.lat, hotel.lng], {
        icon: L.divIcon({
          className: "",
          html: '<div style="width:34px;height:34px;border-radius:12px;background:#18181b;color:#fff;display:flex;align-items:center;justify-content:center;font-size:18px;box-shadow:0 4px 12px rgba(0,0,0,.3);border:2px solid #fff">🏪</div>',
          iconSize: [34, 34],
          iconAnchor: [17, 17],
        }),
        interactive: false,
      })
        .bindTooltip(hotel.name, { direction: "top", offset: [0, -16] })
        .addTo(m);
    }
    m.on("click", (e: L.LeafletMouseEvent) => onChange({ lat: e.latlng.lat, lng: e.latlng.lng }));
    return () => {
      m.remove();
      map.current = null;
      marker.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !value) return;
    const ll = L.latLng(value.lat, value.lng);
    const color = inside === false ? "#dc2626" : "#dc4b12";
    if (marker.current) marker.current.setLatLng(ll).setStyle({ fillColor: color });
    else marker.current = L.circleMarker(ll, { radius: 11, color: "#fff", weight: 3, fillColor: color, fillOpacity: 1 }).addTo(m);
  }, [value, inside]);

  function locate() {
    if (!navigator.geolocation) return setGpsError("Location isn't available here. Tap the map instead.");
    setLocating(true);
    setGpsError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        const p = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        onChange(p);
        map.current?.setView([p.lat, p.lng], 16);
      },
      () => {
        setLocating(false);
        setGpsError("Couldn't get your location. Tap the map instead.");
      },
      { enableHighAccuracy: true, timeout: 15_000 },
    );
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div ref={el} className={`isolate z-0 w-full overflow-hidden rounded-2xl border border-line ${height}`} role="application" aria-label="Map: tap to set the location" />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={locate}
          disabled={locating}
          className="flex h-10 shrink-0 items-center gap-2 rounded-xl border border-line bg-surface px-3.5 text-sm font-semibold whitespace-nowrap hover:bg-subtle disabled:opacity-60"
        >
          {locating ? <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> : <LocateFixed className="size-4" />}
          {t("Use my location")}
        </button>
        {!value ? <span className="text-sm text-muted">{t("or tap the map")}</span> : null}
      </div>
      {value && inside === false ? (
        <p className="flex items-start gap-2 rounded-xl bg-bad-soft px-3.5 py-2.5 text-sm font-medium text-bad">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          {t("That spot is outside our delivery area. Move the pin inside the dashed line, or choose pickup.")}
        </p>
      ) : value && (inside === true || !hasZone) ? (
        <p className="flex items-center gap-2 text-sm font-medium text-ok">
          <CheckCircle2 className="size-4" /> {t("Pin set. Tap the map to move it.")}
        </p>
      ) : null}
      {gpsError ? <p className="text-sm text-bad">{gpsError}</p> : null}
    </div>
  );
}
