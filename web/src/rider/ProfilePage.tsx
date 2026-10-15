/** The rider's own profile: who they are, their bike, how they are doing and what they are owed. */
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Bike, Star } from "lucide-react";
import { useState } from "react";

import { HelpButton } from "../customer/bits";
import { useConfig } from "../customer/OrderPanel";
import { api } from "../lib/api";
import { money } from "../lib/format";
import type { RiderMe } from "./RiderHome";

type Group = "waiting" | "on_the_way" | "delivered" | "failed" | "cancelled";
type SummaryOrder = { code: string; hotel_name: string; status: string; group: Group; rider_fee: number; at: string };
type Summary = { counts: Record<Group, number>; earned: number; open_now: number; orders: SummaryOrder[]; has_more: boolean };
type Earnings = { owed: number; payouts: { id: string; amount: number; mpesa_code: string; paid_at: string }[] };

const STATUS: Record<RiderMe["kyc_status"], { text: string; tone: string }> = {
  draft: { text: "Application not sent", tone: "bg-subtle text-muted" },
  pending: { text: "Being checked", tone: "bg-warn-soft text-warn" },
  approved: { text: "Approved", tone: "bg-ok-soft text-ok" },
  rejected: { text: "Needs fixing", tone: "bg-bad-soft text-bad" },
  suspended: { text: "Paused", tone: "bg-bad-soft text-bad" },
};

const day = new Intl.DateTimeFormat("en-KE", { day: "numeric", month: "short", year: "numeric", timeZone: "Africa/Nairobi" });
const paidOn = new Intl.DateTimeFormat("en-KE", { weekday: "short", day: "numeric", month: "short", timeZone: "Africa/Nairobi" });

/** 0712 345 678 style from +2547… / 2547… */
function localPhone(p: string | null | undefined) {
  if (!p) return "";
  const d = p.replace(/\D/g, "");
  return d.startsWith("254") ? `0${d.slice(3)}` : p;
}

function Row({ k, v }: { k: string; v: string | null | undefined }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="text-sm text-muted">{k}</dt>
      <dd className="text-right text-sm font-medium">{v || "Not added"}</dd>
    </div>
  );
}

const PERIODS = [
  { id: "today", label: "Today" },
  { id: "week", label: "This week" },
  { id: "month", label: "This month" },
  { id: "all", label: "All time" },
] as const;
type Period = (typeof PERIODS)[number]["id"];

const GROUPS: { id: Group; label: string; tone: string }[] = [
  { id: "delivered", label: "Delivered", tone: "bg-ok-soft text-ok" },
  { id: "waiting", label: "Pending pickup", tone: "bg-warn-soft text-warn" },
  { id: "on_the_way", label: "On the way", tone: "bg-brand-soft text-brand" },
  { id: "cancelled", label: "Cancelled", tone: "bg-subtle text-muted" },
  { id: "failed", label: "Failed", tone: "bg-bad-soft text-bad" },
];

