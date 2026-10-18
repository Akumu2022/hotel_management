/**
 * Dashboard reports, shared by the hotel admin (their hotel) and the super
 * admin (all hotels, commission). Numbers come from the ledger, so they match statements.
 * Charts are plain SVG/CSS bars: readable on a phone, nothing to download.
 */
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Banknote, Download, Gift, HandCoins, Percent, Printer, ReceiptText, ShoppingBag, Smartphone, TrendingUp } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { api, auth, getAllPages, request } from "../lib/api";
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
  by_hour_sales: number[];
  by_weekday: { orders: number; sales: number }[];
  item_ranking: { name: string; quantity: number; sales: number }[];
  unsold_items: string[];
  per_hotel?: (Totals & { hotel_id: string; hotel: string; kind: "hotel" | "liquor" })[];
  by_kind?: Record<"hotel" | "liquor", Totals & { stores: number }>;
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


// --- Planning insights, printing and the full CSV -------------------------------------------------

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const orderWord = (n: number) => `${n} order${n === 1 ? "" : "s"}`;
const hourRange = (h: number) => `${hourLabel(h)} – ${hourLabel((h + 1) % 24)}`;

/** Best and worst of each kind. Slow hours are judged only between the first and last hour that had orders. */
function insightsOf(d: Report) {
  const orders = d.by_weekday.reduce((n, x) => n + x.orders, 0);
  if (!orders) return null;
  const pick = <T,>(xs: T[], val: (x: T) => number, best: boolean) =>
    xs.reduce((a, b) => (best ? (val(b) > val(a) ? b : a) : val(b) < val(a) ? b : a));
  const days = d.by_weekday.map((x, i) => ({ i, ...x }));
  const active = d.by_hour.map((n, h) => ({ h, n })).filter((x) => x.n > 0);
  const open = d.by_hour.map((n, h) => ({ h, n })).filter((x) => x.h >= active[0].h && x.h <= active[active.length - 1].h);
  const items = d.item_ranking;
  return {
    orders,
    busyDay: pick(days, (x) => x.orders, true),
    slowDay: pick(days, (x) => x.orders, false),
    busyHour: pick(open, (x) => x.n, true),
    slowHour: pick(open, (x) => x.n, false),
    best: items[0],
    worst: items.length > 1 ? items[items.length - 1] : null,
  };
}

/** Daily rows rolled up into weeks (Monday start) or months. */
function rollup(series: Point[], group: "week" | "month", admin: boolean) {
  const out = new Map<string, { orders: number; value: number }>();
  for (const p of series) {
    const key = group === "month" ? `${p.period.slice(0, 8)}01` : addDays(p.period, -((new Date(`${p.period}T12:00:00Z`).getUTCDay() + 6) % 7));
    const cur = out.get(key) ?? { orders: 0, value: 0 };
    out.set(key, { orders: cur.orders + p.orders, value: cur.value + (admin ? p.earnings : p.net_received) });
  }
  return [...out.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([period, v]) => ({ period, ...v }));
}

function csvOf(rows: (string | number)[][]) {
  return "\ufeff" + rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\r\n");
}

function PlanningInsights({ data }: { data: Report }) {
  const x = insightsOf(data);
  if (!x) return null;
  const cards: [string, string, string][] = [
    ["Best seller", x.best.name, `${x.best.quantity} sold · ${money(x.best.sales)}`],
    ["Slowest seller", x.worst?.name ?? "—", x.worst ? `${x.worst.quantity} sold · ${money(x.worst.sales)}` : "Only one item sold"],
    ["Busiest day", WEEKDAYS[x.busyDay.i], `${orderWord(x.busyDay.orders)} · ${money(x.busyDay.sales)}`],
    ["Slowest day", WEEKDAYS[x.slowDay.i], `${orderWord(x.slowDay.orders)} · ${money(x.slowDay.sales)}`],
    ["Busiest hour", hourRange(x.busyHour.h), orderWord(x.busyHour.n)],
    ["Slowest hour", hourRange(x.slowHour.h), orderWord(x.slowHour.n)],
  ];
  return (
    <Panel title="Plan with this" sub={`From ${orderWord(x.orders)} that went through. Pick 30 days or more for patterns you can rely on.`}>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {cards.map(([label, value, sub]) => (
          <div key={label} className="min-w-0 rounded-2xl bg-subtle p-3">
            <p className="text-xs font-medium text-muted">{label}</p>
            <p className="truncate font-bold">{value}</p>
            <p className="money truncate text-xs text-muted">{sub}</p>
          </div>
        ))}
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-bold">Orders by day of the week</h3>
          <Bars data={data.by_weekday.map((d, i) => ({ label: WEEKDAYS[i].slice(0, 3), value: d.orders }))} format={(n) => `${n} order${n === 1 ? "" : "s"}`} color="#6366f1" tick={(i) => WEEKDAYS[i].slice(0, 3)} />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-bold">Never sold in this period</h3>
          {data.unsold_items.length ? (
            <p className="text-sm text-muted">{data.unsold_items.join(", ")}</p>
          ) : (
            <p className="text-sm text-muted">Nothing to list. Choose one hotel to see menu items that did not sell.</p>
          )}
        </div>
      </div>
    </Panel>
  );
}

