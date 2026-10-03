/**
 * Super admin: where we deliver, what delivery costs, and where each hotel is (fees are measured
 * from the hotel). DECISIONS D14.
 */
import "leaflet/dist/leaflet.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import L from "leaflet";
import { CheckCircle2, Circle, MapPin, Plus, Spline, Trash2, Undo2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { type LngLat, circleZone } from "../lib/geo";

type Band = { max_km: number; fee: number };
type Pricing = {
  rider_fee_mode: "bands" | "per_km";
  rider_fee_base: number;
  rider_fee_per_km: number;
  rider_fee_min: number;
  rider_fee_max_km: number;
  distance_method: "road" | "straight";
};
type AdminSettings = Pricing & { delivery_zone: LngLat[]; rider_fee_bands: Band[]; support_whatsapp: string; platform_mpesa_number: string };
type CalcResult = { distance_km: number; method: string; straight_km: number; rider_fee: number | null; too_far: boolean; max_delivery_km: number };

/** Same formula as the server (services/settings.rider_fee_at), for the live preview only. */
function previewFee(p: Pricing, bands: Band[], km: number): number | null {
  if (p.rider_fee_mode === "bands") {
    const b = bands.find((x) => km <= x.max_km);
    return b ? b.fee : null;
  }
  if (km > p.rider_fee_max_km) return null;
  return Math.max(p.rider_fee_min, Math.ceil((p.rider_fee_base + p.rider_fee_per_km * km) / 10) * 10);
}
type AdminHotel = { id: string; name: string; lat: number | null; lng: number | null };
type Page<T> = { items: T[]; next_cursor: string | null };
type Mode = "circle" | "outline" | { hotel: AdminHotel } | { calc: AdminHotel };

const hotelIcon = (placed: boolean) =>
  L.divIcon({
    className: "",
    html: `<div style="width:32px;height:32px;border-radius:11px;background:${placed ? "#18181b" : "#a1a1aa"};display:flex;align-items:center;justify-content:center;font-size:17px;border:2px solid #fff;box-shadow:0 4px 12px rgba(0,0,0,.3)">🏪</div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });

function Card({ title, subtitle, children, action }: { title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-3xl border border-line bg-surface">
      <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h2 className="text-[1rem] font-bold">{title}</h2>
          {subtitle ? <p className="text-sm text-muted">{subtitle}</p> : null}
        </div>
        {action}
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}

/** Where hotels send what they owe (M7). */
function PlatformNumberCard({ current }: { current: string }) {
  const qc = useQueryClient();
  const [value, setValue] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (v: string) => api.put("/admin/settings", { platform_mpesa_number: v }),
    onSuccess: () => {
      setValue(null);
      return qc.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
  });
  const v = value ?? (current ? "0" + current.slice(3) : "");
  return (
    <Card title="Your M-Pesa number for hotel payments" subtitle="Hotels send their weekly commission and fees here (M-Pesa Send Money).">
      <div className="flex gap-2">
        <input
          aria-label="Platform M-Pesa number"
          inputMode="tel"
          placeholder="0742 554 713"
          value={v}
          onChange={(e) => setValue(e.target.value)}
          className="h-11 flex-1 rounded-xl border border-line px-3.5 text-sm outline-none focus:border-brand"
        />
        <button
          onClick={() => save.mutate(v)}
          disabled={value === null || !v.trim() || save.isPending}
          className="h-11 shrink-0 rounded-xl bg-brand px-4 text-sm font-semibold text-white disabled:opacity-40"
        >
          Save
        </button>
      </div>
      <ErrorNote error={save.error} />
    </Card>
  );
}

function SupportCard({ current }: { current: string }) {
  const qc = useQueryClient();
  const [value, setValue] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (v: string) => api.put("/admin/settings", { support_whatsapp: v }),
    onSuccess: () => {
      setValue(null);
      return qc.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
  });
  const v = value ?? (current ? "0" + current.slice(3) : "");
  return (
    <Card title="Customer support" subtitle="Customers see a WhatsApp help button with this number.">
      <div className="flex gap-2">
        <input
          aria-label="Support WhatsApp number"
          inputMode="tel"
          placeholder="0712 345 678"
          value={v}
          onChange={(e) => setValue(e.target.value)}
          className="h-11 flex-1 rounded-xl border border-line px-3.5 text-sm outline-none focus:border-brand"
        />
        <button
          onClick={() => save.mutate(v)}
          disabled={value === null || save.isPending}
          className="h-11 shrink-0 rounded-xl bg-brand px-4 text-sm font-semibold text-white disabled:opacity-40"
        >
          Save
        </button>
      </div>
      <p className="mt-2 text-xs text-muted">{current ? "Live: customers can message you." : "Not set: the help button is hidden."} Leave empty to hide it.</p>
      <ErrorNote error={save.error} />
    </Card>
  );
}

export function DeliveryPage() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: () => api.get<AdminSettings>("/admin/settings") });
  const hotels = useQuery({ queryKey: ["admin", "hotels"], queryFn: () => api.get<Page<AdminHotel>>("/admin/hotels?limit=100") });

  const [mode, setMode] = useState<Mode>("circle");
  const [centre, setCentre] = useState<{ lat: number; lng: number } | null>(null);
  const [radius, setRadius] = useState(5);
  const [outline, setOutline] = useState<LngLat[]>([]);
  const [draft, setDraft] = useState<LngLat[] | null>(null); // unsaved zone
  const [bands, setBands] = useState<Band[] | null>(null);

  const saved = settings.data?.delivery_zone ?? [];
  const zone = draft ?? saved;
  const editBands = bands ?? settings.data?.rider_fee_bands ?? [];

  // Circle mode: the draft follows centre + radius.
  useEffect(() => {
    if (mode === "circle" && centre) setDraft(circleZone(centre.lat, centre.lng, radius));
  }, [mode, centre, radius]);
  useEffect(() => {
    if (mode === "outline") setDraft(outline.length ? outline : null);
  }, [mode, outline]);

  const saveZone = useMutation({
    mutationFn: (z: LngLat[]) => api.put("/admin/settings", { delivery_zone: z }),
    onSuccess: () => {
      setDraft(null);
      setCentre(null);
      setOutline([]);
      return qc.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
  });
  const saveBands = useMutation({
    mutationFn: (b: Band[]) => api.put("/admin/settings", { rider_fee_bands: b }),
    onSuccess: () => {
      setBands(null);
      return qc.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
  });
  const placeHotel = useMutation({
    mutationFn: ({ id, lat, lng }: { id: string; lat: number; lng: number }) => api.patch(`/admin/hotels/${id}`, { lat, lng }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "hotels"] }),
  });

  // Pricing draft (per-km / bands / distance method)
  const [pricing, setPricing] = useState<Pricing | null>(null);
  const savedPricing: Pricing | null = settings.data
    ? {
        rider_fee_mode: settings.data.rider_fee_mode,
        rider_fee_base: settings.data.rider_fee_base,
        rider_fee_per_km: settings.data.rider_fee_per_km,
        rider_fee_min: settings.data.rider_fee_min,
        rider_fee_max_km: settings.data.rider_fee_max_km,
        distance_method: settings.data.distance_method,
      }
    : null;
  const editPricing = pricing ?? savedPricing;
  const savePricing = useMutation({
    mutationFn: (p: Pricing) => api.put("/admin/settings", p),
    onSuccess: () => {
      setPricing(null);
      return qc.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
  });

  // Distance calculator: the exact distance and fee a customer at a tapped spot would get.
  const [calc, setCalc] = useState<{ hotel: AdminHotel; point: { lat: number; lng: number }; result?: CalcResult; error?: unknown } | null>(null);
  const calcLayer = useRef<L.LayerGroup | null>(null);
  async function runCalc(hotel: AdminHotel, point: { lat: number; lng: number }) {
    setCalc({ hotel, point });
    try {
      const result = await api.get<CalcResult>(`/admin/distance?hotel_id=${hotel.id}&lat=${point.lat}&lng=${point.lng}`);
      setCalc({ hotel, point, result });
    } catch (error) {
      setCalc({ hotel, point, error });
    }
  }

  // --- Map ----------------------------------------------------------------------------------
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const zoneLayer = useRef<L.LayerGroup | null>(null);
  const hotelLayer = useRef<L.LayerGroup | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current).setView([0.5636, 34.5606], 12);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
    zoneLayer.current = L.layerGroup().addTo(m);
    hotelLayer.current = L.layerGroup().addTo(m);
    calcLayer.current = L.layerGroup().addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => {
      const md = modeRef.current;
      const p = { lat: e.latlng.lat, lng: e.latlng.lng };
      if (md === "circle") setCentre(p);
      else if (md === "outline") setOutline((o) => [...o, [+p.lng.toFixed(6), +p.lat.toFixed(6)]]);
      else if ("calc" in md) runCalc(md.calc, p);
      else {
        placeHotel.mutate({ id: md.hotel.id, lat: +p.lat.toFixed(6), lng: +p.lng.toFixed(6) });
        setMode("circle");
      }
    });
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.isLoading]);

  // Fit to the saved zone once loaded.
  const fitted = useRef(false);
  useEffect(() => {
    if (!map.current || fitted.current || !settings.data) return;
    fitted.current = true;
    if (saved.length >= 3) map.current.fitBounds(L.latLngBounds(saved.map(([lng, lat]) => [lat, lng])), { padding: [24, 24] });
  }, [settings.data, saved]);

  useEffect(() => {
    const g = zoneLayer.current;
    if (!g) return;
    g.clearLayers();
    if (zone.length >= 2) {
      const ring = zone.map(([lng, lat]) => L.latLng(lat, lng));
      const style = draft ? { color: "#dc4b12", dashArray: "6 6", fillOpacity: 0.12 } : { color: "#16a34a", fillOpacity: 0.1 };
      (zone.length >= 3 ? L.polygon(ring, { weight: 2.5, ...style }) : L.polyline(ring, { weight: 2.5, color: "#dc4b12" })).addTo(g);
    }
    if (mode === "outline") outline.forEach(([lng, lat]) => L.circleMarker([lat, lng], { radius: 5, color: "#fff", weight: 2, fillColor: "#dc4b12", fillOpacity: 1 }).addTo(g));
    if (mode === "circle" && centre) L.circleMarker([centre.lat, centre.lng], { radius: 7, color: "#fff", weight: 3, fillColor: "#dc4b12", fillOpacity: 1 }).addTo(g);
  }, [zone, draft, mode, outline, centre]);

  useEffect(() => {
    const g = hotelLayer.current;
    if (!g) return;
    g.clearLayers();
    hotels.data?.items.filter((h) => h.lat != null).forEach((h) => L.marker([h.lat!, h.lng!], { icon: hotelIcon(true) }).bindTooltip(h.name, { direction: "top", offset: [0, -14] }).addTo(g));
  }, [hotels.data]);

  useEffect(() => {
    const g = calcLayer.current;
    if (!g) return;
    g.clearLayers();
    if (!calc || calc.hotel.lat == null) return;
    const a = L.latLng(calc.hotel.lat, calc.hotel.lng!);
    const b = L.latLng(calc.point.lat, calc.point.lng);
    L.polyline([a, b], { color: "#2563eb", weight: 3, dashArray: "4 6" }).addTo(g);
    L.circleMarker(b, { radius: 9, color: "#fff", weight: 3, fillColor: "#2563eb", fillOpacity: 1 }).addTo(g);
  }, [calc]);

  const bandsValid = useMemo(
    () => editBands.length > 0 && editBands.every((b, i) => b.max_km > 0 && b.fee >= 0 && (i === 0 || b.max_km > editBands[i - 1].max_km)),
    [editBands],
  );

  if (settings.isLoading) return <div className="p-6"><Skeleton className="h-96 rounded-3xl" /></div>;
  if (settings.error) return <div className="p-6"><ErrorNote error={settings.error} /></div>;

  const placing = typeof mode === "object" && "hotel" in mode ? mode.hotel : null;
  const unplaced = hotels.data?.items.filter((h) => h.lat == null) ?? [];

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold">Delivery & fees</h1>
        <p className="text-sm text-muted">Where riders deliver, and what delivery costs by distance from the hotel.</p>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
        <Card
          title="Delivery area"
          subtitle={saved.length >= 3 ? "Customers can only drop a delivery pin inside the green area." : `No map area: each hotel delivers up to ${settings.data?.rider_fee_mode === "bands" ? settings.data?.rider_fee_bands.at(-1)?.max_km : settings.data?.rider_fee_max_km} km from its location.`}
          action={
            saved.length >= 3 && !draft ? (
              <span className="flex items-center gap-1.5 rounded-full bg-ok-soft px-2.5 py-1 text-xs font-semibold text-ok"><CheckCircle2 className="size-3.5" /> Active</span>
            ) : null
          }
        >
          {/* Mode switch */}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="flex rounded-xl bg-subtle p-1 text-sm font-semibold">
              {[
                { v: "circle" as const, label: "Circle", icon: Circle },
                { v: "outline" as const, label: "Draw outline", icon: Spline },
              ].map(({ v, label, icon: Icon }) => (
                <button
                  key={v}
                  onClick={() => {
                    setMode(v);
                    setDraft(null);
                    setCentre(null);
                    setOutline([]);
                  }}
                  className={clsx("flex h-9 items-center gap-1.5 rounded-lg px-3", mode === v ? "bg-surface shadow-sm" : "text-muted")}
                >
                  <Icon className="size-4" /> {label}
                </button>
              ))}
            </div>
            {mode === "outline" ? (
              <>
                <button onClick={() => setOutline((o) => o.slice(0, -1))} disabled={!outline.length} className="flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-medium disabled:opacity-40"><Undo2 className="size-4" /> Undo</button>
                <button onClick={() => setOutline([])} disabled={!outline.length} className="flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-medium disabled:opacity-40">Clear</button>
              </>
            ) : null}
          </div>

          <p className={clsx("mb-3 rounded-xl px-3.5 py-2.5 text-sm font-medium", typeof mode === "object" && "calc" in mode ? "bg-blue-500/10 text-blue-600" : placing ? "bg-ink text-white" : "bg-brand-soft text-brand")}>
            {typeof mode === "object" && "calc" in mode
              ? `Calculator: tap any spot to see its distance and fee from ${mode.calc.name}.`
              : placing
              ? `Tap the map where ${placing.name} is.`
              : mode === "circle"
                ? centre
                  ? "Drag the slider to set how far riders go, then save."
                  : "Tap the map at the centre of your delivery area."
                : outline.length < 3
                  ? `Tap the map to outline the area (${outline.length} of at least 3 points).`
                  : "Keep tapping to refine, then save."}
          </p>

          <div ref={el} className="isolate z-0 h-[26.25rem] w-full overflow-hidden rounded-2xl border border-line" role="application" aria-label="Delivery area map" />

          {mode === "circle" && centre ? (
            <div className="mt-4 flex items-center gap-4">
              <label htmlFor="radius" className="text-sm font-semibold whitespace-nowrap">Radius</label>
              <input id="radius" type="range" min={0.5} max={50} step={0.5} value={radius} onChange={(e) => setRadius(+e.target.value)} className="flex-1 accent-[#dc4b12]" />
              <span className="money w-16 text-right text-sm font-bold">{radius} km</span>
            </div>
          ) : null}

          <div className="mt-4 flex flex-wrap justify-end gap-2">
            {saved.length >= 3 && !draft ? (
              <button onClick={() => saveZone.mutate([])} className="flex h-11 items-center gap-2 rounded-xl border border-line px-4 text-sm font-semibold text-muted hover:text-bad">
                <Trash2 className="size-4" /> Use distance from hotel instead
              </button>
            ) : null}
            {draft ? (
              <>
                <button onClick={() => { setDraft(null); setCentre(null); setOutline([]); }} className="h-11 rounded-xl border border-line px-4 text-sm font-semibold">Discard</button>
                <button
                  onClick={() => saveZone.mutate(draft)}
                  disabled={draft.length < 3 || saveZone.isPending}
                  className="h-11 rounded-xl bg-brand px-5 text-sm font-semibold text-white shadow-lg shadow-brand/25 disabled:opacity-40"
                >
                  {saveZone.isPending ? "Saving…" : "Save delivery area"}
                </button>
              </>
            ) : null}
          </div>
          <ErrorNote error={saveZone.error} />
        </Card>

        <div className="flex flex-col gap-5">
          <Card title="Delivery fees" subtitle="Worked out automatically from the distance between the hotel and the customer's pin.">
            {editPricing ? (
              <div className="mb-5 flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-1 rounded-xl bg-subtle p-1 text-sm font-semibold">
                  {(
                    [
                      ["per_km", "Per km"],
                      ["bands", "Distance bands"],
                    ] as const
                  ).map(([v, label]) => (
                    <button
                      key={v}
                      onClick={() => setPricing({ ...editPricing, rider_fee_mode: v })}
                      className={clsx("h-10 rounded-lg", editPricing.rider_fee_mode === v ? "bg-surface shadow-sm" : "text-muted")}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {editPricing.rider_fee_mode === "per_km" ? (
                  <div className="grid grid-cols-2 gap-3">
                    {(
                      [
                        ["rider_fee_base", "Base fee", "KES"],
                        ["rider_fee_per_km", "Per km", "KES"],
                        ["rider_fee_min", "Minimum", "KES"],
                        ["rider_fee_max_km", "Furthest", "km"],
                      ] as const
                    ).map(([k, label, unit]) => (
                      <label key={k} className="flex flex-col gap-1">
                        <span className="text-xs font-medium text-muted">{label}</span>
                        <span className="relative">
                          <input
                            inputMode={unit === "km" ? "decimal" : "numeric"}
                            value={editPricing[k]}
                            onChange={(e) => {
                              const v = unit === "km" ? Number(e.target.value.replace(/[^\d.]/g, "")) || 0 : Number(e.target.value.replace(/\D/g, "")) || 0;
                              setPricing({ ...editPricing, [k]: v });
                            }}
                            className="money h-11 w-full rounded-xl border border-line bg-surface pr-11 pl-3 text-sm outline-none focus:border-brand"
                          />
                          <span className="absolute top-1/2 right-3 -translate-y-1/2 text-xs text-muted">{unit}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                ) : null}

                <label className="flex items-center justify-between gap-3 text-sm">
                  <span className="font-medium">Measure distance</span>
                  <select
                    value={editPricing.distance_method}
                    onChange={(e) => setPricing({ ...editPricing, distance_method: e.target.value as Pricing["distance_method"] })}
                    className="h-10 rounded-xl border border-line bg-surface px-3 text-sm font-medium"
                  >
                    <option value="road">By road (recommended)</option>
                    <option value="straight">Straight line</option>
                  </select>
                </label>

                {/* Live preview: what customers pay at common distances */}
                <div className="overflow-hidden rounded-xl border border-line">
                  <div className="grid grid-cols-6 bg-subtle text-center text-xs font-semibold text-muted">
                    {[1, 2, 3, 5, 8, 12].map((km) => (
                      <span key={km} className="py-1.5">{km} km</span>
                    ))}
                  </div>
                  <div className="grid grid-cols-6 text-center text-sm font-bold">
                    {[1, 2, 3, 5, 8, 12].map((km) => {
                      const f = previewFee(editPricing, editBands, km);
                      return (
                        <span key={km} className={clsx("money py-2", f == null && "text-muted")}>{f == null ? "—" : f}</span>
                      );
                    })}
                  </div>
                </div>
                <p className="-mt-2 text-xs text-muted">KES the customer pays the rider at each distance. “—” means too far: pickup only.</p>

                {pricing ? (
                  <div className="flex justify-end gap-2">
                    <button onClick={() => setPricing(null)} className="h-11 rounded-xl border border-line px-4 text-sm font-semibold">Discard</button>
                    <button
                      onClick={() => savePricing.mutate(pricing)}
                      disabled={savePricing.isPending || pricing.rider_fee_max_km <= 0}
                      className="h-11 rounded-xl bg-brand px-5 text-sm font-semibold text-white disabled:opacity-40"
                    >
                      {savePricing.isPending ? "Saving…" : "Save pricing"}
                    </button>
                  </div>
                ) : null}
                <ErrorNote error={savePricing.error} />
              </div>
            ) : null}

            {editPricing?.rider_fee_mode === "bands" ? (
            <>
            <ul className="flex flex-col gap-2.5">
              {editBands.map((b, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span className="w-16 text-sm text-muted">{i === 0 ? "Up to" : "Up to"}</span>
                  <div className="relative">
                    <input
                      aria-label="Distance in km"
                      inputMode="decimal"
                      value={b.max_km}
                      onChange={(e) => setBands(editBands.map((x, j) => (j === i ? { ...x, max_km: Number(e.target.value.replace(/[^\d.]/g, "")) || 0 } : x)))}
                      className="h-11 w-24 rounded-xl border border-line pr-9 pl-3 text-sm outline-none focus:border-brand"
                    />
                    <span className="absolute top-1/2 right-3 -translate-y-1/2 text-xs text-muted">km</span>
                  </div>
                  <span className="text-muted">→</span>
                  <div className="relative flex-1">
                    <span className="absolute top-1/2 left-3 -translate-y-1/2 text-xs text-muted">KES</span>
                    <input
                      aria-label="Fee in KES"
                      inputMode="numeric"
                      value={b.fee}
                      onChange={(e) => setBands(editBands.map((x, j) => (j === i ? { ...x, fee: Number(e.target.value.replace(/\D/g, "")) || 0 } : x)))}
                      className="money h-11 w-full rounded-xl border border-line pr-3 pl-11 text-sm outline-none focus:border-brand"
                    />
                  </div>
                  <button
                    onClick={() => setBands(editBands.filter((_, j) => j !== i))}
                    disabled={editBands.length === 1}
                    aria-label="Remove band"
                    className="flex size-9 items-center justify-center rounded-lg text-muted hover:bg-bad-soft hover:text-bad disabled:opacity-30"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
            <button
              onClick={() => {
                const last = editBands[editBands.length - 1];
                setBands([...editBands, { max_km: (last?.max_km ?? 0) + 3, fee: (last?.fee ?? 100) + 50 }]);
              }}
              disabled={editBands.length >= 8}
              className="mt-3 flex h-10 items-center gap-1.5 rounded-xl px-2 text-sm font-semibold text-brand disabled:opacity-40"
            >
              <Plus className="size-4" /> Add distance band
            </button>
            <p className="mt-2 text-xs text-muted">
              Beyond {editBands.at(-1)?.max_km ?? "?"} km, delivery isn't offered. Example: a pin 3 km away pays{" "}
              {money(editBands.find((b) => 3 <= b.max_km)?.fee ?? 0)}.
            </p>
            {!bandsValid ? <p className="mt-2 text-sm text-bad">Each distance must be bigger than the one above it.</p> : null}
            {bands ? (
              <div className="mt-4 flex justify-end gap-2">
                <button onClick={() => setBands(null)} className="h-11 rounded-xl border border-line px-4 text-sm font-semibold">Discard</button>
                <button onClick={() => saveBands.mutate(editBands)} disabled={!bandsValid || saveBands.isPending} className="h-11 rounded-xl bg-brand px-5 text-sm font-semibold text-white disabled:opacity-40">
                  {saveBands.isPending ? "Saving…" : "Save fees"}
                </button>
              </div>
            ) : null}
            <ErrorNote error={saveBands.error} />
            </>
            ) : null}
          </Card>

          <Card title="Distance calculator" subtitle="Check the distance and fee for any spot, exactly as a customer would get it.">
            <div className="flex flex-col gap-3">
              <select
                aria-label="Hotel"
                value={typeof mode === "object" && "calc" in mode ? mode.calc.id : ""}
                onChange={(e) => {
                  const h = hotels.data?.items.find((x) => x.id === e.target.value);
                  setCalc(null);
                  setMode(h ? { calc: h } : "circle");
                }}
                className="h-11 rounded-xl border border-line bg-surface px-3 text-sm font-medium"
              >
                <option value="">Choose a hotel…</option>
                {hotels.data?.items.filter((h) => h.lat != null).map((h) => (
                  <option key={h.id} value={h.id}>{h.name}</option>
                ))}
              </select>
              {typeof mode === "object" && "calc" in mode ? (
                <p className="rounded-xl bg-blue-500/10 px-3.5 py-2.5 text-sm font-medium text-blue-600">Now tap any spot on the map.</p>
              ) : null}
              {calc?.result ? (
                <div className="grid grid-cols-2 gap-2 text-center">
                  <div className="rounded-xl bg-subtle p-3">
                    <p className="text-xs text-muted">{calc.result.method === "road" ? "By road" : calc.result.method === "estimated" ? "Estimated road" : "Straight line"}</p>
                    <p className="text-xl font-bold">{calc.result.distance_km} km</p>
                    <p className="text-xs text-muted">straight: {calc.result.straight_km} km</p>
                  </div>
                  <div className={clsx("rounded-xl p-3", calc.result.too_far ? "bg-bad-soft" : "bg-brand-soft")}>
                    <p className="text-xs text-muted">Rider fee</p>
                    <p className={clsx("money text-xl font-bold", calc.result.too_far ? "text-bad" : "text-brand")}>
                      {calc.result.too_far ? "Too far" : money(calc.result.rider_fee ?? 0)}
                    </p>
                    <p className="text-xs text-muted">max {calc.result.max_delivery_km} km</p>
                  </div>
                </div>
              ) : calc && !calc.error ? (
                <Skeleton className="h-20" />
              ) : null}
              {calc?.error ? <ErrorNote error={calc.error} /> : null}
            </div>
          </Card>

          <SupportCard current={settings.data?.support_whatsapp ?? ""} />
          <PlatformNumberCard current={settings.data?.platform_mpesa_number ?? ""} />

          <Card title="Hotel locations" subtitle="Fees are measured from here. Without a location, the nearest band is charged.">
            {hotels.isLoading ? (
              <Skeleton className="h-24" />
            ) : (
              <ul className="flex flex-col gap-2">
                {hotels.data?.items.map((h) => (
                  <li key={h.id} className="flex items-center justify-between gap-2 rounded-xl border border-line px-3 py-2.5">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold">{h.name}</span>
                      <span className={clsx("text-xs", h.lat != null ? "text-ok" : "text-warn")}>{h.lat != null ? "Placed on map" : "No location yet"}</span>
                    </span>
                    <button
                      onClick={() => setMode(placing?.id === h.id ? "circle" : { hotel: h })}
                      className={clsx(
                        "flex h-9 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold",
                        placing?.id === h.id ? "bg-ink text-white" : "border border-line hover:bg-subtle",
                      )}
                    >
                      <MapPin className="size-4" /> {placing?.id === h.id ? "Tap the map…" : h.lat != null ? "Move" : "Place"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {unplaced.length ? <p className="mt-3 text-xs text-warn">{unplaced.length} hotel{unplaced.length > 1 ? "s" : ""} still need a location.</p> : null}
            <ErrorNote error={placeHotel.error} />
          </Card>
        </div>
      </div>
    </div>
  );
}