const when = new Intl.DateTimeFormat("en-KE", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Africa/Nairobi" });

/** How the rider's orders went: counts by outcome and a filterable list, by day, week or month. */
function Breakdown({ owed }: { owed: number | undefined }) {
  const [period, setPeriod] = useState<Period>("today");
  const [only, setOnly] = useState<Group | null>(null);
  const PAGE = 30;
  // Counts and earnings come from the server for the whole period; the list loads a page at a time.
  const q = useInfiniteQuery({
    queryKey: ["rider", "summary", period, only],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api.get<Summary>(`/rider/summary?period=${period}&limit=${PAGE}&offset=${pageParam}${only ? `&group=${only}` : ""}`),
    getNextPageParam: (last, pages) => (last.has_more ? pages.length * PAGE : undefined),
    refetchInterval: 30_000,
    placeholderData: (prev) => prev,
  });
  const first = q.data?.pages[0];
  if (!first) return <p className="rounded-3xl bg-surface p-5 text-sm text-muted shadow-sm">Loading your orders…</p>;
  const count = (g: Group) => first.counts[g];
  const earned = first.earned;
  const shown = q.data!.pages.flatMap((p) => p.orders);
  const summary = first;

  return (
    <section className="rounded-3xl bg-surface p-5 shadow-sm">
      <h2 className="mb-3 text-sm font-bold">My orders</h2>
      <div role="tablist" className="mb-4 grid grid-cols-4 gap-1 rounded-xl bg-subtle p-1">
        {PERIODS.map((p) => (
          <button
            key={p.id}
            role="tab"
            aria-selected={period === p.id}
            onClick={() => setPeriod(p.id)}
            className={clsx("h-9 rounded-lg text-xs font-semibold sm:text-sm", period === p.id ? "bg-surface shadow-sm" : "text-muted")}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="mb-3 grid grid-cols-2 gap-3">
        <div className="rounded-2xl bg-ok-soft/60 p-4">
          <p className="text-xs text-muted">Earned from deliveries</p>
          <p className="money text-xl font-extrabold text-ok">{money(earned)}</p>
        </div>
        <div className="rounded-2xl bg-subtle p-4">
          <p className="text-xs text-muted">Owed to you</p>
          <p className="money text-xl font-extrabold">{owed == null ? "…" : money(owed)}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {GROUPS.map((g) => (
          <button
            key={g.id}
            onClick={() => setOnly(only === g.id ? null : g.id)}
            aria-pressed={only === g.id}
            className={clsx("rounded-2xl p-3 text-left ring-2 transition", g.tone, only === g.id ? "ring-current" : "ring-transparent")}
          >
            <span className="money block text-2xl font-extrabold">{count(g.id)}</span>
            <span className="block text-xs font-semibold">{g.label}</span>
          </button>
        ))}
        <div className="rounded-2xl bg-subtle p-3 text-muted">
          <span className="money block text-2xl font-extrabold">{summary.open_now}</span>
          <span className="block text-xs font-semibold">Open to take now</span>
        </div>
      </div>

      <ul className="mt-4 divide-y divide-line text-sm">
        {shown.map((o) => {
          const g = GROUPS.find((x) => x.id === o.group)!;
          return (
            <li key={o.code} className="flex items-center justify-between gap-3 py-2.5">
              <span className="min-w-0">
                <span className="money block font-bold">#{o.code} <span className="font-normal text-muted">· {o.hotel_name}</span></span>
                <span className="block text-xs text-muted">{when.format(new Date(o.at))}</span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1">
                <span className={clsx("rounded-full px-2.5 py-0.5 text-xs font-semibold", g.tone)}>{g.label}</span>
                {o.group === "delivered" ? <span className="money text-xs font-bold text-ok">{money(o.rider_fee)}</span> : null}
              </span>
            </li>
          );
        })}
        {shown.length === 0 ? <li className="py-6 text-center text-muted">No orders here for this time.</li> : null}
      </ul>
      {q.hasNextPage ? (
        <button onClick={() => void q.fetchNextPage()} disabled={q.isFetchingNextPage} className="mt-3 h-10 w-full rounded-xl border border-line text-sm font-semibold hover:bg-subtle disabled:opacity-60">
          {q.isFetchingNextPage ? "Loading…" : "Show more"}
        </button>
      ) : null}
    </section>
  );
}

export function ProfileView({ me }: { me: RiderMe }) {
  const config = useConfig();
  const approved = me.kyc_status === "approved";
  const earnings = useQuery({ queryKey: ["rider", "earnings"], queryFn: () => api.get<Earnings>("/rider/earnings"), enabled: approved });

  const status = STATUS[me.kyc_status];
  const idShown = me.national_id ? `${"•".repeat(Math.max(me.national_id.length - 3, 0))}${me.national_id.slice(-3)}` : "";

  return (
    <div className="flex flex-col gap-4">
      <section className="flex items-center gap-4 rounded-3xl bg-surface p-5 shadow-sm">
        {me.photo_url ? (
          <img src={me.photo_url} alt="" className="size-20 shrink-0 rounded-full object-cover ring-2 ring-brand/30" />
        ) : (
          <span className="flex size-20 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand"><Bike className="size-9" /></span>
        )}
        <div className="min-w-0">
          <h1 className="truncate text-xl font-bold">{me.name}</h1>
          <p className="money text-sm text-muted">{localPhone(me.phone)}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={clsx("rounded-full px-2.5 py-1 text-xs font-semibold", status.tone)}>{status.text}</span>
            {approved ? (
              <span className={clsx("rounded-full px-2.5 py-1 text-xs font-semibold", me.is_online ? "bg-ok-soft text-ok" : "bg-subtle text-muted")}>
                {me.is_online ? "Online" : "Offline"}
              </span>
            ) : null}
            {me.rating != null ? (
              <span className="flex items-center gap-1 rounded-full bg-warn-soft px-2.5 py-1 text-xs font-semibold text-warn">
                <Star className="size-3.5 fill-current" /> {me.rating.toFixed(1)} ({me.rating_count})
              </span>
            ) : null}
          </div>
        </div>
      </section>

      {me.kyc_note && me.kyc_status !== "approved" ? (
        <p className="rounded-2xl bg-bad-soft p-4 text-sm text-bad">{me.kyc_note}</p>
      ) : null}

      {approved ? <Breakdown owed={earnings.data?.owed} /> : null}

      <section className="rounded-3xl bg-surface p-5 shadow-sm">
        <h2 className="mb-1 text-sm font-bold">My bike</h2>
        <dl className="divide-y divide-line">
          <Row k="Number plate" v={me.bike_plate} />
          <Row k="Bike" v={me.bike_description} />
        </dl>
      </section>

      <section className="rounded-3xl bg-surface p-5 shadow-sm">
        <h2 className="mb-1 text-sm font-bold">My details</h2>
        <dl className="divide-y divide-line">
          <Row k="Phone" v={localPhone(me.phone)} />
          <Row k="ID number" v={idShown} />
          <Row k="Lives in" v={me.residence_area} />
          <Row k="Next of kin" v={me.next_of_kin} />
          <Row k="Next of kin phone" v={localPhone(me.next_of_kin_phone)} />
          <Row k="Riding with Chakula since" v={day.format(new Date(me.created_at))} />
        </dl>
        <p className="mt-3 text-xs text-muted">To change any of these, message the Chakula team on WhatsApp below.</p>
      </section>

      {approved && earnings.data?.payouts.length ? (
        <section className="rounded-3xl bg-surface p-5 shadow-sm">
          <h2 className="mb-1 text-sm font-bold">Payouts sent to you</h2>
          <ul className="divide-y divide-line text-sm">
            {earnings.data.payouts.slice(0, 5).map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2 py-2.5">
                <span><strong className="money tracking-wide">{p.mpesa_code}</strong> · {paidOn.format(new Date(p.paid_at))}</span>
                <span className="money font-bold">{money(p.amount)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <HelpButton number={config.data?.support_whatsapp} message={`Hello Chakula, I am rider ${me.name} and I need help with `} />
    </div>
  );
}
