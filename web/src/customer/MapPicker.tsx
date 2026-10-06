import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { AlertTriangle, CheckCircle2, LocateFixed, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { type LngLat, pointInZone } from "../lib/geo";
import { useT } from "../lib/i18n";

type Point = { lat: number; lng: number };

// Hotels can only be pinned within 20 km of Bungoma town CBD.
const CBD = L.latLng(0.5636, 34.5606);
const CBD_RADIUS_M = 20_000;
const withinCbd = (p: Point) => CBD.distanceTo(L.latLng(p.lat, p.lng)) <= CBD_RADIUS_M;

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
  precise = false,
}: {
  zone?: LngLat[];
  value: Point | null;
  onChange: (p: Point) => void;
  hotel?: { lat: number; lng: number; name: string } | null;
  height?: string;
  checkZone?: boolean;
  rangeKm?: number; // no drawn area: show how far riders go from the hotel
  precise?: boolean; // hotel admins: place search + satellite layer for an exact pin
}) {
  const t = useT();
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const accuracy = useRef<L.Circle | null>(null);
  const [accuracyM, setAccuracyM] = useState<number | null>(null);
  const [locating, setLocating] = useState(false);
  const [gpsError, setGpsError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);

  const hasZone = checkZone && zone.length >= 3;
  const inside = value && hasZone ? pointInZone(value.lat, value.lng, zone) : null;

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current, { zoomControl: true, attributionControl: true });
    map.current = m;
    // Give the map a view first: layers added to a map with no view aren't attached yet.
    m.setView(value ? [value.lat, value.lng] : hotel ? [hotel.lat, hotel.lng] : [0.5636, 34.5606], value ? 15 : hotel ? 14 : 12);
    const street = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
    if (precise) {
      const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Imagery © Esri" });
      m.setMaxBounds(CBD.toBounds(CBD_RADIUS_M * 2.4));
      m.setMinZoom(10);
      L.circle(CBD, { radius: CBD_RADIUS_M, color: "#dc4b12", weight: 2.5, dashArray: "6 6", fillOpacity: 0.03, interactive: false }).addTo(m);
      if (!value) m.setView(CBD, 13);
      L.control.layers({ Map: street, Satellite: sat }, undefined, { position: "topright" }).addTo(m);
    }
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
    m.on("click", (e: L.LeafletMouseEvent) => {
      const p = { lat: e.latlng.lat, lng: e.latlng.lng };
      if (precise && !withinCbd(p)) return setGpsError("That's more than 20 km from Bungoma town. Pin a spot inside the dashed circle.");
      setGpsError(null);
      accuracy.current?.remove();
      accuracy.current = null;
      setAccuracyM(null);
      onChange(p);
    });
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

  async function find(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setGpsError(null);
    try {
      const box = CBD.toBounds(CBD_RADIUS_M * 2);
      const vb = [box.getWest(), box.getNorth(), box.getEast(), box.getSouth()].join(",");
      const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=ke&viewbox=${vb}&bounded=1&q=${encodeURIComponent(`${q}, Bungoma`)}`);
      const hits = (await r.json()) as { lat: string; lon: string }[];
      if (!hits.length) setGpsError("Couldn't find that within 20 km of Bungoma town. Try a nearby landmark, then tap the map.");
      else {
        const ll = { lat: Number(hits[0].lat), lng: Number(hits[0].lon) };
        if (withinCbd(ll)) map.current?.setView([ll.lat, ll.lng], 18);
        else setGpsError("That result is outside the 20 km Bungoma area.");
      }
    } catch {
      setGpsError("Search isn't available right now. Pan the map instead.");
    }
    setSearching(false);
  }

  function locate() {
    if (!navigator.geolocation || !window.isSecureContext)
      return setGpsError(
        window.isSecureContext
          ? "Location isn't available on this device. Tap the map instead."
          : "Your browser blocks GPS on this connection (it needs https). Tap the map instead.",
      );
    setLocating(true);
    setGpsError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        const p = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        if (precise && !withinCbd(p)) return setGpsError("You're more than 20 km from Bungoma town. Search or tap the map inside the dashed circle.");
        onChange(p);
        const m = map.current;
        if (!m) return;
        m.setView([p.lat, p.lng], pos.coords.accuracy > 100 ? 16 : 18);
        // Show how sure the phone is, so they can check the pin and tap the map to correct it.
        accuracy.current?.remove();
        accuracy.current = L.circle([p.lat, p.lng], { radius: pos.coords.accuracy, color: "#2563eb", weight: 1, fillOpacity: 0.12, interactive: false }).addTo(m);
        setAccuracyM(Math.round(pos.coords.accuracy));
      },
      (err) => {
        setLocating(false);
        setGpsError(
          err.code === err.PERMISSION_DENIED
            ? "Location is turned off for this site. Allow it in your browser settings, or tap the map instead."
            : err.code === err.TIMEOUT
              ? "Couldn't get a GPS fix in time. Move near a window and try again, or tap the map."
              : "Couldn't get your location. Tap the map instead.",
        );
      },
      { enableHighAccuracy: true, timeout: 20_000, maximumAge: 0 },
    );
  }

  return (
    <div className="flex flex-col gap-2.5">
      {precise ? (
        <form onSubmit={find} className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search a place in Bungoma town"
            aria-label="Search for a place"
            className="h-10 min-w-0 flex-1 rounded-xl border border-line bg-surface px-3.5 text-sm"
          />
          <button type="submit" disabled={searching} className="flex h-10 shrink-0 items-center gap-2 rounded-xl border border-line bg-surface px-3.5 text-sm font-semibold hover:bg-subtle disabled:opacity-60">
            <Search className="size-4" /> Search
          </button>
        </form>
      ) : null}
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
          {accuracyM != null ? ` (GPS ±${accuracyM} m)` : ""}
        </p>
      ) : null}
      {gpsError ? <p className="text-sm text-bad">{gpsError}</p> : null}
    </div>
  );
}
