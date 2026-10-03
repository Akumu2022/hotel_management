/**
 * Dashboard reports (DECISIONS D19), shared by the hotel admin (their hotel) and the super
 * admin (all hotels, commission). Numbers come from the ledger, so they match statements.
 * Charts are plain SVG/CSS bars: readable on a phone, nothing to download.
 */
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Banknote, Download, Gift, HandCoins, Percent, ReceiptText, ShoppingBag, Smartphone, TrendingUp } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { api, auth, request } from "../lib/api";
import { money } from "../lib/format";
import { ErrorNote, Skeleton } from "./ui";

type Totals = {
  orders: number;
  mpesa: number;
  cash: number;
  received: number;
  refunds: number;
  net_received: number;
  commission: number;
  service_fee: number;
  bonuses: number;
  earnings: number;
  food_sales: number;
  average_order: number;
  deliveries: number;
  pickups: number;
};
type Point = Totals & { period: string };
type Report = {
  totals: Totals;
  series: Point[];
  top_items: { name: string; quantity: number; sales: number }[];
  by_hour: number[];
  per_hotel?: (Totals & { hotel_id: string; hotel: string })[];
};
type PaymentRow = { at: string; kind: "mpesa" | "cash" | "refund"; amount: number; reference: string | null; order_code: string; customer: string; order_type: string; hotel: string };

// --- Dates (Kenya days) -------------------------------------------------------------------------

/** Today's date in Kenya (UTC+3, no daylight saving), as YYYY-MM-DD. */
const iso = (d: Date) => new Date(d.getTime() + 3 * 3600_000).toISOString().slice(0, 10);
/** Calendar arithmetic on a YYYY-MM-DD date (noon UTC avoids any day-boundary slip). */
const addDays = (s: string, n: number) => new Date(Date.parse(`${s}T12:00:00Z`) + n * 86400_000).toISOString().slice(0, 10);

const PRESETS = [
  { id: "today", label: "Today" },
  { id: "7d", label: "7 days" },
  { id: "30d", label: "30 days" },
  { id: "month", label: "This month" },
  { id: "custom", label: "Custom" },
] as const;
type Preset = (typeof PRESETS)[number]["id"];

function rangeFor(p: Preset, custom: { start: string; end: string }) {
  const today = iso(new Date());
  if (p === "today") return { start: today, end: today };
  if (p === "7d") return { start: addDays(today, -6), end: today };
  if (p === "30d") return { start: addDays(today, -29), end: today };
  if (p === "month") return { start: `${today.slice(0, 8)}01`, end: today };
  return custom;
}