/** The sheet that prints (or saves as PDF). Hidden on screen; the print style shows only this. */
function PrintReport({ data, daily, range, title, admin, foodLabel }: { data: Report; daily: Point[]; range: { start: string; end: string }; title: string; admin: boolean; foodLabel: string }) {
  const t = data.totals;
  const x = insightsOf(data);
  const money2 = admin ? "Earnings" : "Revenue";
  const table = (head: string[], body: (string | number)[][], right = 1) => (
    <table className="mb-4 w-full text-[0.8rem]">
      <thead><tr className="border-b border-black text-left">{head.map((h, i) => <th key={h} className={clsx("py-1 pr-2 font-semibold", i >= right && "text-right")}>{h}</th>)}</tr></thead>
      <tbody>{body.map((r, i) => <tr key={i} className="break-inside-avoid border-b border-gray-300">{r.map((c, j) => <td key={j} className={clsx("py-1 pr-2", j >= right && "text-right")}>{c}</td>)}</tr>)}</tbody>
    </table>
  );
  const h2 = (s: string) => <h2 className="mt-5 mb-1 text-base font-bold break-after-avoid">{s}</h2>;
  const days = daily.map((p) => [periodLabel(p.period, "day"), p.orders, money(admin ? p.earnings : p.net_received)]);
  const weeks = rollup(daily, "week", admin).map((r) => [`Week of ${periodLabel(r.period, "day")}`, r.orders, money(r.value)]);
  const months = rollup(daily, "month", admin).map((r) => [new Date(`${r.period}T12:00:00+03:00`).toLocaleDateString("en-KE", { month: "long", year: "numeric" }), r.orders, money(r.value)]);
  const activeHours = data.by_hour.map((n, h) => ({ h, n })).filter((r) => r.n > 0);
  return (
    <div id="print-report" style={{ color: "#111", background: "#fff", padding: "0.5rem", fontSize: "0.85rem" }}>
      <h1 className="text-2xl font-bold">{title}</h1>
      <p className="mb-3">Sales and planning report · {periodLabel(range.start, "day")} to {periodLabel(range.end, "day")} · printed {new Date().toLocaleDateString("en-KE", { day: "numeric", month: "short", year: "numeric" })}</p>
      <div className="mb-2 grid grid-cols-4 gap-3">
        {([
          ["Money received", money(t.net_received)],
          ["Orders", String(t.orders)],
          ["Average order", money(t.average_order)],
          [foodLabel, money(t.food_sales)],
        ] as const).map(([k, v]) => <div key={k} className="rounded border border-gray-400 p-2"><p className="text-xs">{k}</p><p className="font-bold">{v}</p></div>)}
      </div>
      <p>{t.deliveries} deliveries · {t.pickups} pickups · M-Pesa {money(t.mpesa)} · cash {money(t.cash)}{admin ? ` · platform earnings ${money(t.earnings)}` : ""}</p>
      {x ? (
        <>
          {h2("What the numbers say")}
          <ul className="list-disc pl-5">
            <li>Best seller: <strong>{x.best.name}</strong> ({x.best.quantity} sold, {money(x.best.sales)}).</li>
            {x.worst ? <li>Slowest seller: <strong>{x.worst.name}</strong> ({x.worst.quantity} sold, {money(x.worst.sales)}).</li> : null}
            <li>Busiest day: <strong>{WEEKDAYS[x.busyDay.i]}</strong> ({orderWord(x.busyDay.orders)}). Slowest day: <strong>{WEEKDAYS[x.slowDay.i]}</strong> ({orderWord(x.slowDay.orders)}).</li>
            <li>Busiest hour: <strong>{hourRange(x.busyHour.h)}</strong> ({orderWord(x.busyHour.n)}). Slowest hour: <strong>{hourRange(x.slowHour.h)}</strong> ({orderWord(x.slowHour.n)}).</li>
          </ul>
        </>
      ) : null}
      {h2(`${money2} by month`)}
      {table(["Month", "Orders", money2], months)}
      {h2(`${money2} by week`)}
      {table(["Week", "Orders", money2], weeks)}
      {h2(`${money2} by day`)}
      {table(["Day", "Orders", money2], days)}
      {h2("Day of the week")}
      {table(["Day", "Orders", foodLabel], data.by_weekday.map((d, i) => [WEEKDAYS[i], d.orders, money(d.sales)]))}
      {h2("Hour of the day")}
      {table(["Hour", "Orders", foodLabel], activeHours.map((r) => [hourRange(r.h), r.n, money(data.by_hour_sales[r.h])]))}
      {h2("All items, most sold to least sold")}
      {table(["Item", "Sold", "Sales"], data.item_ranking.map((it) => [it.name, it.quantity, money(it.sales)]))}
      {data.unsold_items.length ? <>{h2("Not sold at all in this period")}<p>{data.unsold_items.join(", ")}</p></> : null}
      <p className="mt-6 text-xs">Figures come from the payment ledger, so they match the weekly statements.</p>
    </div>
  );
}