/** Every period in the range (empty ones too), so quiet days show as gaps, not vanish. */
function allPeriods(start: string, end: string, group: "day" | "week" | "month"): string[] {
  const out: string[] = [];
  let d = start;
  if (group === "week") {
    const dow = (new Date(`${d}T12:00:00Z`).getUTCDay() + 6) % 7; // Monday = 0
    d = addDays(d, -dow);
  } else if (group === "month") d = `${d.slice(0, 8)}01`;
  while (d <= end && out.length < 400) {
    out.push(d);
    if (group === "day") d = addDays(d, 1);
    else if (group === "week") d = addDays(d, 7);
    else {
      const [y, m] = d.split("-").map(Number);
      d = m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, "0")}-01`;
    }
  }
  return out;
}

const hourLabel = (h: number) => (h === 0 ? "12am" : h < 12 ? `${h}am` : h === 12 ? "12pm" : `${h - 12}pm`);

function periodLabel(p: string, group: string) {
  const d = new Date(`${p}T12:00:00+03:00`);
  if (group === "month") return d.toLocaleDateString("en-KE", { month: "short", year: "2-digit" });
  return d.toLocaleDateString("en-KE", { day: "numeric", month: "short" });
}

// --- Pieces ------------------------------------------------------------------------------------

function Kpi({ icon, label, value, sub, tone = "brand" }: { icon: ReactNode; label: string; value: string; sub?: string; tone?: "brand" | "ok" | "warn" | "bad" }) {
  const color = { brand: "text-brand bg-brand-soft", ok: "text-ok bg-ok-soft", warn: "text-warn bg-warn-soft", bad: "text-bad bg-bad-soft" }[tone];
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-[1.5rem] bg-surface p-4 shadow-sm sm:p-5">
      <span className="flex items-center gap-2 text-xs font-medium text-muted sm:text-sm">
        <span className={clsx("flex size-8 shrink-0 items-center justify-center rounded-lg", color)}>{icon}</span>
        {label}
      </span>
      <span className="money truncate text-xl font-bold sm:text-2xl">{value}</span>
      {sub ? <span className="text-xs text-muted">{sub}</span> : null}
    </div>
  );
}

/** Vertical bars with the value on hover/tap; the tallest bar is labelled. */
function Bars({ data, format, color = "var(--color-brand)", tick }: { data: { label: string; value: number }[]; format: (n: number) => string; color?: string; tick?: (i: number) => string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const [active, setActive] = useState<number | null>(null);
  if (!data.length) return <p className="py-10 text-center text-sm text-muted">Nothing in this period yet.</p>;
  const shown = active ?? data.findIndex((d) => d.value === max);
  const every = Math.ceil(data.length / 6); // keep axis labels readable on phones
  return (
    <div>
      <p className="mb-2 h-5 text-sm">
        <span className="font-semibold">{data[shown]?.label}</span>
        <span className="money text-muted"> · {format(data[shown]?.value ?? 0)}</span>
      </p>
      <div className="flex h-44 items-end gap-[0.1875rem]" onMouseLeave={() => setActive(null)}>
        {data.map((d, i) => (
          <button
            key={i}
            aria-label={`${d.label}: ${format(d.value)}`}
            onMouseEnter={() => setActive(i)}
            onFocus={() => setActive(i)}
            onClick={() => setActive(i)}
            className="group flex h-full min-w-0 flex-1 items-end"
          >
            <span
              className={clsx("w-full rounded-t-md transition-opacity", shown === i ? "opacity-100" : "opacity-60 group-hover:opacity-90")}
              style={{ height: `${d.value ? Math.max((d.value / max) * 100, 2) : 0}%`, background: color }}
            />
          </button>
        ))}
      </div>
      <div className="mt-1.5 flex gap-[0.1875rem] text-xs text-muted">
        {data.map((d, i) => (
          <span key={i} className="min-w-0 flex-1 overflow-visible text-center whitespace-nowrap">{tick ? tick(i) : i % every === 0 ? d.label : ""}</span>
        ))}
      </div>
    </div>
  );
}

function Panel({ title, sub, children, action }: { title: string; sub?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="min-w-0 rounded-[1.5rem] bg-surface p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold">{title}</h2>
          {sub ? <p className="text-sm text-muted">{sub}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Chips<T extends string>({ value, options, onChange, label }: { value: T; options: readonly { id: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1 rounded-xl bg-subtle p-1">
      {options.map((o) => (
        <button key={o.id} role="radio" aria-checked={value === o.id} onClick={() => onChange(o.id)} className={clsx("h-9 rounded-lg px-3 text-sm font-semibold", value === o.id ? "bg-surface shadow-sm" : "text-muted hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

const KIND = { mpesa: { label: "M-Pesa", cls: "bg-ok-soft text-ok" }, cash: { label: "Cash", cls: "bg-warn-soft text-warn" }, refund: { label: "Refund", cls: "bg-bad-soft text-bad" } } as const;

// --- Main --------------------------------------------------------------------------------------

export function Reports({ scope }: { scope: "hotel" | "admin" }) {
  const base = scope === "admin" ? "/admin/reports" : "/hotel/reports";
  const [preset, setPreset] = useState<Preset>("7d");
  const [custom, setCustom] = useState(() => ({ start: addDays(iso(new Date()), -6), end: iso(new Date()) }));
  const [group, setGroup] = useState<"day" | "week" | "month">("day");
  const [hotelId, setHotelId] = useState("");
  const [method, setMethod] = useState<"" | "mpesa" | "cash" | "refund">("");
  const range = rangeFor(preset, custom);

  const hotels = useQuery({
    queryKey: ["admin", "hotels"],
    queryFn: () => api.get<{ items: { id: string; name: string }[] }>("/admin/hotels?limit=100"),
    enabled: scope === "admin",
  });
  const qs = useMemo(() => {
    const p = new URLSearchParams({ start: range.start, end: range.end });
    if (hotelId) p.set("hotel_id", hotelId);
    return p;
  }, [range.start, range.end, hotelId]);
  const report = useQuery({
    queryKey: [scope, "reports", qs.toString(), group],
    queryFn: () => api.get<Report>(`${base}?${qs}&group=${group}`),
    refetchInterval: 60_000,
  });
  const payQs = `${qs}${method ? `&method=${method}` : ""}`;
  const rows = useQuery({ queryKey: [scope, "reports", "payments", payQs], queryFn: () => api.get<PaymentRow[]>(`${base}/payments?${payQs}`) });
  const [downloading, setDownloading] = useState(false);

  const downloadCsv = async () => {
    setDownloading(true);
    try {
      // A file download can't go through the JSON client: make sure the login is fresh (this
      // refreshes an expired token), then fetch with the token header.
      await request("GET", "/auth/me");
      const res = await fetch(`/api/v1${base}/payments?${payQs}&format=csv`, { headers: { Authorization: `Bearer ${auth.token()}` } });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `payments-${range.start}-to-${range.end}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } finally {
      setDownloading(false);
    }
  };

  const t = report.data?.totals;
  const admin = scope === "admin";
  const series = report.data?.series ?? [];

  return (
    <div className="flex flex-col gap-5">
      {/* Filters */}
      <div className="flex flex-col gap-3 rounded-[1.5rem] bg-surface p-4 shadow-sm lg:flex-row lg:items-center lg:justify-between">
        <Chips label="Period" value={preset} options={PRESETS} onChange={setPreset} />
        <div className="flex flex-wrap items-center gap-2">
          {preset === "custom" ? (
            <>
              <input type="date" aria-label="From" value={custom.start} max={custom.end} onChange={(e) => setCustom((c) => ({ ...c, start: e.target.value }))} className="h-10 rounded-xl border border-line bg-surface px-3 text-sm" />
              <span className="text-muted">to</span>
              <input type="date" aria-label="To" value={custom.end} min={custom.start} onChange={(e) => setCustom((c) => ({ ...c, end: e.target.value }))} className="h-10 rounded-xl border border-line bg-surface px-3 text-sm" />
            </>
          ) : null}
          {admin ? (
            <select aria-label="Hotel" value={hotelId} onChange={(e) => setHotelId(e.target.value)} className="h-10 rounded-xl border border-line bg-surface px-3 text-sm font-medium">
              <option value="">All hotels</option>
              {hotels.data?.items.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
          ) : null}
        </div>
      </div>
      <ErrorNote error={report.error} />

      {!t ? (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-32 rounded-[1.5rem]" />)}</div>
      ) : admin ? (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          <Kpi icon={<TrendingUp className="size-4" />} label="Platform earnings" value={money(t.earnings)} sub="Commission + service fees − bonuses" tone="ok" />
          <Kpi icon={<Percent className="size-4" />} label="Commission" value={money(t.commission)} sub={`Service fees ${money(t.service_fee)}`} />
          <Kpi icon={<ReceiptText className="size-4" />} label="Money received" value={money(t.received)} sub={`${t.orders} orders · refunds ${money(t.refunds)}`} tone="warn" />
          <Kpi icon={<Gift className="size-4" />} label="Bonuses paid" value={money(t.bonuses)} sub="Stamp card and free delivery" tone="bad" />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          <Kpi icon={<ReceiptText className="size-4" />} label="Money received" value={money(t.net_received)} sub={`M-Pesa ${money(t.mpesa)} · cash ${money(t.cash)}${t.refunds ? ` · refunds −${money(t.refunds)}` : ""}`} tone="ok" />
          <Kpi icon={<ShoppingBag className="size-4" />} label="Orders" value={String(t.orders)} sub={`${t.deliveries} delivery · ${t.pickups} pickup`} />
          <Kpi icon={<Banknote className="size-4" />} label="Average order" value={money(t.average_order)} sub={`Food sales ${money(t.food_sales)}`} tone="warn" />
          <Kpi icon={<HandCoins className="size-4" />} label="Platform fees" value={money(t.commission + t.service_fee - t.bonuses)} sub={`Commission ${money(t.commission)} · service ${money(t.service_fee)}${t.bonuses ? ` · bonuses credited −${money(t.bonuses)}` : ""}`} tone="bad" />
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[1fr_360px]">
        <Panel
          title={admin ? "Earnings over time" : "Money received over time"}
          sub={`${periodLabel(range.start, "day")} – ${periodLabel(range.end, "day")}`}
          action={<Chips label="Group by" value={group} onChange={setGroup} options={[{ id: "day", label: "Day" }, { id: "week", label: "Week" }, { id: "month", label: "Month" }] as const} />}
        >
          {report.isLoading ? (
            <Skeleton className="h-52" />
          ) : (
            <Bars
              data={allPeriods(range.start, range.end, group).map((p) => {
                const hit = series.find((s) => s.period === p);
                return { label: periodLabel(p, group), value: hit ? (admin ? hit.earnings : hit.net_received) : 0 };
              })}
              format={money}
              color={admin ? "var(--color-ok)" : "var(--color-brand)"}
            />
          )}
        </Panel>
        <Panel title="Busiest hours" sub="Orders by time of day (Kenya time)">
          {report.isLoading ? <Skeleton className="h-52" /> : (
            <Bars data={(report.data?.by_hour ?? []).map((n, h) => ({ label: hourLabel(h), value: n }))} format={(n) => `${n} order${n === 1 ? "" : "s"}`} color="#f59e0b" tick={(h) => (h % 6 === 0 ? hourLabel(h) : "")} />
          )}
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Best sellers" sub="By sales in this period">
          {report.data?.top_items.length ? (
            <ol className="flex flex-col gap-3">
              {report.data.top_items.map((it, i) => {
                const top = report.data!.top_items[0].sales || 1;
                return (
                  <li key={it.name} className="text-sm">
                    <div className="mb-1 flex justify-between gap-2">
                      <span className="truncate font-semibold">{i + 1}. {it.name}</span>
                      <span className="money shrink-0 text-muted">{it.quantity} sold · {money(it.sales)}</span>
                    </div>
                    <div className="h-2 rounded-full bg-subtle"><div className="h-2 rounded-full bg-brand" style={{ width: `${(it.sales / top) * 100}%` }} /></div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="py-8 text-center text-sm text-muted">No sales in this period yet.</p>
          )}
        </Panel>

        {admin ? (
          <Panel title="By hotel" sub="Commission and fees each hotel brought in">
            {report.data?.per_hotel?.length ? (
              <div className="-mx-1 overflow-x-auto">
                <table className="w-full min-w-[26.25rem] text-sm">
                  <thead className="text-left text-xs text-muted uppercase">
                    <tr><th className="px-1 py-2 font-semibold">Hotel</th><th className="px-1 py-2 text-right font-semibold">Orders</th><th className="px-1 py-2 text-right font-semibold">Received</th><th className="px-1 py-2 text-right font-semibold">Commission</th><th className="px-1 py-2 text-right font-semibold">Earnings</th></tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {report.data.per_hotel.map((h) => (
                      <tr key={h.hotel_id}>
                        <td className="px-1 py-2.5 font-semibold">{h.hotel}</td>
                        <td className="money px-1 py-2.5 text-right">{h.orders}</td>
                        <td className="money px-1 py-2.5 text-right">{money(h.received)}</td>
                        <td className="money px-1 py-2.5 text-right">{money(h.commission)}</td>
                        <td className="money px-1 py-2.5 text-right font-bold text-ok">{money(h.earnings)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="py-8 text-center text-sm text-muted">No orders in this period yet.</p>
            )}
          </Panel>
        ) : (
          <Panel title="Payment methods" sub="How customers paid">
            {t && t.received ? (
              <div className="flex flex-col gap-4">
                {([["M-Pesa", t.mpesa, "bg-ok", <Smartphone key="m" className="size-4" />], ["Cash at the counter", t.cash, "bg-warn", <Banknote key="c" className="size-4" />]] as const).map(([label, v, bg, icon]) => (
                  <div key={label} className="text-sm">
                    <div className="mb-1 flex justify-between"><span className="flex items-center gap-1.5 font-semibold">{icon} {label}</span><span className="money text-muted">{money(v)} · {Math.round((v / t.received) * 100)}%</span></div>
                    <div className="h-3 rounded-full bg-subtle"><div className={clsx("h-3 rounded-full", bg)} style={{ width: `${(v / t.received) * 100}%` }} /></div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="py-8 text-center text-sm text-muted">No payments in this period yet.</p>
            )}
          </Panel>
        )}
      </div>

      <Panel
        title="Payments history"
        sub="Every payment and refund, newest first"
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Chips label="Payment type" value={method} onChange={setMethod} options={[{ id: "", label: "All" }, { id: "mpesa", label: "M-Pesa" }, { id: "cash", label: "Cash" }, { id: "refund", label: "Refunds" }] as const} />
            <button onClick={downloadCsv} disabled={downloading} className="flex h-10 items-center gap-2 rounded-xl border border-line px-3 text-sm font-semibold hover:bg-subtle disabled:opacity-60">
              <Download className="size-4" /> {downloading ? "Preparing…" : "CSV"}
            </button>
          </div>
        }
      >
        {rows.isLoading ? (
          <Skeleton className="h-40" />
        ) : rows.data?.length ? (
          <div className="-mx-1 max-h-[30rem] overflow-auto">
            <table className="w-full min-w-[35rem] text-sm">
              <thead className="sticky top-0 bg-surface text-left text-xs text-muted uppercase">
                <tr>
                  <th className="px-1 py-2 font-semibold">When</th>
                  <th className="px-1 py-2 font-semibold">Type</th>
                  <th className="px-1 py-2 font-semibold">Order</th>
                  {admin ? <th className="px-1 py-2 font-semibold">Hotel</th> : null}
                  <th className="px-1 py-2 font-semibold">M-Pesa code</th>
                  <th className="px-1 py-2 text-right font-semibold">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.data.map((r, i) => (
                  <tr key={i}>
                    <td className="px-1 py-2.5 whitespace-nowrap text-muted">{new Date(r.at).toLocaleString("en-KE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                    <td className="px-1 py-2.5"><span className={clsx("rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap", KIND[r.kind].cls)}>{KIND[r.kind].label}</span></td>
                    <td className="px-1 py-2.5"><strong>#{r.order_code}</strong> <span className="text-muted">· {r.customer}</span></td>
                    {admin ? <td className="px-1 py-2.5">{r.hotel}</td> : null}
                    <td className="money px-1 py-2.5 text-muted">{r.reference ?? "—"}</td>
                    <td className={clsx("money px-1 py-2.5 text-right font-bold", r.kind === "refund" && "text-bad")}>{r.kind === "refund" ? "−" : ""}{money(r.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-muted">No payments in this period.</p>
        )}
      </Panel>
    </div>
  );
}