// --- Main --------------------------------------------------------------------------------------

export function Reports({ scope, foodLabel = "Food sales" }: { scope: "hotel" | "admin"; foodLabel?: string }) {
  const base = scope === "admin" ? "/admin/reports" : "/hotel/reports";
  const [preset, setPreset] = useState<Preset>("7d");
  const [custom, setCustom] = useState(() => ({ start: addDays(iso(new Date()), -6), end: iso(new Date()) }));
  const [group, setGroup] = useState<"day" | "week" | "month">("day");
  const [hotelId, setHotelId] = useState("");
  const [method, setMethod] = useState<"" | "mpesa" | "cash" | "refund">("");
  const [rankBy, setRankBy] = useState<"net_received" | "earnings">("net_received");
  const range = rangeFor(preset, custom);

  const hotels = useQuery({
    queryKey: ["admin", "hotels"],
    queryFn: () => getAllPages<{ id: string; name: string }>("/admin/hotels"),
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
  const daily = useQuery({
    queryKey: [scope, "reports", qs.toString(), "day"],
    queryFn: () => api.get<Report>(`${base}?${qs}&group=day`),
    refetchInterval: 60_000,
  });
  const payQs = `${qs}${method ? `&method=${method}` : ""}`;
  const PAY_PAGE = 50;
  const rows = useInfiniteQuery({
    queryKey: [scope, "reports", "payments", payQs],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api.get<PaymentRow[]>(`${base}/payments?${payQs}&limit=${PAY_PAGE}&offset=${pageParam}`),
    getNextPageParam: (last, all) => (last.length === PAY_PAGE ? all.length * PAY_PAGE : undefined),
  });
  const payRows = rows.data?.pages.flat() ?? [];
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
  const title = admin ? (hotelId ? (hotels.data?.items.find((h) => h.id === hotelId)?.name ?? "Report") : "All hotels and stores") : "Sales report";
  const downloadReport = () => {
    const d = daily.data;
    if (!d) return;
    const m = admin ? "Earnings" : "Revenue";
    const rows: (string | number)[][] = [
      [title], ["Period", range.start, "to", range.end], [],
      ["Money received", d.totals.net_received], ["Orders", d.totals.orders], ["Average order", d.totals.average_order], [],
      ["Month", "Orders", m], ...rollup(d.series, "month", admin).map((r) => [r.period.slice(0, 7), r.orders, r.value]), [],
      ["Week starting", "Orders", m], ...rollup(d.series, "week", admin).map((r) => [r.period, r.orders, r.value]), [],
      ["Day", "Orders", m], ...d.series.map((p) => [p.period, p.orders, admin ? p.earnings : p.net_received]), [],
      ["Day of week", "Orders", "Sales"], ...d.by_weekday.map((w, i) => [WEEKDAYS[i], w.orders, w.sales]), [],
      ["Hour", "Orders", "Sales"], ...d.by_hour.map((n, h) => [hourRange(h), n, d.by_hour_sales[h]]).filter((r) => r[1]), [],
      ["Item", "Sold", "Sales"], ...d.item_ranking.map((i) => [i.name, i.quantity, i.sales]),
      ...(d.unsold_items.length ? [[], ["Not sold at all", ...d.unsold_items]] : []),
    ];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csvOf(rows)], { type: "text/csv;charset=utf-8" }));
    a.download = `report-${range.start}-to-${range.end}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
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
          <button onClick={() => window.print()} disabled={!daily.data} className="flex h-10 items-center gap-2 rounded-xl border border-line px-3 text-sm font-semibold hover:bg-subtle disabled:opacity-60">
            <Printer className="size-4" /> Print report
          </button>
          <button onClick={downloadReport} disabled={!daily.data} className="flex h-10 items-center gap-2 rounded-xl border border-line px-3 text-sm font-semibold hover:bg-subtle disabled:opacity-60">
            <Download className="size-4" /> Report CSV
          </button>
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
          <Kpi icon={<Banknote className="size-4" />} label="Average order" value={money(t.average_order)} sub={`${foodLabel} ${money(t.food_sales)}`} tone="warn" />
          <Kpi icon={<HandCoins className="size-4" />} label="Platform fees" value={money(t.commission + t.service_fee - t.bonuses)} sub={`Commission ${money(t.commission)} · service ${money(t.service_fee)}${t.bonuses ? ` · bonuses credited −${money(t.bonuses)}` : ""}`} tone="bad" />
        </div>
      )}

      {admin && report.data?.by_kind ? (
        <Panel title="Hotels vs liquor stores" sub="Money received and platform earnings, side by side">
          <div className="grid gap-3 sm:grid-cols-2">
            {(["hotel", "liquor"] as const).map((k) => {
              const b = report.data!.by_kind![k];
              const all = report.data!.by_kind!.hotel.net_received + report.data!.by_kind!.liquor.net_received;
              return (
                <div key={k} className="rounded-2xl bg-subtle p-4">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-bold">{k === "hotel" ? "Hotels (food)" : "Liquor stores (drinks)"}</span>
                    <span className="text-xs text-muted">{b.stores} active · {b.orders} orders</span>
                  </div>
                  <p className="money mt-1 text-2xl font-bold">{money(b.net_received)}</p>
                  <p className="text-xs text-muted">Platform earnings <span className="money font-semibold text-ok">{money(b.earnings)}</span> · {all ? Math.round((b.net_received / all) * 100) : 0}% of money received</p>
                  <div className="mt-2 h-2 rounded-full bg-surface"><div className="h-2 rounded-full bg-brand" style={{ width: `${all ? (b.net_received / all) * 100 : 0}%` }} /></div>
                </div>
              );
            })}
          </div>
        </Panel>
      ) : null}

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

      {report.data ? <PlanningInsights data={report.data} /> : null}

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
          <Panel
            title="Hotels and stores ranked"
            sub="Highest to lowest"
            action={<Chips label="Rank by" value={rankBy} onChange={setRankBy} options={[{ id: "net_received", label: "Revenue" }, { id: "earnings", label: "Our earnings" }] as const} />}
          >
            {report.data?.per_hotel?.length ? (
              <div className="-mx-1 max-h-[30rem] overflow-auto">
                <table className="w-full min-w-[30rem] text-sm">
                  <thead className="text-left text-xs text-muted uppercase">
                    <tr><th className="px-1 py-2 font-semibold">#</th><th className="px-1 py-2 font-semibold">Name</th><th className="px-1 py-2 text-right font-semibold">Orders</th><th className="px-1 py-2 text-right font-semibold">Revenue</th><th className="px-1 py-2 text-right font-semibold">Commission</th><th className="px-1 py-2 text-right font-semibold">Earnings</th></tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {[...report.data.per_hotel].sort((a, b) => b[rankBy] - a[rankBy]).map((h, i) => (
                      <tr key={h.hotel_id}>
                        <td className="px-1 py-2.5 text-muted">{i + 1}</td>
                        <td className="px-1 py-2.5 font-semibold">{h.hotel} <span className={clsx("ml-1 rounded-full px-2 py-0.5 text-xs font-semibold", h.kind === "liquor" ? "bg-warn-soft text-warn" : "bg-ok-soft text-ok")}>{h.kind === "liquor" ? "Liquor" : "Hotel"}</span></td>
                        <td className="money px-1 py-2.5 text-right">{h.orders}</td>
                        <td className="money px-1 py-2.5 text-right font-bold">{money(h.net_received)}</td>
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
        ) : payRows.length ? (
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
                {payRows.map((r, i) => (
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
            {rows.hasNextPage ? (
              <button onClick={() => void rows.fetchNextPage()} disabled={rows.isFetchingNextPage} className="mx-auto my-3 flex h-10 items-center rounded-xl border border-line px-4 text-sm font-semibold hover:bg-subtle disabled:opacity-60">
                {rows.isFetchingNextPage ? "Loading…" : "Show more"}
              </button>
            ) : null}
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-muted">No payments in this period.</p>
        )}
      </Panel>

      <style>{`
        #print-report { display: none; }
        @media print {
          @page { margin: 12mm; }
          body * { visibility: hidden !important; }
          #print-report, #print-report * { visibility: visible !important; }
          #print-report { display: block !important; position: absolute; left: 0; top: 0; width: 100%; }
        }
      `}</style>
      {daily.data ? <PrintReport data={daily.data} daily={daily.data.series} range={range} title={title} admin={admin} foodLabel={foodLabel} /> : null}
    </div>
  );
}
